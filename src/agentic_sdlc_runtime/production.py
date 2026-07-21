from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OPAPolicyDecisionPoint:
    def __init__(self, url: str, timeout: float = 3.0):
        self.url, self.timeout = url, timeout

    def authorize(self, policy_input: dict) -> dict:
        request = urllib.request.Request(
            self.url, data=json.dumps({"input": policy_input}).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read())["result"]
        except Exception as error:
            raise PermissionError("PDP unavailable; fail closed") from error
        decision = result if isinstance(result, dict) else {"allow": bool(result)}
        if not decision.get("allow", False):
            raise PermissionError(decision.get("reason", "policy denied"))
        return decision


@dataclass(frozen=True)
class WorkloadIdentity:
    token: str
    audience: str
    subject_hint: str
    fingerprint: str


class GitHubOIDCIdentityProvider:
    def acquire(self, audience: str) -> WorkloadIdentity:
        url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
        separator = "&" if "?" in url else "?"
        request = urllib.request.Request(
            f"{url}{separator}audience={audience}",
            headers={"Authorization": f"Bearer {os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']}"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            token = json.loads(response.read())["value"]
        return WorkloadIdentity(
            token=token, audience=audience,
            subject_hint=os.environ.get("GITHUB_REPOSITORY", "unknown"),
            fingerprint=hashlib.sha256(token.encode()).hexdigest()[:16],
        )


class S3EvidenceStore:
    """Immutable object adapter. Bucket versioning/object-lock is an infrastructure prerequisite."""

    def __init__(self, bucket: str, prefix: str = "evidence", client=None):
        if client is None:
            import boto3
            client = boto3.client("s3")
        self.bucket, self.prefix, self.client = bucket, prefix.strip("/"), client

    def put(self, change_id: str, run_id: str, kind: str, payload: dict) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(body).hexdigest()
        key = f"{self.prefix}/{change_id}/{run_id}/{kind}-{digest}.json"
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType="application/json",
            Metadata={"sha256": digest, "change-id": change_id},
            ChecksumSHA256=__import__("base64").b64encode(bytes.fromhex(digest)).decode(),
        )
        return f"s3://{self.bucket}/{key}"


class BudgetExceeded(RuntimeError):
    pass


class BudgetLedger:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS usage(change_id TEXT PRIMARY KEY, tokens INTEGER, cost REAL)")
        self.db.commit()

    def consume(self, change_id: str, *, tokens: int, cost: float,
                token_limit: int, cost_limit: float) -> dict:
        current = self.db.execute(
            "SELECT tokens,cost FROM usage WHERE change_id=?", (change_id,)
        ).fetchone() or (0, 0.0)
        total = (current[0] + tokens, current[1] + cost)
        if total[0] > token_limit or total[1] > cost_limit:
            raise BudgetExceeded("change budget exceeded")
        self.db.execute(
            "INSERT INTO usage VALUES(?,?,?) ON CONFLICT(change_id) DO UPDATE SET tokens=?,cost=?",
            (change_id, *total, *total),
        )
        self.db.commit()
        return {"change_id": change_id, "tokens": total[0], "cost": total[1]}


class SQLiteWorkQueue:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY, payload TEXT, status TEXT, attempts INTEGER, available REAL, lease_until REAL)""")
        self.db.commit()

    def publish(self, payload: dict) -> str:
        job_id = uuid.uuid4().hex
        self.db.execute("INSERT INTO jobs VALUES(?,?, 'queued',0,?,0)", (job_id, json.dumps(payload), time.time()))
        self.db.commit()
        return job_id

    def claim(self, lease_seconds: int = 60) -> dict | None:
        now = time.time()
        row = self.db.execute(
            "SELECT id,payload,attempts FROM jobs WHERE (status='queued' AND available<=?) "
            "OR (status='running' AND lease_until<?) ORDER BY available LIMIT 1", (now, now)
        ).fetchone()
        if not row:
            return None
        self.db.execute(
            "UPDATE jobs SET status='running',attempts=attempts+1,lease_until=? WHERE id=?",
            (now + lease_seconds, row[0]),
        )
        self.db.commit()
        return {"id": row[0], "payload": json.loads(row[1]), "attempts": row[2] + 1}

    def ack(self, job_id: str) -> None:
        self.db.execute("UPDATE jobs SET status='completed' WHERE id=?", (job_id,))
        self.db.commit()

    def retry(self, job_id: str, delay: float) -> None:
        self.db.execute(
            "UPDATE jobs SET status='queued',available=?,lease_until=0 WHERE id=?",
            (time.time() + delay, job_id),
        )
        self.db.commit()


class SQSWorkQueue:
    def __init__(self, queue_url: str, client=None):
        if client is None:
            import boto3
            client = boto3.client("sqs")
        self.queue_url, self.client = queue_url, client

    def publish(self, payload: dict) -> str:
        return self.client.send_message(
            QueueUrl=self.queue_url, MessageBody=json.dumps(payload)
        )["MessageId"]


class OTLPHTTPExporter:
    def __init__(self, endpoint: str, headers: dict[str, str] | None = None):
        self.endpoint, self.headers = endpoint, headers or {}

    def emit(self, record: dict) -> None:
        body = json.dumps({"resourceLogs": [{"scopeLogs": [{"logRecords": [record]}]}]}).encode()
        request = urllib.request.Request(
            self.endpoint, data=body, method="POST",
            headers={"Content-Type": "application/json", **self.headers},
        )
        with urllib.request.urlopen(request, timeout=5):
            pass


class SupplyChainAttestor:
    def __init__(self, runner):
        self.runner = runner

    def attest(self, image: str) -> dict:
        sbom = self.runner.run(["syft", image, "-o", "cyclonedx-json"])
        sign = self.runner.run(["cosign", "sign", "--yes", image])
        return {"image": image, "sbom": sbom.stdout, "signature": sign.returncode == 0}


class DockerSandbox:
    def __init__(self, runner):
        self.runner = runner

    def execute(self, image: str, command: list[str]) -> Any:
        return self.runner.run([
            "docker", "run", "--rm", "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--memory=512m", "--cpus=1", image, *command,
        ])


class ChangeSetCoordinator:
    def __init__(self, changes: list[dict]):
        self.changes = changes

    def promotion_order(self) -> list[str]:
        dependencies = {c["repository"]: set(c.get("depends_on", [])) for c in self.changes}
        order = []
        while dependencies:
            ready = sorted(repo for repo, deps in dependencies.items() if not deps)
            if not ready:
                raise ValueError("cyclic multi-repository Change Set")
            order.extend(ready)
            for repo in ready:
                dependencies.pop(repo)
            for deps in dependencies.values():
                deps.difference_update(ready)
        return order


class SLORecoveryPolicy:
    def __init__(self, *, error_rate: float, latency_ms: float):
        self.error_rate, self.latency_ms = error_rate, latency_ms

    def evaluate(self, sample: dict) -> dict:
        breached = (
            sample.get("error_rate", 0) > self.error_rate
            or sample.get("p95_latency_ms", 0) > self.latency_ms
        )
        return {"breached": breached, "action": "rollback" if breached else "continue"}
