import json
import sys
from pathlib import Path

import pytest

from agentic_sdlc_runtime.mcp import MCPProtocolError, StdioMCPGateway, ToolDeniedError

SERVER = [sys.executable, str(Path(__file__).with_name("echo_mcp_server.py"))]


@pytest.fixture
def gateway():
    with StdioMCPGateway(SERVER) as gateway:
        yield gateway


def test_initialize_handshake_and_tool_listing(gateway):
    tools = gateway.list_tools()
    assert [tool["name"] for tool in tools] == ["echo", "boom"]


def test_tool_call_round_trip(gateway):
    result = gateway.call("echo", {"payload": 42}, ("echo",), "payments", "CHG-3001")
    assert json.loads(result.output["content"][0]["text"]) == {"payload": 42}
    assert gateway.calls[0]["change_id"] == "CHG-3001"


def test_grant_is_enforced_before_reaching_the_server(gateway):
    with pytest.raises(ToolDeniedError):
        gateway.call("echo", {}, ("other.tool",), "payments", "CHG-3001")
    assert gateway.calls == []


def test_tool_error_is_surfaced(gateway):
    with pytest.raises(MCPProtocolError):
        gateway.call("boom", {}, ("boom",), "payments", "CHG-3001")


def test_closed_server_raises_protocol_error():
    gateway = StdioMCPGateway(SERVER)
    gateway.close()
    with pytest.raises(MCPProtocolError):
        gateway.call("echo", {}, ("echo",), "payments", "CHG-3001")
