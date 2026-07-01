from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from knowledge_engine.compiler import compile_release
from knowledge_engine.errors import IntegrityError
from knowledge_engine.publisher import publish_release
from knowledge_engine.storage import FileObjectStore

ROOT = Path(__file__).resolve().parents[1]


def test_compile_is_reproducible(tmp_path: Path) -> None:
    kwargs = {
        "bundle_root": ROOT / "examples/okf-bundle",
        "release_time": datetime(2026, 7, 2, 12, tzinfo=UTC),
        "source_repository": "danielcanfly/knowledge-source",
        "source_commit_sha": "a" * 40,
        "foundation_commit_sha": "d" * 40,
    }
    first = compile_release(work_root=tmp_path / "a", **kwargs)
    second = compile_release(work_root=tmp_path / "b", **kwargs)
    assert first.release_id == second.release_id
    assert (first.release_root / "bundle.tar.gz").read_bytes() == (
        second.release_root / "bundle.tar.gz"
    ).read_bytes()
    assert first.manifest == second.manifest


def test_pointer_changes_last(built_store) -> None:
    store, compiled, result = built_store
    pointer = store.get("channels/staging.json")
    assert compiled.release_id.encode() in pointer
    assert store.head(result.manifest_key) is not None
    for artifact in compiled.manifest["artifacts"]:
        assert store.head(artifact["key"]) is not None


def test_immutable_collision_is_rejected(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    compiled = compile_release(
        bundle_root=ROOT / "examples/okf-bundle",
        work_root=tmp_path / "builds",
        release_time=datetime(2026, 7, 2, 12, tzinfo=UTC),
        source_repository="danielcanfly/knowledge-source",
        source_commit_sha="a" * 40,
        foundation_commit_sha="d" * 40,
    )
    key = compiled.manifest["artifacts"][0]["key"]
    store.put(key, b"tampered", content_type="application/octet-stream")
    with pytest.raises(IntegrityError, match="collision"):
        publish_release(
            store=store,
            compiled=compiled,
            channel="staging",
            promoted_at="2026-07-02T12:00:00Z",
        )
    assert store.head("channels/staging.json") is None
