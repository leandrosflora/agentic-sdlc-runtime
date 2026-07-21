from __future__ import annotations

import hashlib
import json

from .models import ContextEnvelope, ContextSource


CLASSIFICATION_ORDER = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


class ContextBuilder:
    def __init__(self, allowed_classification: str = "internal"):
        if allowed_classification not in CLASSIFICATION_ORDER:
            raise ValueError("unknown classification")
        self.allowed_classification = allowed_classification

    def build(self, project_id: str, change_id: str, objective: str,
              acceptance_criteria: list[str], sources: list[ContextSource],
              max_chars: int) -> ContextEnvelope:
        selected = []
        consumed = 0
        ceiling = CLASSIFICATION_ORDER[self.allowed_classification]
        for source in sources:
            if CLASSIFICATION_ORDER.get(source.classification, 99) > ceiling:
                continue
            content = source.content.strip()
            if not content:
                continue
            remaining = max_chars - consumed
            if remaining <= 0:
                break
            content = content[:remaining]
            consumed += len(content)
            selected.append({
                "uri": source.uri,
                "version": source.version,
                "classification": source.classification,
                "trusted": source.trusted,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "content": content,
            })

        payload = {
            "project_id": project_id,
            "change_id": change_id,
            "objective": objective,
            "acceptance_criteria": acceptance_criteria,
            "sources": selected,
        }
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(rendered.encode()).hexdigest()
        return ContextEnvelope(
            project_id=project_id, change_id=change_id, objective=objective,
            acceptance_criteria=acceptance_criteria, sources=selected,
            rendered=rendered, digest=digest,
        )
