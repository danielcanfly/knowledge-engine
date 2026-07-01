from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from knowledge_engine.compiler import compile_release
from knowledge_engine.publisher import publish_release
from knowledge_engine.storage import FileObjectStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def built_store(tmp_path: Path):
    store = FileObjectStore(tmp_path / "store")
    compiled = compile_release(
        bundle_root=ROOT / "examples/okf-bundle",
        work_root=tmp_path / "builds",
        release_time=datetime(2026, 7, 2, 12, tzinfo=UTC),
        source_repository="danielcanfly/knowledge-source",
        source_commit_sha="a" * 40,
        foundation_commit_sha="d" * 40,
    )
    result = publish_release(
        store=store,
        compiled=compiled,
        channel="staging",
        promoted_at="2026-07-02T12:00:00Z",
    )
    return store, compiled, result
