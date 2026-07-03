from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError, ReleaseConflictError
from knowledge_engine.release_control import (
    PromotionRequest,
    promote_candidate,
    rollback_promotion,
)
from knowledge_engine.storage import FileObjectStore, sha256_bytes

SOURCE_SHA = "a" * 40
BUILDER_SHA = "b" * 40
FOUNDATION_SHA = "d" * 40
OLD_RELEASE = "20260702T072000Z-a78daaefcf49"
NEW_RELEASE = "20260702T152744Z-1b6a2109e6cd"
OLD_MANIFEST_SHA = "1" * 64
NEW_MANIFEST_SHA_PLACEHOLDER = "2" * 64
CHANNEL = f"candidate-source-{SOURCE_SHA}"


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _put_json(store: FileObjectStore, key: str, value: dict) -> bytes:
    data = _json_bytes(value)
    store.put(
        key,
        data,
        content_type="application/json",
        sha256=sha256_bytes(data),
        only_if_absent=True,
    )
    return data


def _fixture(tmp_path: Path) -> tuple[FileObjectStore, PromotionRequest, bytes]:
    store = FileObjectStore(tmp_path / "store")
    old_pointer = {
        "schema_version": "1.0",
        "channel": "production",
        "release_id": OLD_RELEASE,
        "manifest_key": f"releases/{OLD_RELEASE}/manifest.json",
        "manifest_sha256": OLD_MANIFEST_SHA,
        "promoted_at": "2026-07-02T07:30:00Z",
    }
    old_bytes = _put_json(store, "channels/production.json", old_pointer)

    manifest = {
        "schema_version": "1.0",
        "release_id": NEW_RELEASE,
        "source": {
            "repository": "danielcanfly/knowledge-source",
            "commit_sha": SOURCE_SHA,
        },
        "foundation_commit_sha": FOUNDATION_SHA,
        "artifacts": [],
    }
    manifest_bytes = _json_bytes(manifest)
    manifest_sha = sha256_bytes(manifest_bytes)
    manifest_key = f"releases/{NEW_RELEASE}/manifest.json"
    store.put(
        manifest_key,
        manifest_bytes,
        content_type="application/json",
        sha256=manifest_sha,
        only_if_absent=True,
    )
    _put_json(
        store,
        f"channels/{CHANNEL}.json",
        {
            "schema_version": "1.0",
            "channel": CHANNEL,
            "release_id": NEW_RELEASE,
            "manifest_key": manifest_key,
            "manifest_sha256": manifest_sha,
            "promoted_at": "2026-07-02T15:27:44Z",
        },
    )
    request = PromotionRequest(
        promotion_id="m4-release-0001",
        candidate_channel=CHANNEL,
        candidate_release_id=NEW_RELEASE,
        candidate_manifest_sha256=manifest_sha,
        expected_previous_release_id=OLD_RELEASE,
        expected_previous_manifest_sha256=OLD_MANIFEST_SHA,
        source_sha=SOURCE_SHA,
        builder_sha=BUILDER_SHA,
        foundation_sha=FOUNDATION_SHA,
        actor="danielcanfly",
        reason="Promote reviewed M4 acceptance release",
    )
    return store, request, old_bytes


def test_promote_and_rollback_restore_exact_pointer_bytes(tmp_path: Path) -> None:
    store, request, old_bytes = _fixture(tmp_path)

    promoted = promote_candidate(
        store=store,
        request=request,
        promoted_at="2026-07-03T06:00:00Z",
    )
    production_after = json.loads(store.get("channels/production.json"))

    assert promoted.status == "promoted"
    assert production_after["release_id"] == NEW_RELEASE
    assert promoted.previous_pointer_sha256 == sha256_bytes(old_bytes)
    assert store.head(promoted.journal_key) is not None

    rolled_back = rollback_promotion(
        store=store,
        promotion_id=request.promotion_id,
        rolled_back_at="2026-07-03T06:10:00Z",
    )

    assert rolled_back.status == "rolled_back"
    assert rolled_back.restored_release_id == OLD_RELEASE
    assert store.get("channels/production.json") == old_bytes
    assert rolled_back.restored_pointer_sha256 == sha256_bytes(old_bytes)
    assert store.head(rolled_back.rollback_journal_key) is not None


def test_promotion_replay_is_idempotent(tmp_path: Path) -> None:
    store, request, _ = _fixture(tmp_path)

    first = promote_candidate(
        store=store,
        request=request,
        promoted_at="2026-07-03T06:00:00Z",
    )
    second = promote_candidate(
        store=store,
        request=request,
        promoted_at="2026-07-03T07:00:00Z",
    )

    assert first == second
    assert second.promoted_at == "2026-07-03T06:00:00Z"


def test_promotion_id_cannot_be_reused_for_different_request(
    tmp_path: Path,
) -> None:
    store, request, _ = _fixture(tmp_path)
    promote_candidate(store=store, request=request)
    changed = PromotionRequest(
        **{**request.__dict__, "reason": "Different reviewed promotion reason"}
    )

    with pytest.raises(ReleaseConflictError, match="different request"):
        promote_candidate(store=store, request=changed)


def test_stale_previous_release_is_rejected_before_mutation(tmp_path: Path) -> None:
    store, request, old_bytes = _fixture(tmp_path)
    stale = PromotionRequest(
        **{
            **request.__dict__,
            "expected_previous_release_id": "20260701T000000Z-aaaaaaaaaaaa",
        }
    )

    with pytest.raises(ReleaseConflictError, match="release precondition"):
        promote_candidate(store=store, request=stale)

    assert store.get("channels/production.json") == old_bytes
    assert store.head(f"release-control/promotions/{stale.promotion_id}.json") is None


def test_candidate_manifest_bytes_must_match_pointer(tmp_path: Path) -> None:
    store, request, old_bytes = _fixture(tmp_path)
    candidate_key = f"channels/{CHANNEL}.json"
    candidate = json.loads(store.get(candidate_key))
    candidate["manifest_sha256"] = NEW_MANIFEST_SHA_PLACEHOLDER
    candidate_bytes = _json_bytes(candidate)
    current = store.head(candidate_key)
    assert current is not None
    store.put(
        candidate_key,
        candidate_bytes,
        content_type="application/json",
        sha256=sha256_bytes(candidate_bytes),
        expected_etag=current.etag,
    )
    changed = PromotionRequest(
        **{
            **request.__dict__,
            "candidate_manifest_sha256": NEW_MANIFEST_SHA_PLACEHOLDER,
        }
    )

    with pytest.raises(IntegrityError, match="manifest bytes"):
        promote_candidate(store=store, request=changed)

    assert store.get("channels/production.json") == old_bytes


def test_rollback_refuses_to_overwrite_a_newer_production_release(
    tmp_path: Path,
) -> None:
    store, request, _ = _fixture(tmp_path)
    promote_candidate(store=store, request=request)
    head = store.head("channels/production.json")
    assert head is not None
    newer = {
        "schema_version": "1.0",
        "channel": "production",
        "release_id": "20260703T000000Z-cccccccccccc",
        "manifest_key": "releases/newer/manifest.json",
        "manifest_sha256": "c" * 64,
        "promoted_at": "2026-07-03T07:00:00Z",
    }
    newer_bytes = _json_bytes(newer)
    store.put(
        "channels/production.json",
        newer_bytes,
        content_type="application/json",
        sha256=sha256_bytes(newer_bytes),
        expected_etag=head.etag,
    )

    with pytest.raises(ReleaseConflictError, match="no longer points"):
        rollback_promotion(store=store, promotion_id=request.promotion_id)

    assert store.get("channels/production.json") == newer_bytes


def test_rollback_replay_is_idempotent(tmp_path: Path) -> None:
    store, request, _ = _fixture(tmp_path)
    promote_candidate(store=store, request=request)

    first = rollback_promotion(
        store=store,
        promotion_id=request.promotion_id,
        rolled_back_at="2026-07-03T06:10:00Z",
    )
    second = rollback_promotion(
        store=store,
        promotion_id=request.promotion_id,
        rolled_back_at="2026-07-03T07:10:00Z",
    )

    assert first == second
    assert second.rolled_back_at == "2026-07-03T06:10:00Z"
