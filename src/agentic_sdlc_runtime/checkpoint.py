from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CheckpointStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def save(self, change_id: str, role: str, state: dict[str, Any]) -> str:
        directory = self.root / change_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{role}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        temporary.replace(path)
        return path.as_uri()

    def load(self, change_id: str, role: str) -> dict[str, Any] | None:
        path = self.root / change_id / f"{role}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def clear(self, change_id: str, role: str) -> None:
        path = self.root / change_id / f"{role}.json"
        if path.exists():
            path.unlink()
