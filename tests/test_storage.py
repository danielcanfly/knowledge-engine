from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine.errors import ReleaseConflictError
from knowledge_engine.storage import FileObjectStore


def test_file_store_compare_and_swap(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    first = store.put(
        "channels/staging.json",
        b"one",
        content_type="application/json",
        only_if_absent=True,
    )
    second = store.put(
        "channels/staging.json",
        b"two",
        content_type="application/json",
        expected_etag=first.etag,
    )
    assert store.get("channels/staging.json") == b"two"
    with pytest.raises(ReleaseConflictError, match="compare-and-swap"):
        store.put(
            "channels/staging.json",
            b"three",
            content_type="application/json",
            expected_etag=first.etag,
        )
    assert second.etag != first.etag


def test_file_store_blocks_path_escape(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    with pytest.raises(ValueError, match="escapes"):
        store.put("../secret", b"x", content_type="text/plain")
