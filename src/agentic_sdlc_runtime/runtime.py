from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .checkpoint import CheckpointStore
from .context import ContextBuilder
from .definitions import AgentRegistry
from .events import EventStore
from .evidence import EvidenceStore
from .mcp import FakeMCPGateway
from .model_gateway import ModelGateway
from .models import ModelResponse, RunRequest, RunResult


class AgentRuntime:
    def __init__(self, *, definitions_dir: str | Path, state_dir: str | Path,
                 model_gateway: ModelGateway, mcp_gateway: FakeMCPGateway,
                 allowed_classification: str = "internal"):
        state_dir = Path(state_dir)
        self.registry = AgentRegistry(definitions_dir)
        self.context_builder = ContextBuilder(allowed_classification)
        self.model_gateway = model_gateway
        self.mcp_gateway = mcp_gateway
        self.evidence = EvidenceStore(state_dir / "evidence")
        self.checkpoints = CheckpointStore(state_dir / "checkpoints")
        self.events = EventStore(state_dir / "events")

    def run(self, request: RunRequest) -> RunResult:
        definition = self.registry.load(request.agent_role)
        previous = self.checkpoints.load(request.change_id, request.agent_role) if request.resume else None
        run_id = str(uuid.uuid4())
        trace_id = (previous or {}).get("trace_id", uuid.uuid4().hex)
        resumed_from = (previous or {}).get("run_id")
        state: dict[str, Any] = {
            "run_id": run_id, "trace_id": trace_id, "stage": "started",
            "request": asdict(request), "resumed_from": resumed_from,
        }

        try:
            if previous and previous.get("stage") in {"model_completed", "tools_completed"}:
                context_data = previous["context"]
                model_data = previous["model_response"]
                response = ModelResponse(**model_data)
                state["context"] = context_data
                state["model_response"] = model_data
            else:
                context = self.context_builder.build(
                    request.project_id, request.change_id, request.objective,
                    request.acceptance_criteria, request.sources, definition.max_input_chars,
                )
                state["context"] = asdict(context)
                state["stage"] = "context_built"
                self.checkpoints.save(request.change_id, request.agent_role, state)
                response = self.model_gateway.complete(
                    definition.system_prompt, context.rendered, request.input_data,
                )
                if len(response.content) > definition.max_output_chars:
                    raise ValueError("model output exceeds agent limit")
                state["model_response"] = asdict(response)
                state["stage"] = "model_completed"
                self.checkpoints.save(request.change_id, request.agent_role, state)

            tool_outputs = list((previous or {}).get("tool_outputs", [])) if previous else []
            if state["stage"] != "tools_completed":
                for tool_call in response.tool_calls[:definition.max_steps]:
                    name = tool_call["name"]
                    arguments = tool_call.get("arguments", {})
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    result = self.mcp_gateway.call(
                        name, arguments, definition.allowed_tools,
                        request.project_id, request.change_id,
                    )
                    tool_outputs.append({"name": result.name, "output": result.output})
                state["tool_outputs"] = tool_outputs
                state["stage"] = "tools_completed"
                self.checkpoints.save(request.change_id, request.agent_role, state)

            try:
                parsed_output = json.loads(response.content)
            except json.JSONDecodeError:
                parsed_output = {"content": response.content}
            output = {"agent": definition.role, "result": parsed_output, "tools": tool_outputs}

            context_ref = self.evidence.put(request.change_id, run_id, "context", state["context"])
            output_ref = self.evidence.put(request.change_id, run_id, "output", output)
            evidence_refs = [context_ref, output_ref]
            event_ref = self.events.emit(
                trace_id=trace_id, change_id=request.change_id, project_id=request.project_id,
                workflow_id="agent-run", workflow_version="1.0",
                actor_id=definition.role, actor_version=definition.version,
                action=f"{definition.role}.execute", model=response.model,
                input_tokens=response.input_tokens, output_tokens=response.output_tokens,
                evidence_refs=evidence_refs,
            )
            state.update({"stage": "completed", "output": output,
                          "evidence_refs": evidence_refs, "event_refs": [event_ref]})
            self.checkpoints.save(request.change_id, request.agent_role, state)
            return RunResult(run_id=run_id, status="completed", output=output,
                             evidence_refs=evidence_refs, event_refs=[event_ref],
                             resumed_from=resumed_from)
        except Exception as error:
            state.update({"stage": "failed", "error": type(error).__name__, "message": str(error)})
            self.checkpoints.save(request.change_id, request.agent_role, state)
            raise
