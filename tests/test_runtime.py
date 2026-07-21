import json

import pytest

from agentic_sdlc_runtime.mcp import FakeMCPGateway
from agentic_sdlc_runtime.model_gateway import FakeModelGateway
from agentic_sdlc_runtime.models import ContextSource, ModelResponse, RunRequest
from agentic_sdlc_runtime.runtime import AgentRuntime


def request(resume=False):
    return RunRequest(
        agent_role="product", project_id="payments", change_id="CHG-1001",
        objective="Refine requirement", acceptance_criteria=["testable"],
        sources=[ContextSource("repo://requirement", "Keep compatibility")],
        input_data={"task": "refine"}, resume=resume,
    )


def model():
    return FakeModelGateway([ModelResponse(
        content=json.dumps({"status": "proposed"}),
        tool_calls=[{"name": "requirements.write", "arguments": {"criteria": ["compatible"]}}],
        input_tokens=100, output_tokens=20, model="fake-v1",
    )])


def runtime(tmp_path, gateway, model_gateway):
    return AgentRuntime(
        definitions_dir="agents", state_dir=tmp_path,
        model_gateway=model_gateway, mcp_gateway=gateway,
    )


def test_runtime_persists_evidence_checkpoint_and_compatible_event(tmp_path):
    gateway = FakeMCPGateway()
    gateway.register("requirements.write", lambda args: {"updated": True})
    result = runtime(tmp_path, gateway, model()).run(request())

    assert result.status == "completed"
    assert len(result.evidence_refs) == 2
    assert len(result.event_refs) == 1
    event = json.loads((tmp_path / "events" / "CHG-1001" / result.event_refs[0].split("/")[-1]).read_text())
    required = {"schema_version", "event_id", "timestamp", "trace_id", "change_id",
                "project_id", "workflow", "actor", "action", "policy", "usage", "evidence_refs"}
    assert required <= set(event)
    assert event["change_id"] == "CHG-1001"
    checkpoint = json.loads((tmp_path / "checkpoints" / "CHG-1001" / "product.json").read_text())
    assert checkpoint["stage"] == "completed"


def test_resume_does_not_call_model_twice(tmp_path):
    gateway = FakeMCPGateway()

    def fail(_):
        raise RuntimeError("temporary tool failure")

    gateway.register("requirements.write", fail)
    fake_model = model()
    service = runtime(tmp_path, gateway, fake_model)
    with pytest.raises(RuntimeError):
        service.run(request())

    gateway.register("requirements.write", lambda args: {"updated": True})
    result = service.run(request(resume=True))
    assert result.status == "completed"
    assert result.resumed_from is not None
    assert len(fake_model.calls) == 1
