from agentic_sdlc_runtime.cross_repo import CrossRepositoryRelease
from agentic_sdlc_runtime.demo_environment import DemoEnvironment
from agentic_sdlc_runtime.github import GitHubClient


class ObservedEnvironment(DemoEnvironment):
    def __init__(self, path, healthy):
        super().__init__(path)
        self.healthy = healthy

    def observe(self, _value):
        return super().observe(self.healthy)


def github(calls, author="author"):
    def transport(method, path, payload):
        calls.append((method, path, payload))
        if method == "GET":
            return {
                "number": 9, "title": "Change", "body": "criteria",
                "user": {"login": author}, "html_url": "https://example/issues/9",
            }
        if path.endswith("/comments"):
            return {"html_url": "https://example/comment"}
        return {"id": len(calls)}
    return GitHubClient("owner/demo", transport=transport)


def test_cross_repo_release_completes_and_persists_evidence(tmp_path):
    calls = []
    service = CrossRepositoryRelease(
        github=github(calls), environment=ObservedEnvironment(tmp_path / "env.json", True),
        state_dir=tmp_path,
    )
    result = service.run(
        issue_number=9, head_sha="candidate", previous_sha="stable", approver="reviewer",
    )
    assert result["status"] == "completed"
    assert result["artifact_digest"] == "sha256:candidate"
    assert result["evidence"].startswith("file://")


def test_cross_repo_release_rolls_back(tmp_path):
    service = CrossRepositoryRelease(
        github=github([]), environment=ObservedEnvironment(tmp_path / "env.json", False),
        state_dir=tmp_path,
    )
    result = service.run(
        issue_number=9, head_sha="candidate", previous_sha="stable", approver="reviewer",
    )
    assert result["status"] == "rolled_back"
    assert result["environment"]["current_digest"] == "sha256:stable"


def test_issue_author_cannot_approve(tmp_path):
    service = CrossRepositoryRelease(
        github=github([], author="same"), environment=ObservedEnvironment(tmp_path / "env.json", True),
        state_dir=tmp_path,
    )
    try:
        service.run(issue_number=9, head_sha="candidate", previous_sha="stable", approver="same")
        assert False
    except PermissionError:
        pass
