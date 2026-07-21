from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .checkpoint import CheckpointStore
from .demo_environment import DemoEnvironment
from .mcp import FakeMCPGateway
from .model_gateway import FakeModelGateway, ModelGateway
from .models import ContextSource, ModelResponse, RunRequest
from .runtime import AgentRuntime


STAGES = ("product", "architecture", "developer", "test", "security", "reviewer")


@dataclass(frozen=True)
class HumanApproval:
    actor_id: str
    artifact_digest: str
    valid: bool = True
    human: bool = True


class ApprovalError(PermissionError):
    pass


class EndToEndWorkflow:
    def __init__(self, *, definitions_dir: str | Path, state_dir: str | Path,
                 environment: DemoEnvironment,
                 model_factory: Callable[[str, dict], ModelGateway] | None = None):
        self.definitions_dir = Path(definitions_dir)
        self.state_dir = Path(state_dir)
        self.environment = environment
        self.checkpoints = CheckpointStore(self.state_dir / "workflow-checkpoints")
        self.model_factory = model_factory or self._fake_model

    @staticmethod
    def _fake_model(role: str, state: dict) -> ModelGateway:
        payload = {
            "role": role,
            "status": "passed" if role in {"test", "security", "reviewer"} else "proposed",
            "change_id": state["change_id"],
            "evidence": f"{role} evidence",
        }
        content = json.dumps(payload)
        return FakeModelGateway([ModelResponse(
            content=content, model=f"fake-{role}-v1",
            input_tokens=100, output_tokens=len(content) // 4,
        )])

    def _save(self, state: dict) -> None:
        self.checkpoints.save(state["change_id"], "end-to-end", state)

    def _run_agent(self, role: str, state: dict) -> dict:
        runtime = AgentRuntime(
            definitions_dir=self.definitions_dir,
            state_dir=self.state_dir,
            model_gateway=self.model_factory(role, state),
            mcp_gateway=FakeMCPGateway(),
        )
        result = runtime.run(RunRequest(
            agent_role=role, project_id=state["project_id"], change_id=state["change_id"],
            objective=f"{role} stage for {state['objective']}",
            acceptance_criteria=state["acceptance_criteria"],
            sources=[ContextSource(
                uri=f"workflow://{state['change_id']}/{role}",
                content=json.dumps({"prior_results": state["agent_results"]}),
                classification="internal",
            )],
            input_data={"task": role, "workflow_state": state["status"]},
        ))
        return {
            "run_id": result.run_id, "status": result.status,
            "output": result.output, "evidence_refs": result.evidence_refs,
            "event_refs": result.event_refs,
        }

    def start(self, *, project_id: str, change_id: str, objective: str,
              acceptance_criteria: list[str], author_id: str) -> dict:
        existing = self.checkpoints.load(change_id, "end-to-end")
        if existing:
            return existing
        state = {
            "workflow": "end-to-end-v1", "project_id": project_id,
            "change_id": change_id, "objective": objective,
            "acceptance_criteria": acceptance_criteria, "author_id": author_id,
            "status": "running", "next_stage": 0, "agent_results": {},
            "artifact_digest": None, "approval": None, "deployment": None,
            "observation": None,
        }
        self._save(state)
        for index, role in enumerate(STAGES):
            state["agent_results"][role] = self._run_agent(role, state)
            state["next_stage"] = index + 1
            self._save(state)

        digest_input = json.dumps(state["agent_results"], sort_keys=True).encode()
        state["artifact_digest"] = "sha256:" + hashlib.sha256(digest_input).hexdigest()
        state["status"] = "awaiting_human_approval"
        self._save(state)
        return state

    def approve_and_release(self, change_id: str, approval: HumanApproval,
                            *, healthy: bool | None = True) -> dict:
        state = self.checkpoints.load(change_id, "end-to-end")
        if not state:
            raise ValueError("workflow not found")
        if state["status"] != "awaiting_human_approval":
            return state
        if not approval.valid or not approval.human:
            raise ApprovalError("valid human approval required")
        if approval.actor_id == state["author_id"]:
            raise ApprovalError("author cannot approve own change")
        if approval.artifact_digest != state["artifact_digest"]:
            raise ApprovalError("approval digest does not match artifact")

        state["approval"] = {
            "actor_id": approval.actor_id, "artifact_digest": approval.artifact_digest,
            "valid": approval.valid, "human": approval.human,
        }
        state["status"] = "releasing"
        self._save(state)

        state["agent_results"]["release"] = self._run_agent("release", state)
        state["deployment"] = self.environment.deploy(state["artifact_digest"])
        state["status"] = "observing"
        self._save(state)

        state["observation"] = self.environment.observe(healthy)
        observed_healthy = bool(state["observation"]["healthy"])
        if observed_healthy:
            state["status"] = "completed"
        else:
            state["deployment"] = self.environment.rollback()
            state["status"] = "rolled_back"
        self._save(state)
        return state

    def get(self, change_id: str) -> dict | None:
        return self.checkpoints.load(change_id, "end-to-end")
