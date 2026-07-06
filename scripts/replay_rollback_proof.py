#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from knowledge_engine.errors import ReleaseConflictError
from knowledge_engine.promotion import (
    PromotionRequest,
    promote_release,
    rollback_release,
)
from knowledge_engine.storage import FileObjectStore, sha256_bytes

SOURCE_SHA = "6254725c38969e46e65aadcba13a8803b0d8a6a9"
BUILDER_SHA = "1b55c68a441def01a5277c94b350efab1437459d"
FOUNDATION_SHA = "d12c7c416c950d743d4cd5e7964fd3c3bc0d9062"
CONTROL_PLANE_SHA = "4716f6c9638ac8f06bfb48f164d79d972154961d"

OLD_RELEASE_ID = "20260703T074814Z-1b18538bfbac"
OLD_MANIFEST_SHA = "eab8d4191cba77e06e594d09bb48450635efd36e55e8accc14cec88e78e7de95"
TARGET_RELEASE_ID = "20260706T024200Z-19b86982de27"
OPERATION_ID = "m5-replay-rollback-proof-6254725c"
CHANNEL = f"candidate-source-{SOURCE_SHA}"


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _put_json(store: FileObjectStore, key: str, payload: dict[str, Any]) -> bytes:
    data = _json_bytes(payload)
    store.put(
        key,
        data,
        content_type="application/json",
        sha256=sha256_bytes(data),
        only_if_absent=True,
    )
    return data


def _seed_store(root: Path) -> tuple[FileObjectStore, bytes, str]:
    store = FileObjectStore(root / "object-store")
    manifest_key = f"releases/{TARGET_RELEASE_ID}/manifest.json"
    manifest = {
        "schema_version": "1.0",
        "release_id": TARGET_RELEASE_ID,
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
            "release_id": TARGET_RELEASE_ID,
            "manifest_key": manifest_key,
            "manifest_sha256": manifest_sha,
            "promoted_at": "2026-07-06T02:42:00Z",
        },
    )
    previous_bytes = _put_json(
        store,
        "channels/production.json",
        {
            "schema_version": "1.0",
            "channel": "production",
            "release_id": OLD_RELEASE_ID,
            "manifest_key": f"releases/{OLD_RELEASE_ID}/manifest.json",
            "manifest_sha256": OLD_MANIFEST_SHA,
            "promoted_at": "2026-07-03T07:48:14Z",
        },
    )
    return store, previous_bytes, manifest_sha


def _request(manifest_sha: str, operation_id: str = OPERATION_ID) -> PromotionRequest:
    return PromotionRequest(
        operation_id=operation_id,
        candidate_channel=CHANNEL,
        expected_release_id=TARGET_RELEASE_ID,
        expected_manifest_sha256=manifest_sha,
        expected_source_repository="danielcanfly/knowledge-source",
        expected_source_sha=SOURCE_SHA,
        expected_builder_sha=BUILDER_SHA,
        expected_foundation_sha=FOUNDATION_SHA,
        expected_previous_release_id=OLD_RELEASE_ID,
        expected_previous_manifest_sha256=OLD_MANIFEST_SHA,
        control_plane_sha=CONTROL_PLANE_SHA,
        reason="M5.6.5 replay and rollback proof",
        actor="github-actions",
    )


def run_replay_rollback_proof(evidence_dir: Path, run_id: str) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    store, previous_bytes, manifest_sha = _seed_store(evidence_dir)
    request = _request(manifest_sha)

    previous_pointer_sha = sha256_bytes(previous_bytes)
    _write_json(
        evidence_dir / "initial-production-pointer.json",
        {
            "release_id": OLD_RELEASE_ID,
            "manifest_sha256": OLD_MANIFEST_SHA,
            "pointer_sha256": previous_pointer_sha,
        },
    )

    promote_first = promote_release(
        store=store,
        request=request,
        promoted_at="2026-07-06T10:00:00Z",
    )
    _write_json(evidence_dir / "promote-first.json", promote_first.to_dict())

    target_bytes = store.get("channels/production.json")
    target_pointer_sha = sha256_bytes(target_bytes)

    promote_replay = promote_release(
        store=store,
        request=request,
        promoted_at="2026-07-06T10:01:00Z",
    )
    _write_json(evidence_dir / "promote-replay.json", promote_replay.to_dict())

    if promote_replay.idempotent is not True:
        raise RuntimeError("promotion replay was not idempotent")
    if store.get("channels/production.json") != target_bytes:
        raise RuntimeError("promotion replay changed target pointer bytes")

    rollback_first = rollback_release(
        store=store,
        operation_id=request.operation_id,
        reason="M5.6.5 rollback proof",
        actor="github-actions",
    )
    _write_json(evidence_dir / "rollback-first.json", rollback_first.to_dict())

    if store.get("channels/production.json") != previous_bytes:
        raise RuntimeError("rollback did not restore exact previous pointer bytes")

    rollback_replay = rollback_release(
        store=store,
        operation_id=request.operation_id,
        reason="M5.6.5 rollback proof replay",
        actor="github-actions",
    )
    _write_json(evidence_dir / "rollback-replay.json", rollback_replay.to_dict())

    if rollback_replay.idempotent is not True:
        raise RuntimeError("rollback replay was not idempotent")
    if store.get("channels/production.json") != previous_bytes:
        raise RuntimeError("rollback replay changed previous pointer bytes")

    stale_result: dict[str, Any]
    try:
        promote_release(
            store=store,
            request=request,
            promoted_at="2026-07-06T10:02:00Z",
        )
    except ReleaseConflictError as exc:
        stale_result = {
            "status": "rejected",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    else:
        raise RuntimeError("old promotion operation revived target after rollback")
    _write_json(evidence_dir / "stale-promote-after-rollback.json", stale_result)

    new_operation = _request(
        manifest_sha,
        operation_id="m5-replay-rollback-proof-new-op",
    )
    new_promote = promote_release(
        store=store,
        request=new_operation,
        promoted_at="2026-07-06T10:03:00Z",
    )
    _write_json(evidence_dir / "new-operation-promote.json", new_promote.to_dict())

    summary = {
        "status": "passed",
        "run_id": run_id,
        "operation_id": request.operation_id,
        "new_operation_id": new_operation.operation_id,
        "previous_release_id": OLD_RELEASE_ID,
        "target_release_id": TARGET_RELEASE_ID,
        "manifest_sha256": manifest_sha,
        "previous_pointer_sha256": previous_pointer_sha,
        "target_pointer_sha256": target_pointer_sha,
        "promote_replay_idempotent": promote_replay.idempotent,
        "rollback_replay_idempotent": rollback_replay.idempotent,
        "old_operation_after_rollback": stale_result,
        "new_operation_after_rollback": {
            "status": new_promote.status,
            "release_id": new_promote.release_id,
        },
        "governance": {
            "old_operation_cannot_revive_target_after_rollback": True,
            "new_operation_required_after_rollback": True,
            "rollback_restored_exact_previous_pointer_bytes": True,
        },
    }
    _write_json(evidence_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    result = run_replay_rollback_proof(args.evidence_dir, args.run_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    print("M5_REPLAY_ROLLBACK_PROOF_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
