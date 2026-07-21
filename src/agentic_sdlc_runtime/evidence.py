from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class EvidenceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def put(self, change_id: str, run_id: str, kind: str, payload: dict[str, Any]) -> str:
        directory = self.root / change_id / run_id
        directory.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        path = directory / f"{kind}-{digest[:12]}.json"
        path.write_bytes(encoded)
        return path.as_uri()

    def read(self, uri: str) -> dict[str, Any]:
        return json.loads(Path(uri.removeprefix("file://")).read_text(encoding="utf-8"))
