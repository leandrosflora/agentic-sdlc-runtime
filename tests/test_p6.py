import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agentic_sdlc_runtime.demo_environment import DemoEnvironment
from agentic_sdlc_runtime.evidence import path_from_uri
from agentic_sdlc_runtime.external_environment import HttpHealthObserver
from agentic_sdlc_runtime.github import GitHubClient
from agentic_sdlc_runtime.p6 import P6Integration
from agentic_sdlc_runtime.quality import CommandRejected, GovernedCommandRunner, QualityGates
from agentic_sdlc_runtime.workflow import EndToEndWorkflow


class HealthyEnvironment(DemoEnvironment):
    def observe(self, healthy=None):
        return super().observe(True)


def fake_github(calls):
    def transport(method, path, payload):
        calls.append((method, path, payload))
        if method == "GET":
            return {
                "number": 42, "title": "Add health endpoint", "body": "Returns HTTP 200",
                "user": {"login": "issue-author"}, "html_url": "https://example/issues/42",
            }
        if path.endswith("/comments"):
            return {"html_url": "https://example/comment"}
        return {"id": len(calls)}
    return GitHubClient("owner/repo", transport=transport)


def test_github_adapter_maps_issue_comment_and_check():
    calls = []
    client = fake_github(calls)
    issue = client.get_issue(42)
    assert issue.author == "issue-author"
    assert client.comment(42, "done") == "https://example/comment"
    assert client.check("abc", name="gate", status="completed", conclusion="success") > 0
    assert calls[-1][2]["conclusion"] == "success"


def test_github_adapter_rejects_invalid_repository_and_pull_request():
    with pytest.raises(ValueError):
        GitHubClient("invalid", transport=lambda *_: {})
    client = GitHubClient("owner/repo", transport=lambda *_: {"pull_request": {}})
    with pytest.raises(ValueError):
        client.get_issue(1)


def test_governed_runner_executes_argv_without_shell(tmp_path):
    runner = GovernedCommandRunner(tmp_path, allowed={sys.executable})
    result = runner.run([sys.executable, "-c", "print('ok')"])
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"
    with pytest.raises(CommandRejected):
        runner.run(["sh", "-c", "echo unsafe"])


class Handler(BaseHTTPRequestHandler):
    status = 200

    def do_GET(self):
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *_):
        pass


def test_http_health_observer_uses_real_http_signal():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = HttpHealthObserver(
            f"http://127.0.0.1:{server.server_port}/health", attempts=1
        ).observe()
    finally:
        server.shutdown()
    assert result["healthy"] is True
    assert result["attempts"][0]["status"] == 200


def test_p6_issue_to_release_with_evidence_and_feedback(tmp_path):
    calls = []
    github = fake_github(calls)
    environment = HealthyEnvironment(tmp_path / "environment.json")
    workflow = EndToEndWorkflow(
        definitions_dir="agents", state_dir=tmp_path / "runtime", environment=environment,
    )
    runner = GovernedCommandRunner(tmp_path, allowed={sys.executable})
    integration = P6Integration(
        github=github, workflow=workflow, quality=QualityGates(runner),
        state_dir=tmp_path / "runtime",
    )
    prepared = integration.prepare(
        issue_number=42, head_sha="abc123", project_id="demo",
        quality_commands=[[sys.executable, "-c", "print('tests and security passed')"]],
    )
    assert prepared["status"] == "awaiting_human_approval"
    assert prepared["quality_evidence"]
    assert json.loads(
        path_from_uri(prepared["quality_evidence"][0]).read_text(encoding="utf-8")
    )["head_sha"] == "abc123"

    released = integration.release(
        issue_number=42, approver="release-manager",
        artifact_digest=prepared["artifact_digest"],
    )
    assert released["status"] == "completed"
    assert any("release" in (payload or {}).get("name", "") for _, path, payload in calls
               if path.endswith("/check-runs"))
