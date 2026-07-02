from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine.errors import ReleaseConflictError
from knowledge_engine.storage import (
    FileObjectStore,
    R2ObjectStore,
    _etag_for_if_match,
)


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


def test_etag_for_if_match_preserves_or_adds_quotes() -> None:
    assert _etag_for_if_match('"abc123"') == '"abc123"'
    assert _etag_for_if_match("abc123") == '"abc123"'
    assert _etag_for_if_match('W/"abc123"') == '"abc123"'


class _FakeR2Client:
    def __init__(self) -> None:
        self.put_kwargs: dict[str, object] | None = None

    def head_object(self, **kwargs):
        del kwargs
        return {
            "ContentLength": 3,
            "ETag": '"abc123"',
            "Metadata": {"sha256": "0" * 64},
            "ContentType": "application/json",
        }

    def put_object(self, **kwargs):
        self.put_kwargs = kwargs
        return {}


def test_r2_preserves_etag_and_quotes_conditional_write() -> None:
    client = _FakeR2Client()
    store = object.__new__(R2ObjectStore)
    store.bucket = "bucket"
    store.client = client

    metadata = store.head("channels/staging.json")
    assert metadata is not None
    assert metadata.etag == '"abc123"'

    store.put(
        "channels/staging.json",
        b"new",
        content_type="application/json",
        expected_etag="abc123",
    )
    assert client.put_kwargs is not None
    assert client.put_kwargs["IfMatch"] == '"abc123"'
