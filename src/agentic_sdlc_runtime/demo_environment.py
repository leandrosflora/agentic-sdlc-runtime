from __future__ import annotations

import json
from pathlib import Path


class DemoEnvironment:
    """Durable local deployment target with observable health and rollback."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> dict:
        if not self.path.is_file():
            return {"current_digest": None, "previous_digest": None, "history": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)

    def deploy(self, digest: str) -> dict:
        state = self._read()
        if state["current_digest"] == digest:
            return state
        state["previous_digest"] = state["current_digest"]
        state["current_digest"] = digest
        state["history"].append({"action": "deploy", "digest": digest})
        self._write(state)
        return state

    def observe(self, healthy: bool) -> dict:
        state = self._read()
        state["history"].append({"action": "observe", "digest": state["current_digest"], "healthy": healthy})
        self._write(state)
        return {"healthy": healthy, "digest": state["current_digest"]}

    def rollback(self) -> dict:
        state = self._read()
        failed = state["current_digest"]
        target = state["previous_digest"]
        state["current_digest"] = target
        state["history"].append({"action": "rollback", "from": failed, "to": target})
        self._write(state)
        return state

    def state(self) -> dict:
        return self._read()
