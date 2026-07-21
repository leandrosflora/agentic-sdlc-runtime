from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class ToolDeniedError(PermissionError):
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
