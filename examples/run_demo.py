from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from agentic_sdlc_runtime.mcp import FakeMCPGateway
from agentic_sdlc_runtime.model_gateway import FakeModelGateway
from agentic_sdlc_runtime.models import ContextSource, ModelResponse, RunRequest
from agentic_sdlc_runtime.runtime import AgentRuntime


root = Path(__file__).resolve().parents[1]
mcp = FakeMCPGateway()
mcp.register("requirements.write", lambda args: {"issue": "PAY-142", "updated": True, **args})
model = FakeModelGateway([ModelResponse(
    content=json.dumps({"requirements": ["API remains compatible"], "status": "proposed"}),
    tool_calls=[{"name": "requirements.write", "arguments": {"criteria": ["API remains compatible"]}}],
    input_tokens=120, output_tokens=32, model="fake-v1",
)])

with tempfile.TemporaryDirectory() as state:
    runtime = AgentRuntime(
        definitions_dir=root / "agents", state_dir=state,
        model_gateway=model, mcp_gateway=mcp,
    )
    result = runtime.run(RunRequest(
        agent_role="product", project_id="payments", change_id="CHG-1001",
        objective="Refine the payment API requirement",
        acceptance_criteria=["criteria are testable"],
        sources=[ContextSource(uri="repo://requirements/PAY-142", content="Preserve API compatibility")],
        input_data={"task": "refine"},
    ))
    print(json.dumps(asdict(result), indent=2))
