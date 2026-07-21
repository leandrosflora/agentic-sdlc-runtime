import pytest

from agentic_sdlc_runtime.demo_environment import DemoEnvironment
from agentic_sdlc_runtime.workflow import ApprovalError, EndToEndWorkflow, HumanApproval, STAGES


def workflow(tmp_path):
    environment = DemoEnvironment(tmp_path / "demo-environment.json")
    service = EndToEndWorkflow(
        definitions_dir="agents", state_dir=tmp_path / "runtime",
        environment=environment,
    )
    return service, environment


def start(service, change_id="CHG-2001"):
    return service.start(
        project_id="payments", change_id=change_id,
        objective="Deliver idempotent payment endpoint",
        acceptance_criteria=["retries do not duplicate payment"],
        author_id="developer-01",
    )


def test_runs_all_agents_and_pauses_for_human_approval(tmp_path):
    service, _ = workflow(tmp_path)
    state = start(service)
    assert state["status"] == "awaiting_human_approval"
    assert tuple(state["agent_results"]) == STAGES
    assert state["artifact_digest"].startswith("sha256:")
    assert all(result["evidence_refs"] for result in state["agent_results"].values())


def test_valid_human_approval_releases_and_observes_healthy(tmp_path):
    service, environment = workflow(tmp_path)
    state = start(service)
    completed = service.approve_and_release(
        state["change_id"],
        HumanApproval("release-manager", state["artifact_digest"]),
        healthy=True,
    )
    assert completed["status"] == "completed"
    assert completed["observation"]["healthy"] is True
    assert completed["agent_results"]["release"]["status"] == "completed"
    assert environment.state()["current_digest"] == state["artifact_digest"]


def test_unhealthy_observation_rolls_back_to_previous_digest(tmp_path):
    service, environment = workflow(tmp_path)
    environment.deploy("sha256:stable")
    state = start(service)
    rolled_back = service.approve_and_release(
        state["change_id"],
        HumanApproval("release-manager", state["artifact_digest"]),
        healthy=False,
    )
    assert rolled_back["status"] == "rolled_back"
    assert environment.state()["current_digest"] == "sha256:stable"
    assert environment.state()["history"][-1]["action"] == "rollback"


def test_author_cannot_approve_own_change(tmp_path):
    service, _ = workflow(tmp_path)
    state = start(service)
    with pytest.raises(ApprovalError):
        service.approve_and_release(
            state["change_id"], HumanApproval("developer-01", state["artifact_digest"])
        )


def test_approval_is_bound_to_exact_digest(tmp_path):
    service, _ = workflow(tmp_path)
    state = start(service)
    with pytest.raises(ApprovalError):
        service.approve_and_release(
            state["change_id"], HumanApproval("release-manager", "sha256:other")
        )
