import pytest

from agentic_sdlc_runtime.mcp import FakeMCPGateway, ToolDeniedError


def test_fake_mcp_enforces_tool_grants():
    gateway = FakeMCPGateway()
    gateway.register("repository.write", lambda args: {"ok": True})
    with pytest.raises(ToolDeniedError):
        gateway.call("repository.write", {}, ("project.read",), "p1", "CHG-1001")
