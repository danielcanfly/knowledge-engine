from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import urllib.parse
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .errors import IntegrityError, ReleaseConflictError
from .m25_blog_live_candidate import ADMISSION_SHA, SOURCE_SHA
from .storage import ObjectStore, create_object_store, sha256_bytes

SCHEMA_VERSION = "knowledge-engine-m25-10-production-promotion/v1"
PRODUCTION_POINTER_KEY = "channels/production.json"
CANDIDATE_CHANNEL = "candidate-blog-m25-10"
EXPECTED_RELEASE_ID = "m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043"
EXPECTED_ENGINE_SHA = "fe499db2e043209bfa4c2390d513c5dc579727a2"
EXPECTED_CANDIDATE_MANIFEST_SHA256 = (
    "f8e2a2f4b775e053bed93f3379f2aa6decd62b36e32380de0aff16caf14f18f3"
)
EXPECTED_PREVIOUS_POINTER_SHA256 = (
    "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
)
EXPECTED_PREVIOUS_RELEASE_ID = "20260708T040116Z-69a9f445699a"
EXPECTED_QDRANT_COLLECTION = (
    "m25_blog_m25blog_5250f8422f4f_f5f01d82c7a1_fe499db2e043_fe499db2e043"
)
EXPECTED_QDRANT_POINT_COUNT = 4197
PRODUCTION_MANIFEST_KEY = (
    f"releases/{EXPECTED_RELEASE_ID}/promotion/m25-10-production-manifest.json"
)


@dataclass(frozen=True)
class PromotionExpectation:
    candidate_channel: str = CANDIDATE_CHANNEL
    release_id: str = EXPECTED_RELEASE_ID
    engine_sha: str = EXPECTED_ENGINE_SHA
    candidate_manifest_sha256: str = EXPECTED_CANDIDATE_MANIFEST_SHA256
    previous_pointer_sha256: str = EXPECTED_PREVIOUS_POINTER_SHA256
    previous_release_id: str = EXPECTED_PREVIOUS_RELEASE_ID
    production_manifest_key: str = PRODUCTION_MANIFEST_KEY
    qdrant_collection: str = EXPECTED_QDRANT_COLLECTION
    qdrant_point_count: int = EXPECTED_QDRANT_POINT_COUNT


DEFAULT_EXPECTATION = PromotionExpectation()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _pretty(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityError(f"M25-PROD-001 {label} must be a JSON object")
    return value


def _json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        return _object(json.loads(data), label)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M25-PROD-002 {label} is invalid JSON") from exc


def _put_immutable_json(
    *,
    store: ObjectStore,
    key: str,
    data: bytes,
) -> None:
    digest = sha256_bytes(data)
    with suppress(ReleaseConflictError):
        store.put(
            key,
            data,
            content_type="application/json",
            sha256=digest,
            only_if_absent=True,
        )
    remote = store.get(key)
    if sha256_bytes(remote) != digest:
        raise IntegrityError(f"M25-PROD-003 immutable object collision: {key}")


def _candidate_pointer_key(expectation: PromotionExpectation) -> str:
    return f"channels/{expectation.candidate_channel}.json"


def _validate_candidate_pointer(
    pointer: Mapping[str, Any],
    expectation: PromotionExpectation,
) -> str:
    expected = {
        "schema_version": "1.0",
        "channel": expectation.candidate_channel,
        "release_id": expectation.release_id,
        "manifest_key": f"releases/{expectation.release_id}/manifest.json",
        "manifest_sha256": expectation.candidate_manifest_sha256,
    }
    for key, value in expected.items():
        if pointer.get(key) != value:
            raise IntegrityError(
                f"M25-PROD-004 candidate pointer {key} drift: "
                f"expected {value!r}, observed {pointer.get(key)!r}"
            )
    return str(pointer["manifest_key"])


def _validate_candidate_manifest(
    manifest: Mapping[str, Any],
    expectation: PromotionExpectation,
) -> None:
    expected = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": expectation.release_id,
        "status": "candidate",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise IntegrityError(
                f"M25-PROD-005 candidate manifest {key} drift: "
                f"expected {value!r}, observed {manifest.get(key)!r}"
            )
    authority = _object(manifest.get("authority"), "candidate authority")
    required_authority = {
        "source_admitted": True,
        "candidate_release_authorized": True,
        "semantic_serving_authorized": True,
        "production_pointer_authorized": False,
        "public_production_traffic_authorized": False,
    }
    for key, value in required_authority.items():
        if authority.get(key) is not value:
            raise IntegrityError(f"M25-PROD-006 candidate authority drift: {key}")
    identities = _object(manifest.get("identities"), "candidate identities")
    if identities.get("engine_commit_sha") != expectation.engine_sha:
        raise IntegrityError("M25-PROD-007 engine SHA drift")
    if identities.get("source_commit_sha") != SOURCE_SHA:
        raise IntegrityError("M25-PROD-008 source SHA drift")
    if identities.get("admission_sha256") != ADMISSION_SHA:
        raise IntegrityError("M25-PROD-009 admission SHA drift")
    counts = _object(manifest.get("counts"), "candidate counts")
    expected_counts = {
        "document_sources": 156,
        "document_series": 25,
        "document_articles": 156,
        "document_sections": 4041,
        "document_graph_nodes": 4222,
        "document_graph_edges": 8525,
        "semantic_documents": 4197,
    }
    for key, value in expected_counts.items():
        if counts.get(key) != value:
            raise IntegrityError(f"M25-PROD-010 count drift: {key}")


def build_production_manifest(
    candidate_manifest: Mapping[str, Any],
    *,
    candidate_manifest_key: str,
    expectation: PromotionExpectation = DEFAULT_EXPECTATION,
) -> dict[str, Any]:
    _validate_candidate_manifest(candidate_manifest, expectation)
    manifest = copy.deepcopy(dict(candidate_manifest))
    authority = _object(manifest["authority"], "production authority")
    authority["production_pointer_authorized"] = True
    authority["public_production_traffic_authorized"] = False
    manifest["status"] = "production"
    manifest["production_promotion"] = {
        "schema_version": SCHEMA_VERSION,
        "status": "production_pointer_authorized",
        "owner_authorization": "M25.10 production promotion authorized in Codex on 2026-07-24",
        "source_candidate_channel": expectation.candidate_channel,
        "source_candidate_manifest_key": candidate_manifest_key,
        "source_candidate_manifest_sha256": expectation.candidate_manifest_sha256,
        "accepted_owner_smoke": True,
        "production_pointer_authorized": True,
        "public_production_traffic_authorized": False,
        "public_production_traffic_target": None,
        "qdrant_candidate_collection": expectation.qdrant_collection,
        "qdrant_candidate_authority_filter": {
            "candidate_release_eligible": True,
            "production_authority": False,
        },
    }
    return manifest


def _current_pointer_state(
    pointer: Mapping[str, Any],
    production_manifest_sha256: str,
    expectation: PromotionExpectation,
) -> str:
    if pointer.get("release_id") == expectation.previous_release_id:
        return "ready_to_promote"
    if (
        pointer.get("channel") == "production"
        and pointer.get("release_id") == expectation.release_id
        and pointer.get("manifest_key") == expectation.production_manifest_key
        and pointer.get("manifest_sha256") == production_manifest_sha256
    ):
        return "already_target"
    return "unexpected_production_pointer"


def _qdrant_request(
    *,
    method: str,
    url: str,
    api_key: str,
    body: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        response = client.request(
            method,
            url,
            headers={"api-key": api_key, "Accept": "application/json"},
            json=body,
        )
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict) or value.get("status") != "ok":
        raise IntegrityError("M25-PROD-011 Qdrant returned non-ok status")
    return value


def verify_qdrant_candidate_collection(
    *,
    base_url: str,
    api_key: str,
    expectation: PromotionExpectation = DEFAULT_EXPECTATION,
) -> dict[str, Any]:
    escaped = urllib.parse.quote(expectation.qdrant_collection, safe="")
    result = _qdrant_request(
        method="POST",
        url=f"{base_url.rstrip('/')}/collections/{escaped}/points/count",
        api_key=api_key,
        body={
            "exact": True,
            "filter": {
                "must": [
                    {"key": "release_id", "match": {"value": expectation.release_id}},
                    {"key": "source_commit_sha", "match": {"value": SOURCE_SHA}},
                    {"key": "admission_sha256", "match": {"value": ADMISSION_SHA}},
                    {"key": "candidate_release_eligible", "match": {"value": True}},
                    {"key": "production_authority", "match": {"value": False}},
                ]
            },
        },
    )
    count = (result.get("result") or {}).get("count")
    if count != expectation.qdrant_point_count:
        raise IntegrityError(
            "M25-PROD-012 Qdrant candidate point count drift: "
            f"expected {expectation.qdrant_point_count}, observed {count}"
        )
    return {
        "collection": expectation.qdrant_collection,
        "filtered_point_count": count,
        "authority_filter": "candidate_release_eligible_true_and_production_authority_false",
        "production_qdrant_mutated": False,
    }


def promote_production(
    *,
    store: ObjectStore,
    promoted_at: str,
    expectation: PromotionExpectation = DEFAULT_EXPECTATION,
    verify_qdrant: bool = False,
) -> dict[str, Any]:
    candidate_pointer_bytes = store.get(_candidate_pointer_key(expectation))
    candidate_pointer = _json_bytes(candidate_pointer_bytes, "candidate pointer")
    candidate_manifest_key = _validate_candidate_pointer(candidate_pointer, expectation)
    candidate_manifest_bytes = store.get(candidate_manifest_key)
    candidate_manifest_sha256 = sha256_bytes(candidate_manifest_bytes)
    if candidate_manifest_sha256 != expectation.candidate_manifest_sha256:
        raise IntegrityError("M25-PROD-013 candidate manifest bytes drift")
    candidate_manifest = _json_bytes(candidate_manifest_bytes, "candidate manifest")

    production_manifest = build_production_manifest(
        candidate_manifest,
        candidate_manifest_key=candidate_manifest_key,
        expectation=expectation,
    )
    production_manifest_bytes = _pretty(production_manifest)
    production_manifest_sha256 = sha256_bytes(production_manifest_bytes)

    current_metadata = store.head(PRODUCTION_POINTER_KEY)
    if current_metadata is None:
        raise IntegrityError("M25-PROD-014 production pointer missing")
    current_pointer_bytes = store.get(PRODUCTION_POINTER_KEY)
    current_pointer_sha256 = sha256_bytes(current_pointer_bytes)
    current_pointer = _json_bytes(current_pointer_bytes, "production pointer")
    precondition_state = _current_pointer_state(
        current_pointer,
        production_manifest_sha256,
        expectation,
    )
    if precondition_state == "unexpected_production_pointer":
        raise IntegrityError("M25-PROD-015 production pointer precondition failed")
    if (
        precondition_state == "ready_to_promote"
        and current_pointer_sha256 != expectation.previous_pointer_sha256
    ):
        raise IntegrityError("M25-PROD-016 previous production pointer SHA drift")

    qdrant = None
    if verify_qdrant:
        qdrant = verify_qdrant_candidate_collection(
            base_url=os.environ["QDRANT_URL"],
            api_key=os.environ["QDRANT_API_KEY"],
            expectation=expectation,
        )

    pointer = {
        "schema_version": "1.0",
        "channel": "production",
        "release_id": expectation.release_id,
        "manifest_key": expectation.production_manifest_key,
        "manifest_sha256": production_manifest_sha256,
        "promoted_at": promoted_at,
        "promotion_schema_version": SCHEMA_VERSION,
        "source_candidate_channel": expectation.candidate_channel,
        "source_candidate_manifest_sha256": expectation.candidate_manifest_sha256,
        "production_authority": True,
        "public_production_traffic_mutated": False,
    }
    pointer_bytes = _pretty(pointer)
    pointer_sha256 = sha256_bytes(pointer_bytes)
    if precondition_state == "already_target":
        target_manifest = store.get(expectation.production_manifest_key)
        if sha256_bytes(target_manifest) != production_manifest_sha256:
            raise IntegrityError("M25-PROD-021 production manifest target drift")
        observed = store.get(PRODUCTION_POINTER_KEY)
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "already_promoted",
            "release_id": expectation.release_id,
            "production_manifest_key": expectation.production_manifest_key,
            "production_manifest_sha256": production_manifest_sha256,
            "production_pointer_key": PRODUCTION_POINTER_KEY,
            "production_pointer_sha256": sha256_bytes(observed),
            "previous_pointer_sha256": current_pointer_sha256,
            "qdrant": qdrant,
            "production_pointer_mutated": False,
            "public_production_traffic_mutated": False,
        }

    _put_immutable_json(
        store=store,
        key=expectation.production_manifest_key,
        data=production_manifest_bytes,
    )
    store.put(
        PRODUCTION_POINTER_KEY,
        pointer_bytes,
        content_type="application/json",
        sha256=pointer_sha256,
        expected_etag=current_metadata.etag,
    )
    observed = store.get(PRODUCTION_POINTER_KEY)
    if sha256_bytes(observed) != pointer_sha256:
        raise IntegrityError("M25-PROD-017 production pointer readback mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "production_pointer_promoted",
        "release_id": expectation.release_id,
        "source_candidate_channel": expectation.candidate_channel,
        "candidate_manifest_key": candidate_manifest_key,
        "candidate_manifest_sha256": expectation.candidate_manifest_sha256,
        "production_manifest_key": expectation.production_manifest_key,
        "production_manifest_sha256": production_manifest_sha256,
        "production_pointer_key": PRODUCTION_POINTER_KEY,
        "production_pointer_sha256": pointer_sha256,
        "previous_pointer_sha256": current_pointer_sha256,
        "qdrant": qdrant,
        "production_pointer_mutated": True,
        "public_production_traffic_mutated": False,
    }


def restore_production_pointer(
    *,
    store: ObjectStore,
    previous_pointer_path: Path,
    expected_previous_sha256: str,
) -> dict[str, Any]:
    previous = previous_pointer_path.read_bytes()
    previous_sha256 = sha256_bytes(previous)
    if previous_sha256 != expected_previous_sha256:
        raise IntegrityError("M25-PROD-018 rollback pointer bytes drift")
    current = store.head(PRODUCTION_POINTER_KEY)
    if current is None:
        raise IntegrityError("M25-PROD-019 production pointer missing during rollback")
    store.put(
        PRODUCTION_POINTER_KEY,
        previous,
        content_type="application/json",
        sha256=previous_sha256,
        expected_etag=current.etag,
    )
    observed = store.get(PRODUCTION_POINTER_KEY)
    if sha256_bytes(observed) != previous_sha256:
        raise IntegrityError("M25-PROD-020 rollback readback mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "production_pointer_restored",
        "production_pointer_key": PRODUCTION_POINTER_KEY,
        "production_pointer_sha256": previous_sha256,
        "public_production_traffic_mutated": False,
    }


def _timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("--output", type=Path, required=True)
    promote_parser.add_argument("--verify-qdrant", action="store_true")
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--previous-pointer", type=Path, required=True)
    restore_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    store = create_object_store(Settings.from_env())
    if args.command == "promote":
        result = promote_production(
            store=store,
            promoted_at=_timestamp(),
            verify_qdrant=args.verify_qdrant,
        )
    else:
        result = restore_production_pointer(
            store=store,
            previous_pointer_path=args.previous_pointer,
            expected_previous_sha256=EXPECTED_PREVIOUS_POINTER_SHA256,
        )
    result["workflow_run_id"] = os.environ.get("GITHUB_RUN_ID")
    result["workflow_run_attempt"] = os.environ.get("GITHUB_RUN_ATTEMPT")
    result["control_plane_sha"] = os.environ.get("GITHUB_SHA")
    result["result_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
