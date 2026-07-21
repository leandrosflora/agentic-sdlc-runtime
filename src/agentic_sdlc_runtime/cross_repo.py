from __future__ import annotations

import uuid
from pathlib import Path

from .evidence import EvidenceStore
from .github import GitHubClient


class CrossRepositoryRelease:
    """Promotes one reviewed commit in a target repository and records the outcome."""

    def __init__(self, *, github: GitHubClient, environment, state_dir: str | Path):
        self.github = github
        self.environment = environment
        self.evidence = EvidenceStore(Path(state_dir) / "evidence")

    def run(self, *, issue_number: int, head_sha: str, previous_sha: str,
            approver: str) -> dict:
        issue = self.github.get_issue(issue_number)
        if approver == issue.author:
            raise PermissionError("issue author cannot approve own release")
        candidate = f"sha256:{head_sha}"
        previous = f"sha256:{previous_sha}"
        self.github.check(
            head_sha, name="Agentic SDLC / demo release", status="in_progress",
            summary=f"Promoting {candidate} after Environment approval",
        )
        self.environment.deploy(previous)
        self.environment.deploy(candidate)
        observation = self.environment.observe(None)
        status = "completed"
        if not observation["healthy"]:
            self.environment.rollback()
            status = "rolled_back"
        payload = {
            "issue": issue_number, "repository": self.github.repository,
            "head_sha": head_sha, "artifact_digest": candidate,
            "previous_digest": previous, "approver": approver,
            "observation": observation, "status": status,
            "environment": self.environment.state(),
        }
        evidence = self.evidence.put(
            f"GH-{issue_number}", f"release-{uuid.uuid4().hex}",
            "cross-repository-release", payload,
        )
        conclusion = "success" if status == "completed" else "failure"
        self.github.check(
            head_sha, name="Agentic SDLC / demo release", status="completed",
            conclusion=conclusion,
            summary=f"Demo release {status}; evidence: {evidence}",
        )
        self.github.comment(
            issue_number,
            f"### Release demo\n\n- Status: `{status}`\n"
            f"- Digest: `{candidate}`\n- Aprovador: `{approver}`\n"
            f"- Health: `{observation['healthy']}`\n- Evidência: `{evidence}`",
        )
        return {"status": status, "evidence": evidence, **payload}
