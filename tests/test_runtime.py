from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.runtime import Runtime


def test_internal_query_returns_citations(tmp_path: Path, built_store) -> None:
    store, compiled, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")
    result = runtime.query("knowledge compiler", {"public", "internal"})
    assert result["status"] == "answered"
    assert result["release"]["release_id"] == compiled.release_id
    assert result["results"][0]["concept_id"] == "concepts/knowledge-compiler"
    assert result["results"][0]["citations"][0]["source_id"] == "src_google_okf_v01"


def test_public_query_cannot_retrieve_internal(tmp_path: Path, built_store) -> None:
    store, _, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")
    result = runtime.query("knowledge compiler", {"public"})
    assert result["status"] == "not_found"
    assert result["results"] == []
    assert result["retrieval"]["acl_filtered_count"] == 1
    assert result["non_answer_reason"] == "no_authorized_match"


def test_tampered_artifact_preserves_last_known_good(tmp_path: Path, built_store) -> None:
    store, compiled, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")
    active = runtime.refresh()
    lexical_key = next(
        item["key"]
        for item in compiled.manifest["artifacts"]
        if item["kind"] == "lexical_index"
    )
    metadata = store.head(lexical_key)
    assert metadata is not None
    store.put(
        lexical_key,
        store.get(lexical_key) + b"\n",
        content_type="application/json",
        expected_etag=metadata.etag,
    )
    with pytest.raises(IntegrityError, match="artifact integrity failure"):
        runtime.refresh()
    assert runtime.active is active
    result = runtime.query("knowledge compiler", {"public", "internal"})
    assert result["release"]["release_id"] == compiled.release_id


def test_pointer_manifest_mismatch_is_rejected(tmp_path: Path, built_store) -> None:
    store, _, _ = built_store
    pointer = json.loads(store.get("channels/staging.json"))
    pointer["manifest_sha256"] = "0" * 64
    metadata = store.head("channels/staging.json")
    assert metadata is not None
    store.put(
        "channels/staging.json",
        (json.dumps(pointer) + "\n").encode(),
        content_type="application/json",
        expected_etag=metadata.etag,
    )
    runtime = Runtime(store, tmp_path / "cache", "staging")
    with pytest.raises(IntegrityError, match="manifest hash"):
        runtime.refresh()
