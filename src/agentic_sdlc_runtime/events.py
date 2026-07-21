from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EventStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def emit(self, *, trace_id: str, change_id: str, project_id: str,
             workflow_id: str, workflow_version: str, actor_id: str,
             actor_version: str, action: str, model: str, input_tokens: int,
             output_tokens: int, evidence_refs: list[str],
             policy_decision: str = "allow", bundle_version: str = "runtime-v1") -> str:
        event = {
            "schema_version": "1.0",
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": trace_id,
            "change_id": change_id,
            "project_id": project_id,
            "workflow": {"id": workflow_id, "version": workflow_version},
            "actor": {"type": "agent", "id": actor_id, "version": actor_version},
            "action": action,
            "policy": {"decision": policy_decision, "bundle_version": bundle_version},
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": 0},
            "evidence_refs": evidence_refs,
        }
        directory = self.root / change_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{event['event_id']}.json"
        path.write_text(json.dumps(event, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        return path.as_uri()
