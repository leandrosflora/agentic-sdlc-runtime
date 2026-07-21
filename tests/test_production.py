import json
from types import SimpleNamespace

import pytest

from agentic_sdlc_runtime.production import (
    BudgetExceeded, BudgetLedger, ChangeSetCoordinator, DockerSandbox,
    OPAPolicyDecisionPoint, S3EvidenceStore, SLORecoveryPolicy,
    SQLiteWorkQueue, SupplyChainAttestor,
)


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        return json.dumps(self.data).encode()


def test_opa_allows_and_denies(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response({"result": {"allow": True}}))
    assert OPAPolicyDecisionPoint("http://opa/v1/data/allow").authorize({"action": "read"})["allow"]
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response({"result": {"allow": False}}))
    with pytest.raises(PermissionError):
        OPAPolicyDecisionPoint("http://opa/v1/data/allow").authorize({"action": "deploy"})


class S3:
    def __init__(self):
        self.object = None

    def put_object(self, **kwargs):
        self.object = kwargs


def test_s3_evidence_is_content_addressed():
    client = S3()
    uri = S3EvidenceStore("audit", client=client).put("CHG-1", "run-1", "output", {"ok": True})
    assert uri.startswith("s3://audit/evidence/CHG-1/run-1/output-")
    assert client.object["Metadata"]["change-id"] == "CHG-1"


def test_budget_fails_before_persisting_excess(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.db")
    assert ledger.consume("C", tokens=10, cost=.1, token_limit=20, cost_limit=1)["tokens"] == 10
    with pytest.raises(BudgetExceeded):
        ledger.consume("C", tokens=11, cost=.1, token_limit=20, cost_limit=1)
    assert ledger.consume("C", tokens=1, cost=.1, token_limit=20, cost_limit=1)["tokens"] == 11


def test_queue_claim_ack_and_retry(tmp_path):
    queue = SQLiteWorkQueue(tmp_path / "queue.db")
    job_id = queue.publish({"change_id": "C"})
    job = queue.claim()
    assert job["id"] == job_id and job["attempts"] == 1
    queue.retry(job_id, 0)
    assert queue.claim()["attempts"] == 2
    queue.ack(job_id)
    assert queue.claim() is None


def test_multirepo_order_and_cycle():
    coordinator = ChangeSetCoordinator([
        {"repository": "api", "depends_on": ["contract"]},
        {"repository": "contract"}, {"repository": "ui", "depends_on": ["api"]},
    ])
    assert coordinator.promotion_order() == ["contract", "api", "ui"]
    with pytest.raises(ValueError):
        ChangeSetCoordinator([
            {"repository": "a", "depends_on": ["b"]},
            {"repository": "b", "depends_on": ["a"]},
        ]).promotion_order()


def test_slo_policy_requests_rollback():
    policy = SLORecoveryPolicy(error_rate=.01, latency_ms=500)
    assert policy.evaluate({"error_rate": .02})["action"] == "rollback"
    assert policy.evaluate({"error_rate": 0, "p95_latency_ms": 100})["action"] == "continue"


class Runner:
    def __init__(self):
        self.calls = []

    def run(self, argv):
        self.calls.append(argv)
        return SimpleNamespace(stdout='{"bom":true}', returncode=0)


def test_supply_chain_and_sandbox_commands_are_hardened():
    runner = Runner()
    assert SupplyChainAttestor(runner).attest("registry/app@sha256:1")["signature"]
    DockerSandbox(runner).execute("image@sha256:1", ["pytest"])
    docker = runner.calls[-1]
    assert "--network=none" in docker
    assert "--read-only" in docker
    assert "--cap-drop=ALL" in docker
