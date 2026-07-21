import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agentic_sdlc_runtime.authorization import (
    AuthorizationResult,
    OpaCliAuthorizer,
    OpaHttpAuthorizer,
    PolicyUnavailableError,
    resolve_policy_path,
)
from agentic_sdlc_runtime.mcp import FakeMCPGateway, ToolDeniedError
from agentic_sdlc_runtime.model_gateway import FakeModelGateway
from agentic_sdlc_runtime.models import ContextSource, ModelResponse, RunRequest
from agentic_sdlc_runtime.runtime import AgentRuntime


@pytest.fixture
def opa_server():
    """Minimal OPA data-API stand-in that allows only project.read."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "input": body["input"]})
            allowed = body["input"]["action"] == "project.read"
            payload = json.dumps({"result": True} if allowed else {}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen
    finally:
        server.shutdown()


def run_request(tool):
    return RunRequest(
        agent_role="product", project_id="payments", change_id="CHG-2001",
        objective="Refine requirement", acceptance_criteria=["testable"],
        sources=[ContextSource("repo://requirement", "Keep compatibility")],
        input_data={"task": "refine"},
    ), FakeModelGateway([ModelResponse(
        content=json.dumps({"status": "proposed"}),
        tool_calls=[{"name": tool, "arguments": {}}],
        model="fake-v1",
    )])


def test_http_authorizer_queries_the_decision_path(opa_server):
    base_url, seen = opa_server
    result = OpaHttpAuthorizer(base_url).check({
        "action": "project.read",
        "identity": {"agent_role": "product", "project_id": "payments"},
        "resource": {"project_id": "payments"},
    })
    assert result == AuthorizationResult(allowed=True, action="project.read", raw={"result": True})
    assert seen[0]["path"] == "/v1/data/agentic_sdlc/authorization/allow"


def test_http_authorizer_treats_undefined_decision_as_deny(opa_server):
    base_url, _ = opa_server
    assert OpaHttpAuthorizer(base_url).check({"action": "requirements.write"}).allowed is False


def test_http_authorizer_raises_when_server_unreachable():
    with pytest.raises(PolicyUnavailableError):
        OpaHttpAuthorizer("http://127.0.0.1:1", timeout=1).check({"action": "project.read"})


def test_runtime_executes_tool_allowed_by_policy(tmp_path, opa_server):
    base_url, seen = opa_server
    gateway = FakeMCPGateway()
    gateway.register("project.read", lambda args: {"status": "ok"})
    request, model = run_request("project.read")
    result = AgentRuntime(
        definitions_dir="agents", state_dir=tmp_path,
        model_gateway=model, mcp_gateway=gateway,
        authorizer=OpaHttpAuthorizer(base_url),
    ).run(request)
    assert result.status == "completed"
    assert seen[-1]["input"]["identity"] == {"agent_role": "product", "project_id": "payments"}


def test_runtime_denies_tool_rejected_by_policy(tmp_path, opa_server):
    base_url, _ = opa_server
    gateway = FakeMCPGateway()
    gateway.register("requirements.write", lambda args: {"updated": True})
    request, model = run_request("requirements.write")
    with pytest.raises(ToolDeniedError):
        AgentRuntime(
            definitions_dir="agents", state_dir=tmp_path,
            model_gateway=model, mcp_gateway=gateway,
            authorizer=OpaHttpAuthorizer(base_url),
        ).run(request)
    assert gateway.calls == []


def _cli_integration_available():
    if shutil.which("opa") is None:
        return False
    try:
        resolve_policy_path()
    except PolicyUnavailableError:
        return False
    return True


@pytest.mark.skipif(not _cli_integration_available(),
                    reason="opa CLI or sibling reference-architecture checkout not available")
def test_cli_authorizer_against_canonical_policy():
    authorizer = OpaCliAuthorizer()
    own = {
        "action": "project.read",
        "identity": {"agent_role": "product", "project_id": "payments"},
        "resource": {"project_id": "payments"},
    }
    assert authorizer.check(own).allowed is True
    other = dict(own, resource={"project_id": "other"})
    assert authorizer.check(other).allowed is False
