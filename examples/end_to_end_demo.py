from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from agentic_sdlc_runtime.demo_environment import DemoEnvironment
from agentic_sdlc_runtime.workflow import EndToEndWorkflow, HumanApproval


parser = argparse.ArgumentParser()
parser.add_argument("--unhealthy", action="store_true", help="violate observation guardrail and demonstrate rollback")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory() as directory:
    state_dir = Path(directory)
    environment = DemoEnvironment(state_dir / "demo-environment.json")
    environment.deploy("sha256:stable")
    workflow = EndToEndWorkflow(
        definitions_dir=root / "agents",
        state_dir=state_dir / "runtime",
        environment=environment,
    )
    pending = workflow.start(
        project_id="payments", change_id="CHG-2001",
        objective="Deliver idempotent payment endpoint",
        acceptance_criteria=["retries do not duplicate payment"],
        author_id="developer-01",
    )
    print(json.dumps({"phase": "approval", "status": pending["status"],
                      "artifact_digest": pending["artifact_digest"]}, indent=2))
    final = workflow.approve_and_release(
        pending["change_id"],
        HumanApproval("release-manager", pending["artifact_digest"]),
        healthy=not args.unhealthy,
    )
    print(json.dumps({
        "phase": "final", "status": final["status"],
        "agents": list(final["agent_results"]),
        "observation": final["observation"],
        "environment": environment.state(),
    }, indent=2))
