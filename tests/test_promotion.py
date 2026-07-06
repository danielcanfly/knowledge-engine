from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError, ReleaseConflictError
from knowledge_engine.promotion import (
    PromotionRequest,
    promote_release,
    rollback_release,
    verify_already_promoted,
    verify_promotion_candidate,
)
from knowledge_engine.storage import FileObjectStore, sha256_bytes

SOURCE_SHA = "a" * 40
BUILDER_SHA = "b" * 40
FOUNDATION_SHA = "d" * 40
CONTROL_PLANE_SHA = "f" * 40
OLD_RELEASE_ID = "20260702T072000Z-a78daaefcf49"
OLD_MANIFEST_SHA = "1" * 64
RELEASE_ID = "20260703T030000Z-123456789abc"
CHANNEL = f"candidate-source-{SOURCE_SHA}"


def _put_json(store: FileObjectStore, key: str, payload: dict) -> bytes:
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    store.put(
        key,
        data,
        content_type="application/json",
        sha256=sha256_bytes(data),
        only_if_absent=True,
    )
    return data


def _store(tmp_path: Path) -> tuple[FileObjectStore, bytes, str]:
    store = FileObjectStore(tmp_path / "store")
    manifest_key = f"releases/{RELEASE_ID}/manifest.json"
    manifest = {
        "schema_version": "1.0",
        "release_id": RELEASE_ID,
        "release_ready": True,
        "quality": {"overall": "passed"},
        "builder": {
            "name": "knowledge-engine",
            "version": "0.3.0",
            "git_sha": BUILDER_SHA,
        },
        "source": {
            "repository": "danielcanfly/knowledge-source",
            "commit_sha": SOURCE_SHA,
            "foundation_commit_sha": FOUNDATION_SHA,
            "dirty": False,
        },
    }
    manifest_bytes = _put_json(store, manifest_key, manifest)
    manifest_sha = sha256_bytes(manifest_bytes)
    _put_json(
        store,
        f"channels/{CHANNEL}.json",
        {
            "schema_version": "1.0",
            "channel": CHANNEL,
            "release_id": RELEASE_ID,
            "manifest_key": manifest_key,
            "manifest_sha256": manifest_sha,
            "promoted_at": "2026-07-03T03:00:00Z",
        },
    )
    production_bytes = _put_json(
        store,
        "channels/production.json",
        {
            "schema_version": "1.0",
            "channel": "production",
            "release_id": OLD_RELEASE_ID,
            "manifest_key": f"releases/{OLD_RELEASE_ID}/manifest.json",
            "manifest_sha256": OLD_MANIFEST_SHA,
            "promoted_at": "2026-07-02T07:20:00Z",
        },
    )
    return store, production_bytes, manifest_sha


def _request(
    manifest_sha: str,
    operation_id: str = "promote-m4-test-001",
) -> PromotionRequest:
    return PromotionRequest(
        operation_id=operation_id,
        candidate_channel=CHANNEL,
        expected_release_id=RELEASE_ID,
        expected_manifest_sha256=manifest_sha,
        expected_source_repository="danielcanfly/knowledge-source",
        expected_source_sha=SOURCE_SHA,
        expected_builder_sha=BUILDER_SHA,
        expected_foundation_sha=FOUNDATION_SHA,
        expected_previous_release_id=OLD_RELEASE_ID,
        expected_previous_manifest_sha256=OLD_MANIFEST_SHA,
        control_plane_sha=CONTROL_PLANE_SHA,
        reason="M4 acceptance",
        actor="github-actions",
    )


def test_promotion_is_idempotent_and_creates_immutable_evidence(tmp_path: Path) -> None:
    store, _, manifest_sha = _store(tmp_path)
    request = _request(manifest_sha)

    first = promote_release(
        store=store,
        request=request,
        promoted_at="2026-07-03T03:10:00Z",
    )
    second = promote_release(
        store=store,
        request=request,
        promoted_at="2026-07-03T03:11:00Z",
    )

    assert first.status == "promoted"
    assert first.idempotent is False
    assert first.previous_release_id == OLD_RELEASE_ID
    assert first.previous_manifest_sha256 == OLD_MANIFEST_SHA
    assert first.builder_sha == BUILDER_SHA
    assert second.status == "promoted"
    assert second.idempotent is True
    assert second.release_id == RELEASE_ID
    current = json.loads(store.get("channels/production.json"))
    assert current["release_id"] == RELEASE_ID
    assert current["promotion_id"] == request.operation_id
    assert store.head(first.intent_key) is not None
    assert store.head(first.receipt_key) is not None



def test_verify_promotion_candidate_checks_identity_without_writing(
    tmp_path: Path,
) -> None:
    store, _, manifest_sha = _store(tmp_path)
    request = _request(manifest_sha)

    result = verify_promotion_candidate(store=store, request=request)

    assert result.status == "candidate_verified"
    assert result.candidate_channel == CHANNEL
    assert result.release_id == RELEASE_ID
    assert result.manifest_sha256 == manifest_sha
    assert result.source_sha == SOURCE_SHA
    assert result.builder_sha == BUILDER_SHA
    assert result.foundation_sha == FOUNDATION_SHA
    assert result.control_plane_sha == CONTROL_PLANE_SHA
    assert store.head(f"operations/promotions/{request.operation_id}/intent.json") is None


def test_verify_already_promoted_accepts_exact_target_with_new_runtime_request(
    tmp_path: Path,
) -> None:
    store, _, manifest_sha = _store(tmp_path)
    request = _request(manifest_sha)
    promote_release(store=store, request=request, promoted_at="2026-07-03T03:10:00Z")
    replay_request = PromotionRequest(
        **{
            **request.to_dict(),
            "reason": "Reusable workflow replay after promotion is already target",
            "control_plane_sha": "e" * 40,
        }
    )

    result = verify_already_promoted(store=store, request=replay_request)

    assert result.status == "already_promoted"
    assert result.idempotent is True
    assert result.release_id == RELEASE_ID
    assert result.manifest_sha256 == manifest_sha
    assert result.source_sha == SOURCE_SHA
    assert result.builder_sha == BUILDER_SHA
    assert result.foundation_sha == FOUNDATION_SHA
    assert result.control_plane_sha == "e" * 40
    assert result.production_pointer_sha256 == sha256_bytes(
        store.get("channels/production.json")
    )
    assert result.intent_key == "not_written_for_already_promoted_replay"


def test_verify_already_promoted_rejects_wrong_candidate_identity(
    tmp_path: Path,
) -> None:
    store, _, manifest_sha = _store(tmp_path)
    request = _request(manifest_sha)
    promote_release(store=store, request=request, promoted_at="2026-07-03T03:10:00Z")
    replay_request = PromotionRequest(
        **{
            **request.to_dict(),
            "expected_builder_sha": "c" * 40,
        }
    )

    with pytest.raises(IntegrityError, match="builder git_sha mismatch"):
        verify_already_promoted(store=store, request=replay_request)

def test_rollback_restores_exact_previous_pointer_bytes(tmp_path: Path) -> None:
    store, original, manifest_sha = _store(tmp_path)
    request = _request(manifest_sha)
    promote_release(store=store, request=request, promoted_at="2026-07-03T03:10:00Z")

    first = rollback_release(
        store=store,
        operation_id=request.operation_id,
        reason="smoke check failed",
        actor="github-actions",
    )
    second = rollback_release(
        store=store,
        operation_id=request.operation_id,
        reason="smoke check failed",
        actor="github-actions",
    )

    assert first.idempotent is False
    assert second.idempotent is True
    assert first.restored_release_id == OLD_RELEASE_ID
    assert first.restored_manifest_sha256 == OLD_MANIFEST_SHA
    assert store.get("channels/production.json") == original


def test_stale_second_operation_cannot_overwrite_production(tmp_path: Path) -> None:
    store, _, manifest_sha = _store(tmp_path)
    first = _request(manifest_sha, "promote-m4-first")
    second = _request(manifest_sha, "promote-m4-second")

    promote_release(store=store, request=first, promoted_at="2026-07-03T03:10:00Z")

    with pytest.raises(ReleaseConflictError, match="release precondition"):
        promote_release(
            store=store,
            request=second,
            promoted_at="2026-07-03T03:11:00Z",
        )

    assert store.head("operations/promotions/promote-m4-second/intent.json") is None


def test_stale_previous_manifest_is_rejected_before_intent(tmp_path: Path) -> None:
    store, original, manifest_sha = _store(tmp_path)
    request = PromotionRequest(
        **{
            **_request(manifest_sha).to_dict(),
            "expected_previous_manifest_sha256": "2" * 64,
        }
    )

    with pytest.raises(ReleaseConflictError, match="manifest precondition"):
        promote_release(store=store, request=request)

    assert store.get("channels/production.json") == original
    assert store.head(f"operations/promotions/{request.operation_id}/intent.json") is None


def test_operation_id_collision_is_rejected(tmp_path: Path) -> None:
    store, _, manifest_sha = _store(tmp_path)
    first = _request(manifest_sha)
    promote_release(store=store, request=first, promoted_at="2026-07-03T03:10:00Z")
    changed = PromotionRequest(
        **{
            **first.to_dict(),
            "reason": "different request",
        }
    )

    with pytest.raises(ReleaseConflictError, match="different request"):
        promote_release(
            store=store,
            request=changed,
            promoted_at="2026-07-03T03:12:00Z",
        )


def test_candidate_source_mismatch_is_rejected(tmp_path: Path) -> None:
    store, _, manifest_sha = _store(tmp_path)
    request = PromotionRequest(
        **{
            **_request(manifest_sha).to_dict(),
            "expected_source_sha": "c" * 40,
        }
    )

    with pytest.raises(IntegrityError, match="commit_sha mismatch"):
        promote_release(store=store, request=request)


def test_candidate_builder_mismatch_is_rejected(tmp_path: Path) -> None:
    store, _, manifest_sha = _store(tmp_path)
    request = PromotionRequest(
        **{
            **_request(manifest_sha).to_dict(),
            "expected_builder_sha": "c" * 40,
        }
    )

    with pytest.raises(IntegrityError, match="builder git_sha mismatch"):
        promote_release(store=store, request=request)


def test_rollback_refuses_unrelated_current_pointer(tmp_path: Path) -> None:
    store, _, manifest_sha = _store(tmp_path)
    request = _request(manifest_sha)
    promote_release(store=store, request=request, promoted_at="2026-07-03T03:10:00Z")
    current = store.head("channels/production.json")
    assert current is not None
    unrelated = _put_json(
        FileObjectStore(tmp_path / "unrelated"),
        "pointer.json",
        {"channel": "production", "release_id": "unrelated"},
    )
    store.put(
        "channels/production.json",
        unrelated,
        content_type="application/json",
        sha256=sha256_bytes(unrelated),
        expected_etag=current.etag,
    )

    with pytest.raises(ReleaseConflictError, match="no longer matches"):
        rollback_release(
            store=store,
            operation_id=request.operation_id,
            reason="unsafe",
            actor="github-actions",
        )
