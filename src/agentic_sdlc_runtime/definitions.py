from __future__ import annotations

import json
from pathlib import Path

from .models import AgentDefinition


class DefinitionError(ValueError):
    pass


class AgentRegistry:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def load(self, role: str) -> AgentDefinition:
        path = self.directory / f"{role}.json"
        if not path.is_file():
            raise DefinitionError(f"unknown agent role: {role}")
        data = json.loads(path.read_text(encoding="utf-8"))
        required = {"role", "version", "description", "system_prompt", "allowed_tools"}
        missing = required - set(data)
        if missing:
            raise DefinitionError(f"{path}: missing {sorted(missing)}")
        if data["role"] != role:
            raise DefinitionError(f"{path}: role mismatch")
        return AgentDefinition(
            role=data["role"],
            version=data["version"],
            description=data["description"],
            system_prompt=data["system_prompt"],
            allowed_tools=tuple(data["allowed_tools"]),
            max_steps=int(data.get("limits", {}).get("max_steps", 8)),
            max_input_chars=int(data.get("limits", {}).get("max_input_chars", 32_000)),
            max_output_chars=int(data.get("limits", {}).get("max_output_chars", 8_000)),
        )

    def roles(self) -> list[str]:
        return sorted(path.stem for path in self.directory.glob("*.json"))
