"""Write-once evidence store with a tamper-evident manifest.

Every bundle is content-addressed, made read-only after the write, and
recorded in an append-only per-change manifest whose entries are hash-chained,
so any later mutation or deletion is detectable by verify(). A local
filesystem is tamper-evident, not tamper-proof: production deployments should
put this layout on WORM/object-lock storage.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

GENESIS = "genesis"
MANIFEST_NAME = "manifest.jsonl"


def path_from_uri(uri: str) -> Path:
    return Path(url2pathname(urlparse(uri).path))


class EvidenceTamperedError(RuntimeError):
    pass


@dataclass
class ManifestEntry:
    seq: int
    run_id: str
    kind: str
    file: str
    sha256: str
    prev: str


class EvidenceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def put(self, change_id: str, run_id: str, kind: str, payload: dict[str, Any]) -> str:
        directory = self.root / change_id / run_id
        directory.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        path = directory / f"{kind}-{digest[:12]}.json"
        if path.exists():
            if path.read_bytes() != encoded:
                raise EvidenceTamperedError(f"write-once violation: {path} already exists with different content")
            return path.as_uri()
        path.write_bytes(encoded)
        path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        self._append_manifest(change_id, run_id, kind, path, digest)
        return path.as_uri()

    def read(self, uri: str) -> dict[str, Any]:
        return json.loads(path_from_uri(uri).read_text(encoding="utf-8"))

    def verify(self, change_id: str) -> int:
        """Checks the hash chain and every referenced file; returns the entry count."""
        manifest = self.root / change_id / MANIFEST_NAME
        if not manifest.is_file():
            raise EvidenceTamperedError(f"manifest not found for change {change_id}")
        prev = GENESIS
        count = 0
        for index, line in enumerate(manifest.read_text(encoding="utf-8").splitlines()):
            entry = json.loads(line)
            if entry["seq"] != index:
                raise EvidenceTamperedError(f"{change_id}: manifest entry {index} has seq {entry['seq']}")
            if entry["prev"] != prev:
                raise EvidenceTamperedError(f"{change_id}: hash chain broken at entry {index}")
            path = self.root / change_id / entry["file"]
            if not path.is_file():
                raise EvidenceTamperedError(f"{change_id}: evidence file missing: {entry['file']}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != entry["sha256"]:
                raise EvidenceTamperedError(f"{change_id}: evidence file modified: {entry['file']}")
            prev = self._entry_hash(line)
            count += 1
        return count

    def _append_manifest(self, change_id: str, run_id: str, kind: str,
                         path: Path, digest: str) -> None:
        manifest = self.root / change_id / MANIFEST_NAME
        prev = GENESIS
        seq = 0
        if manifest.is_file():
            lines = manifest.read_text(encoding="utf-8").splitlines()
            if lines:
                prev = self._entry_hash(lines[-1])
                seq = len(lines)
        entry = ManifestEntry(
            seq=seq, run_id=run_id, kind=kind,
            file=path.relative_to(self.root / change_id).as_posix(),
            sha256=digest, prev=prev,
        )
        line = json.dumps(entry.__dict__, sort_keys=True)
        if manifest.is_file():
            os.chmod(manifest, stat.S_IREAD | stat.S_IWRITE)
        with manifest.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        os.chmod(manifest, stat.S_IREAD)

    @staticmethod
    def _entry_hash(line: str) -> str:
        return hashlib.sha256(line.encode()).hexdigest()
