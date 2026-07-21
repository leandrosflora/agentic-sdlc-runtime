import json

import pytest

from agentic_sdlc_runtime.developer import ChangeRejected, DeveloperAgentService, FileChange
from agentic_sdlc_runtime.github import GitHubClient
from agentic_sdlc_runtime.model_gateway import FakeModelGateway
from agentic_sdlc_runtime.models import ModelResponse


def client(calls):
    def transport(method, path, payload):
        calls.append((method, path, payload))
        if path.endswith("/issues/7"):
            return {
                "number": 7, "title": "Expose environment", "body": "Add environment to /version",
                "user": {"login": "author"}, "html_url": "https://example/issues/7",
            }
        if "/git/ref/heads/master" in path:
            return {"object": {"sha": "base-sha"}}
        if "/contents/" in path and method == "GET":
            return {"sha": "blob-sha"}
        if path.endswith("/pulls"):
            return {"html_url": "https://example/pull/8"}
        if path.endswith("/comments"):
            return {"html_url": "https://example/comment"}
        return {}
    return GitHubClient("leandrosflora/agentic-sdlc-demo-app", transport=transport)


def test_developer_creates_guarded_branch_change_and_draft_pr():
    calls = []
    response = ModelResponse(
        content=json.dumps({
            "summary": "expose environment",
            "files": [{"path": "src/demo_app/app.py", "content": "ENVIRONMENT = 'demo'\n"}],
        }),
        model="fake", input_tokens=10, output_tokens=10,
    )
    service = DeveloperAgentService(client(calls), FakeModelGateway([response]))
    result = service.implement(7)
    assert result["merged"] is False
    assert result["pull_request"].endswith("/8")
    assert any(path.endswith("/git/refs") for _, path, _ in calls)
    pull = next(payload for method, path, payload in calls if method == "POST" and path.endswith("/pulls"))
    assert pull["draft"] is True


def test_developer_rejects_workflows_and_traversal():
    service = DeveloperAgentService(client([]), FakeModelGateway())
    with pytest.raises(ChangeRejected):
        service._validate([FileChange(".github/workflows/pwn.yml", "x")])
    with pytest.raises(ChangeRejected):
        service._validate([FileChange("../secret", "x")])
