from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentic_sdlc_runtime.cross_repo import CrossRepositoryRelease
from agentic_sdlc_runtime.external_environment import ExternalDemoEnvironment, HttpHealthObserver
from agentic_sdlc_runtime.github import GitHubClient
from agentic_sdlc_runtime.quality import GovernedCommandRunner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--previous-sha", required=True)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--state-dir", default=".agentic-release")
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/health")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    runner = GovernedCommandRunner(workspace, allowed={"python", "python3"})
    environment = ExternalDemoEnvironment(
        workspace / args.state_dir / "environment.json",
        runner=runner,
        deploy_command=["python", "ops/deploy.py", "deploy"],
        rollback_command=["python", "ops/deploy.py", "rollback"],
        observer=HttpHealthObserver(args.health_url, attempts=5, interval=.5),
    )
    release = CrossRepositoryRelease(
        github=GitHubClient(args.repository), environment=environment,
        state_dir=workspace / args.state_dir,
    )
    result = release.run(
        issue_number=args.issue, head_sha=args.head_sha,
        previous_sha=args.previous_sha, approver=args.approver,
    )
    print(json.dumps(result, indent=2))
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
