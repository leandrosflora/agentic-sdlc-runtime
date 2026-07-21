from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from .evidence import EvidenceStore
from .github import GitHubClient
from .quality import QualityGates
from .workflow import EndToEndWorkflow, HumanApproval


class P6Integration:
    """Issue-driven vertical joining agents, real gates, approval, release and feedback."""

    check_name = "Agentic SDLC / P6"

    def __init__(self, *, github: GitHubClient, workflow: EndToEndWorkflow,
                 quality: QualityGates, state_dir: str | Path):
        self.github = github
        self.workflow = workflow
        self.quality = quality
        self.evidence = EvidenceStore(Path(state_dir) / "evidence")

    def prepare(self, *, issue_number: int, head_sha: str,
                project_id: str, quality_commands: list[list[str]]) -> dict:
        issue = self.github.get_issue(issue_number)
        change_id = f"GH-{issue.number}"
        self.github.check(
            head_sha, name=self.check_name, status="in_progress",
            summary=f"Starting governed workflow for {change_id}",
        )
        try:
            state = self.workflow.start(
                project_id=project_id, change_id=change_id,
                objective=issue.title, acceptance_criteria=[issue.body or issue.title],
                author_id=issue.author,
            )
            gate_results = self.quality.run(quality_commands)
            gate_ref = self.evidence.put(
                change_id, f"quality-{uuid.uuid4().hex}", "quality-gates",
                {"commands": gate_results, "head_sha": head_sha},
            )
            state["quality_evidence"] = [gate_ref]
            digest_payload = {
                "agent_results": state["agent_results"],
                "quality_evidence": state["quality_evidence"],
                "head_sha": head_sha,
            }
            state["artifact_digest"] = "sha256:" + hashlib.sha256(
                json.dumps(digest_payload, sort_keys=True).encode()
            ).hexdigest()
            state["head_sha"] = head_sha
            self.workflow.checkpoints.save(change_id, "end-to-end", state)
            self.github.check(
                head_sha, name=self.check_name, status="completed", conclusion="success",
                summary=f"Agents and gates passed. Awaiting approval for {state['artifact_digest']}.",
            )
            self.github.comment(
                issue.number,
                f"### Agentic SDLC — aguardando aprovação\n\n"
                f"- Change: `{change_id}`\n"
                f"- Estado: `awaiting_human_approval`\n"
                f"- Digest: `{state['artifact_digest']}`\n"
                f"- Evidence bundles: {sum(len(v['evidence_refs']) for v in state['agent_results'].values()) + 1}\n\n"
                "A promoção ocorre somente pelo GitHub Environment `demo`.",
            )
            return state
        except Exception as error:
            self.github.check(
                head_sha, name=self.check_name, status="completed", conclusion="failure",
                summary=f"Workflow blocked: {type(error).__name__}",
            )
            raise

    def release(self, *, issue_number: int, approver: str,
                artifact_digest: str) -> dict:
        change_id = f"GH-{issue_number}"
        state = self.workflow.approve_and_release(
            change_id,
            HumanApproval(actor_id=approver, artifact_digest=artifact_digest),
            healthy=None,
        )
        conclusion = "success" if state["status"] == "completed" else "failure"
        self.github.check(
            state["head_sha"], name=f"{self.check_name} / release",
            status="completed", conclusion=conclusion,
            summary=f"Release finished with status {state['status']}. Digest: {artifact_digest}",
        )
        self.github.comment(
            issue_number,
            f"### Agentic SDLC — release\n\n"
            f"- Estado: `{state['status']}`\n"
            f"- Digest aprovado: `{artifact_digest}`\n"
            f"- Aprovador: `{approver}`\n"
            f"- Health check: `{state['observation']['healthy']}`",
        )
        return state
