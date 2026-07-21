from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentDefinition:
    role: str
    version: str
    description: str
    system_prompt: str
    allowed_tools: tuple[str, ...]
    max_steps: int = 8
    max_input_chars: int = 32_000
    max_output_chars: int = 8_000


@dataclass(frozen=True)
class ContextSource:
    uri: str
    content: str
    classification: str = "internal"
    trusted: bool = True
    version: str = "1"


@dataclass
class ContextEnvelope:
    project_id: str
    change_id: str
    objective: str
    acceptance_criteria: list[str]
    sources: list[dict[str, Any]]
    rendered: str
    digest: str


@dataclass
class ModelResponse:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = "unknown"


@dataclass
class RunRequest:
    agent_role: str
    project_id: str
    change_id: str
    objective: str
    acceptance_criteria: list[str]
    sources: list[ContextSource] = field(default_factory=list)
    input_data: dict[str, Any] = field(default_factory=dict)
    resume: bool = False


@dataclass
class RunResult:
    run_id: str
    status: str
    output: dict[str, Any]
    evidence_refs: list[str]
    event_refs: list[str]
    resumed_from: str | None = None
