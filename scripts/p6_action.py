from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from agentic_sdlc_runtime.demo_environment import DemoEnvironment
from agentic_sdlc_runtime.external_environment import ExternalDemoEnvironment, HttpHealthObserver
from agentic_sdlc_runtime.github import GitHubClient
from agentic_sdlc_runtime.model_gateway import OpenAICompatibleGateway
from agentic_sdlc_runtime.p6 import P6Integration
from agentic_sdlc_runtime.quality import GovernedCommandRunner, QualityGates
from agentic_sdlc_runtime.workflow import EndToEndWorkflow


ALLOWED_EXECUTABLES = {"python", "python3", "pytest", "ruff", "docker", "kubectl"}


def command_from_env(name: str) -> list[str]:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    command = json.loads(value)
    if not isinstance(command, list) or not command or not all(isinstance(v, str) for v in command):
        raise ValueError(f"{name} must be a JSON string array")
    return command


def write_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"{name}={value}\n")
    print(f"{name}={value}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "release"))
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--head-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--project", default="demo")
    parser.add_argument("--state-dir", default=".runtime")
    parser.add_argument("--approver")
    parser.add_argument("--digest")
    args = parser.parse_args()

    workspace = Path.cwd()
    runner = GovernedCommandRunner(workspace, allowed=ALLOWED_EXECUTABLES)
    github = GitHubClient(os.environ["GITHUB_REPOSITORY"])
    if args.phase == "prepare":
        environment = DemoEnvironment(Path(args.state_dir) / "demo-environment.json")
    else:
        environment = ExternalDemoEnvironment(
            Path(args.state_dir) / "demo-environment.json",
            runner=runner,
            deploy_command=command_from_env("P6_DEPLOY_COMMAND"),
            rollback_command=command_from_env("P6_ROLLBACK_COMMAND"),
            observer=HttpHealthObserver(os.environ["P6_HEALTH_URL"]),
        )

    model_factory = None
    if os.environ.get("MODEL_API_KEY") and os.environ.get("MODEL_NAME"):
        model_factory = lambda _role, _state: OpenAICompatibleGateway()
    workflow = EndToEndWorkflow(
        definitions_dir="agents", state_dir=args.state_dir, environment=environment,
        model_factory=model_factory,
    )
    integration = P6Integration(
        github=github, workflow=workflow, quality=QualityGates(runner),
        state_dir=args.state_dir,
    )
    if args.phase == "prepare":
        state = integration.prepare(
            issue_number=args.issue, head_sha=args.head_sha, project_id=args.project,
            quality_commands=[
                ["python", "-m", "pytest"],
                ["python", "scripts/security_scan.py"],
            ],
        )
        write_output("digest", state["artifact_digest"])
        write_output("change_id", state["change_id"])
    else:
        if not args.approver or not args.digest:
            parser.error("release requires --approver and --digest")
        state = integration.release(
            issue_number=args.issue, approver=args.approver,
            artifact_digest=args.digest,
        )
        write_output("status", state["status"])
        if state["status"] != "completed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
