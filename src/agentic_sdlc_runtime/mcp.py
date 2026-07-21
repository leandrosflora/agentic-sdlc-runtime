from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable


class ToolDeniedError(PermissionError):
    pass


class MCPProtocolError(RuntimeError):
    pass


@dataclass
class ToolResult:
    name: str
    output: dict[str, Any]


class FakeMCPGateway:
    """In-memory MCP-like gateway for deterministic tests."""

    def __init__(self):
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.calls: list[dict[str, Any]] = []

    def register(self, name: str, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.handlers[name] = handler

    def call(self, name: str, arguments: dict[str, Any], allowed_tools: tuple[str, ...],
             project_id: str, change_id: str) -> ToolResult:
        if name not in allowed_tools:
            raise ToolDeniedError(f"tool not granted to agent: {name}")
        if name not in self.handlers:
            raise KeyError(f"tool not registered: {name}")
        record = {"name": name, "arguments": arguments, "project_id": project_id, "change_id": change_id}
        self.calls.append(record)
        return ToolResult(name=name, output=self.handlers[name](arguments))


class StdioMCPGateway:
    """Real MCP client over the stdio transport (newline-delimited JSON-RPC 2.0).

    Spawns an MCP server as a subprocess, performs the initialize handshake and
    exposes the same call() contract as FakeMCPGateway, so the runtime accepts
    either. Tool grants keep being enforced locally before the server is asked
    to execute anything.
    """

    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, command: list[str], timeout: int = 60):
        self.timeout = timeout
        self.calls: list[dict[str, Any]] = []
        self._next_id = 0
        self._process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8",
        )
        self._request("initialize", {
            "protocolVersion": self.PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "agentic-sdlc-runtime", "version": "0.1.0"},
        })
        self._notify("notifications/initialized", {})

    def list_tools(self) -> list[dict[str, Any]]:
        return self._request("tools/list", {}).get("tools", [])

    def call(self, name: str, arguments: dict[str, Any], allowed_tools: tuple[str, ...],
             project_id: str, change_id: str) -> ToolResult:
        if name not in allowed_tools:
            raise ToolDeniedError(f"tool not granted to agent: {name}")
        record = {"name": name, "arguments": arguments, "project_id": project_id, "change_id": change_id}
        self.calls.append(record)
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise MCPProtocolError(f"tool {name} failed: {result.get('content')}")
        return ToolResult(name=name, output=result)

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.stdin.close()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

    def __enter__(self) -> StdioMCPGateway:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _send(self, message: dict[str, Any]) -> None:
        if self._process.poll() is not None:
            raise MCPProtocolError("MCP server process has exited")
        self._process.stdin.write(json.dumps(message) + "\n")
        self._process.stdin.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            line = self._process.stdout.readline()
            if not line:
                raise MCPProtocolError(f"MCP server closed the stream during {method}")
            message = json.loads(line)
            if message.get("id") != request_id:
                continue  # server-initiated notifications and requests are ignored
            if "error" in message:
                raise MCPProtocolError(f"{method} failed: {message['error']}")
            return message.get("result", {})
