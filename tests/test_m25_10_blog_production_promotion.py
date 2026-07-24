from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine import m25_blog_production_promotion as subject
from knowledge_engine.errors import IntegrityError
from knowledge_engine.storage import FileObjectStore, sha256_bytes


def _write_json(store: FileObjectStore, key: str, value: dict[str, object]) -> str:
    data = json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"
    store.put(
        key,
        data,
        content_type="application/json",
        sha256=sha256_bytes(data),
    )
    return sha256_bytes(data)


def _candidate_manifest() -> dict[str, object]:
    return {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": subject.EXPECTED_RELEASE_ID,
        "status": "candidate",
        "authority": {
            "source_admitted": True,
            "candidate_release_authorized": True,
            "semantic_serving_authorized": True,
            "production_pointer_authorized": False,
            "public_production_traffic_authorized": False,
        },
        "identities": {
            "engine_commit_sha": subject.EXPECTED_ENGINE_SHA,
            "source_commit_sha": subject.SOURCE_SHA,
            "admission_sha256": subject.ADMISSION_SHA,
        },
        "counts": {
            "document_sources": 156,
            "document_series": 25,
            "document_articles": 156,
            "document_sections": 4041,
            "document_graph_nodes": 4222,
            "document_graph_edges": 8525,
            "semantic_documents": 4197,
        },
        "artifacts": [],
    }


def _seed_store(tmp_path: Path) -> tuple[FileObjectStore, subject.PromotionExpectation]:
    store = FileObjectStore(tmp_path)
    manifest_key = f"releases/{subject.EXPECTED_RELEASE_ID}/manifest.json"
    manifest_sha = _write_json(store, manifest_key, _candidate_manifest())
    _write_json(
        store,
        f"channels/{subject.CANDIDATE_CHANNEL}.json",
        {
            "schema_version": "1.0",
            "channel": subject.CANDIDATE_CHANNEL,
            "release_id": subject.EXPECTED_RELEASE_ID,
            "manifest_key": manifest_key,
            "manifest_sha256": manifest_sha,
            "promoted_at": "2026-07-24T00:00:00Z",
        },
    )
    previous_sha = _write_json(
        store,
        subject.PRODUCTION_POINTER_KEY,
        {
            "schema_version": "1.0",
            "channel": "production",
            "release_id": subject.EXPECTED_PREVIOUS_RELEASE_ID,
            "manifest_key": (
                f"releases/{subject.EXPECTED_PREVIOUS_RELEASE_ID}/manifest.json"
            ),
            "manifest_sha256": "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb",
            "promoted_at": "2026-07-08T04:01:16Z",
        },
    )
    expectation = subject.PromotionExpectation(
        candidate_manifest_sha256=manifest_sha,
        previous_pointer_sha256=previous_sha,
    )
    return store, expectation


def test_build_production_manifest_converts_authority_without_public_traffic() -> None:
    manifest = subject.build_production_manifest(
        _candidate_manifest(),
        candidate_manifest_key=f"releases/{subject.EXPECTED_RELEASE_ID}/manifest.json",
    )
    assert manifest["status"] == "production"
    authority = manifest["authority"]
    assert authority["production_pointer_authorized"] is True
    assert authority["public_production_traffic_authorized"] is False
    promotion = manifest["production_promotion"]
    assert promotion["accepted_owner_smoke"] is True
    assert promotion["public_production_traffic_target"] is None


def test_promote_production_updates_pointer_by_compare_and_swap(tmp_path: Path) -> None:
    store, expectation = _seed_store(tmp_path)
    result = subject.promote_production(
        store=store,
        promoted_at="2026-07-24T12:00:00Z",
        expectation=expectation,
    )
    assert result["status"] == "production_pointer_promoted"
    assert result["production_pointer_mutated"] is True
    assert result["public_production_traffic_mutated"] is False
    pointer = json.loads(store.get(subject.PRODUCTION_POINTER_KEY))
    assert pointer["release_id"] == subject.EXPECTED_RELEASE_ID
    assert pointer["manifest_key"] == subject.PRODUCTION_MANIFEST_KEY
    assert pointer["production_authority"] is True
    production_manifest = json.loads(store.get(subject.PRODUCTION_MANIFEST_KEY))
    assert production_manifest["status"] == "production"


def test_promote_is_idempotent_after_target_reached(tmp_path: Path) -> None:
    store, expectation = _seed_store(tmp_path)
    subject.promote_production(
        store=store,
        promoted_at="2026-07-24T12:00:00Z",
        expectation=expectation,
    )
    result = subject.promote_production(
        store=store,
        promoted_at="2026-07-24T12:30:00Z",
        expectation=expectation,
    )
    assert result["status"] == "already_promoted"
    assert result["production_pointer_mutated"] is False


def test_promote_rejects_unexpected_current_production_pointer(tmp_path: Path) -> None:
    store, expectation = _seed_store(tmp_path)
    _write_json(
        store,
        subject.PRODUCTION_POINTER_KEY,
        {
            "schema_version": "1.0",
            "channel": "production",
            "release_id": "unexpected",
            "manifest_key": "releases/unexpected/manifest.json",
            "manifest_sha256": "0" * 64,
        },
    )
    with pytest.raises(IntegrityError, match="precondition"):
        subject.promote_production(
            store=store,
            promoted_at="2026-07-24T12:00:00Z",
            expectation=expectation,
        )


def test_promote_rejects_candidate_manifest_authority_drift(tmp_path: Path) -> None:
    store, expectation = _seed_store(tmp_path)
    manifest = _candidate_manifest()
    manifest["authority"]["production_pointer_authorized"] = True
    manifest_key = f"releases/{subject.EXPECTED_RELEASE_ID}/manifest.json"
    manifest_sha = _write_json(store, manifest_key, manifest)
    _write_json(
        store,
        f"channels/{subject.CANDIDATE_CHANNEL}.json",
        {
            "schema_version": "1.0",
            "channel": subject.CANDIDATE_CHANNEL,
            "release_id": subject.EXPECTED_RELEASE_ID,
            "manifest_key": manifest_key,
            "manifest_sha256": manifest_sha,
        },
    )
    with pytest.raises(IntegrityError, match="candidate authority"):
        subject.promote_production(
            store=store,
            promoted_at="2026-07-24T12:00:00Z",
            expectation=subject.PromotionExpectation(
                candidate_manifest_sha256=manifest_sha,
                previous_pointer_sha256=expectation.previous_pointer_sha256,
            ),
        )


def test_restore_production_pointer_uses_exact_previous_bytes(tmp_path: Path) -> None:
    store, expectation = _seed_store(tmp_path)
    previous = store.get(subject.PRODUCTION_POINTER_KEY)
    previous_path = tmp_path / "previous-production-pointer.json"
    previous_path.write_bytes(previous)
    subject.promote_production(
        store=store,
        promoted_at="2026-07-24T12:00:00Z",
        expectation=expectation,
    )
    result = subject.restore_production_pointer(
        store=store,
        previous_pointer_path=previous_path,
        expected_previous_sha256=sha256_bytes(previous),
    )
    assert result["status"] == "production_pointer_restored"
    assert store.get(subject.PRODUCTION_POINTER_KEY) == previous
