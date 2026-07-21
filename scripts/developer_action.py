from __future__ import annotations

import argparse
import json
import os

from agentic_sdlc_runtime.developer import DeveloperAgentService
from agentic_sdlc_runtime.github import GitHubClient
from agentic_sdlc_runtime.model_gateway import FakeModelGateway, OpenAICompatibleGateway
from agentic_sdlc_runtime.models import ModelResponse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base", default="master")
    args = parser.parse_args()

    deterministic = os.environ.get("DEVELOPER_CHANGE_JSON")
    if deterministic:
        model = FakeModelGateway([ModelResponse(
            content=deterministic, model="declared-change",
            input_tokens=0, output_tokens=len(deterministic) // 4,
        )])
    else:
        model = OpenAICompatibleGateway()
    service = DeveloperAgentService(
        GitHubClient(args.repository), model,
        allowed_prefixes=("src/", "tests/", "docs/"),
    )
    print(json.dumps(service.implement(args.issue, base_branch=args.base), indent=2))


if __name__ == "__main__":
    main()
