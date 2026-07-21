from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from .authorization import OpaHttpAuthorizer, authorizer_from_environment
from .mcp import FakeMCPGateway
from .model_gateway import FakeModelGateway, OpenAICompatibleGateway
from .models import ContextSource, RunRequest
from .runtime import AgentRuntime


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a governed Agentic SDLC agent")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--definitions", default="agents")
    parser.add_argument("--state", default=".runtime")
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--opa-url", help="OPA server used as PDP for tool calls "
                        "(also SDLC_OPA_URL; SDLC_POLICY_PATH selects the opa CLI instead)")
    args = parser.parse_args()

    model = OpenAICompatibleGateway() if args.real_model else FakeModelGateway()
    mcp = FakeMCPGateway()
    mcp.register("project.read", lambda payload: {"status": "ok", "payload": payload})

    runtime = AgentRuntime(
        definitions_dir=Path(args.definitions), state_dir=Path(args.state),
        model_gateway=model, mcp_gateway=mcp,
        allowed_classification=os.environ.get("MAX_CONTEXT_CLASSIFICATION", "internal"),
        authorizer=OpaHttpAuthorizer(args.opa_url) if args.opa_url else authorizer_from_environment(),
    )
    request = RunRequest(
        agent_role=args.agent, project_id=args.project, change_id=args.change,
        objective=args.objective, acceptance_criteria=["output is structured and evidenced"],
        sources=[ContextSource(uri="cli://objective", content=args.objective, classification="internal")],
        input_data={"task": args.objective}, resume=args.resume,
    )
    print(json.dumps(asdict(runtime.run(request)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
