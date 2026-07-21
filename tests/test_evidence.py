import json
import os
import stat

import pytest

from agentic_sdlc_runtime.evidence import EvidenceStore, EvidenceTamperedError, path_from_uri


@pytest.fixture
def store(tmp_path):
    return EvidenceStore(tmp_path / "evidence")


def make_writable(path):
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def test_put_read_round_trip_and_manifest(store):
    uri = store.put("CHG-1", "run-1", "context", {"a": 1})
    assert store.read(uri) == {"a": 1}
    store.put("CHG-1", "run-1", "output", {"b": 2})
    store.put("CHG-1", "run-2", "context", {"c": 3})
    assert store.verify("CHG-1") == 3


def test_evidence_files_are_read_only(store):
    uri = store.put("CHG-1", "run-1", "context", {"a": 1})
    with pytest.raises(PermissionError):
        path_from_uri(uri).write_text("overwritten")


def test_identical_put_is_idempotent(store):
    first = store.put("CHG-1", "run-1", "context", {"a": 1})
    second = store.put("CHG-1", "run-1", "context", {"a": 1})
    assert first == second
    assert store.verify("CHG-1") == 1


def test_replaced_file_blocks_rewrite_and_fails_verification(store):
    uri = store.put("CHG-1", "run-1", "context", {"a": 1})
    path = path_from_uri(uri)
    make_writable(path)
    path.write_text(json.dumps({"a": "tampered"}))
    with pytest.raises(EvidenceTamperedError):
        store.put("CHG-1", "run-1", "context", {"a": 1})
    with pytest.raises(EvidenceTamperedError):
        store.verify("CHG-1")


def test_deleted_file_fails_verification(store):
    uri = store.put("CHG-1", "run-1", "context", {"a": 1})
    path = path_from_uri(uri)
    make_writable(path)
    path.unlink()
    with pytest.raises(EvidenceTamperedError):
        store.verify("CHG-1")


def test_manifest_tampering_breaks_the_hash_chain(store, tmp_path):
    store.put("CHG-1", "run-1", "context", {"a": 1})
    store.put("CHG-1", "run-1", "output", {"b": 2})
    manifest = tmp_path / "evidence" / "CHG-1" / "manifest.jsonl"
    make_writable(manifest)
    lines = manifest.read_text().splitlines()
    first = json.loads(lines[0])
    first["kind"] = "forged"
    manifest.write_text("\n".join([json.dumps(first, sort_keys=True), lines[1]]) + "\n")
    with pytest.raises(EvidenceTamperedError):
        store.verify("CHG-1")
