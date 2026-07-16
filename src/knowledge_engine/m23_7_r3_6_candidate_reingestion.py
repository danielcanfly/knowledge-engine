from __future__ import annotations

import argparse
import hashlib
import os
import urllib.error
import urllib.parse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import m23_qdrant_first_upsert as legacy
from .m23_7_r3_5_rank_quality_calibration_runtime import build_calibration_candidate

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-6-candidate-reingestion/v1"
RECEIPT_SCHEMA_VERSION = "knowledge-engine-m23-7-r3-6-candidate-reingestion-receipt/v1"
IMPLEMENTATION_ISSUE = 508
PARENT_ISSUE = 474
ENTRY_ENGINE_SHA = "b5501e8171f87ed25c937c245abc97e77fc32a28"
R3_5_IMPLEMENTATION_MERGE = "dd10d66083a3a4b81546467f26f0f3253b3a8a22"
R3_5_REPORT_FILE_SHA256 = "7a84c7e98b6e50d294b5bbbe1433e61f627f1550e740d0e50e8c57994cba5f36"
R3_5_REPORT_SHA256 = "410a5781504d2906f96191627e4e5cae46bb6eb1fa5dc907c1e84ec111c01bc2"
R3_5_CANDIDATE_ARTIFACT_SHA256 = (
    "8eed54902c73314ac2e5d5e187a788e44941dae250d9823d45b71ec57d1e1371"
)
R3_5_SEAL_SHA256 = "811942ecb900daba1fdde8ebd4baa33e6e31e8dd5e69ecbd44115f5b79dcf3a8"
R3_5_RECONCILIATION_SHA256 = (
    "fcb9cff2332865a0f2b5cd5b1ee27fbf488980fa343d16e117e9c3d4dd8cfc5d"
)
EXPECTED_EVIDENCE_SHA256 = "1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272"
EXPECTED_POINT_COUNT = 107
EXPECTED_VECTOR_NAME = "default"
EXPECTED_VECTOR_DIMENSION = 1024
EXPECTED_DISTANCE = "Cosine"
EXPECTED_PAYLOAD_SCHEMA = "knowledge-engine-m23-qdrant-payload/v2"
HISTORICAL_PILOT_COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024"
EXPECTED_COLLECTION = (
    "llm_wiki_m23_r3_5_candidate_" + R3_5_CANDIDATE_ARTIFACT_SHA256[:12]
)
READBACK_BATCH_SIZE = 32

canonical_json_bytes = legacy.canonical_json_bytes
canonical_sha256 = legacy.canonical_sha256
sha256_bytes = legacy.sha256_bytes
point_fingerprint = legacy.point_fingerprint
aggregate_fingerprint = legacy.aggregate_fingerprint
utc_now = legacy.utc_now


class GateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise GateError(code, message)


def canonical_contract() -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R3.6",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "r3_5_implementation_merge": R3_5_IMPLEMENTATION_MERGE,
            "r3_5_report_file_sha256": R3_5_REPORT_FILE_SHA256,
            "r3_5_report_sha256": R3_5_REPORT_SHA256,
            "r3_5_candidate_artifact_sha256": R3_5_CANDIDATE_ARTIFACT_SHA256,
            "r3_5_seal_sha256": R3_5_SEAL_SHA256,
            "r3_5_reconciliation_sha256": R3_5_RECONCILIATION_SHA256,
            "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
        },
        "collection": {
            "name": EXPECTED_COLLECTION,
            "historical_pilot_collection": HISTORICAL_PILOT_COLLECTION,
            "must_be_absent_before_create": True,
            "reuse_existing_collection": False,
            "point_count": EXPECTED_POINT_COUNT,
            "vector_name": EXPECTED_VECTOR_NAME,
            "vector_dimension": EXPECTED_VECTOR_DIMENSION,
            "distance": EXPECTED_DISTANCE,
            "sparse_vectors": None,
            "payload_schema_version": EXPECTED_PAYLOAD_SCHEMA,
        },
        "write": {
            "create_collection": True,
            "upsert_wait": True,
            "upsert_ordering": "strong",
            "full_id_readback": True,
            "readback_batch_size": READBACK_BATCH_SIZE,
            "rollback_on_post_create_failure": True,
            "rollback_scope": "exact-new-candidate-collection-only",
        },
        "authority": {
            "candidate_collection_create_authorized": True,
            "candidate_collection_write_authorized": True,
            "candidate_collection_readback_authorized": True,
            "candidate_collection_failure_rollback_authorized": True,
            "historical_pilot_mutation_authorized": False,
            "production_collection_mutation_authorized": False,
            "r2_mutation_authorized": False,
            "pointer_mutation_authorized": False,
            "source_mutation_authorized": False,
            "production_mutation_authorized": False,
            "live_acceptance_authorized": False,
            "retrieval_quality_blocker_cleared": False,
            "promotion_eligibility_granted": False,
            "production_retrieval": "lexical",
        },
    }
    contract["contract_sha256"] = canonical_sha256(contract)
    return contract


def build_candidate_points(evidence_zip: Path) -> dict[str, Any]:
    _require(
        hashlib.sha256(evidence_zip.read_bytes()).hexdigest() == EXPECTED_EVIDENCE_SHA256,
        "evidence_identity",
        "frozen evidence identity mismatch",
    )
    candidate = build_calibration_candidate(evidence_zip)
    _require(
        candidate.get("candidate_artifact_sha256") == R3_5_CANDIDATE_ARTIFACT_SHA256,
        "candidate_identity",
        "R3.5 candidate identity mismatch",
    )
    raw_points = candidate.get("points")
    _require(
        isinstance(raw_points, list) and len(raw_points) == EXPECTED_POINT_COUNT,
        "point_count",
        "candidate must contain exactly 107 points",
    )
    points: list[dict[str, Any]] = []
    ids: list[str] = []
    sections: list[str] = []
    for index, raw_point in enumerate(raw_points):
        _require(isinstance(raw_point, Mapping), "point_shape", f"invalid point {index}")
        payload = dict(raw_point.get("payload", {}))
        _require(
            payload.get("payload_schema_version") == EXPECTED_PAYLOAD_SCHEMA,
            "payload_schema",
            f"point {index} payload schema mismatch",
        )
        for field in ("section_title", "language", "section_id"):
            _require(
                isinstance(payload.get(field), str) and bool(payload[field]),
                field,
                f"point {index} lacks {field}",
            )
        payload.update(
            {
                "source_membership": "r3-6-candidate-live-acceptance-only",
                "candidate_collection": EXPECTED_COLLECTION,
                "candidate_artifact_sha256": R3_5_CANDIDATE_ARTIFACT_SHA256,
                "candidate_reingestion_issue": IMPLEMENTATION_ISSUE,
                "canonical_knowledge": False,
                "candidate_release_eligible": False,
                "production_authority": False,
            }
        )
        point = {
            "id": str(raw_point.get("id", "")),
            "vector": raw_point.get("vector"),
            "payload": payload,
        }
        point_fingerprint(point)
        points.append(point)
        ids.append(point["id"])
        sections.append(str(payload["section_id"]))
    _require(len(set(ids)) == EXPECTED_POINT_COUNT, "unique_ids", "point IDs are not unique")
    _require(
        len(set(sections)) == EXPECTED_POINT_COUNT,
        "unique_sections",
        "section IDs are not unique",
    )
    manifest: dict[str, Any] = {
        "schema_version": "knowledge-engine-m23-7-r3-6-candidate-points/v1",
        "milestone": "M23.7-R3.6",
        "collection": EXPECTED_COLLECTION,
        "contract_sha256": canonical_contract()["contract_sha256"],
        "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
        "r3_5_candidate_artifact_sha256": R3_5_CANDIDATE_ARTIFACT_SHA256,
        "point_count": len(points),
        "payload_schema_version": EXPECTED_PAYLOAD_SCHEMA,
        "vector_name": EXPECTED_VECTOR_NAME,
        "points": points,
        "authority": {
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
            "live_acceptance_complete": False,
            "retrieval_quality_blocker_cleared": False,
        },
    }
    manifest["ids_sha256"] = canonical_sha256(sorted(ids))
    manifest["aggregate_fingerprint_sha256"] = aggregate_fingerprint(points)
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    return manifest


class QdrantClient(legacy.QdrantClient):
    def request(
        self,
        method: str,
        path: str,
        body: Any | None = None,
        *,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        try:
            return super().request(method, path, body)
        except legacy.GateError as exc:
            cause = exc.__cause__
            if allow_not_found and isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                return None
            raise GateError("qdrant_request", "Qdrant request failed") from exc


def _escaped_collection() -> str:
    return urllib.parse.quote(EXPECTED_COLLECTION, safe="")


def collection_snapshot(
    client: QdrantClient,
    *,
    allow_absent: bool = False,
) -> dict[str, Any] | None:
    response = client.request(
        "GET",
        f"/collections/{_escaped_collection()}",
        allow_not_found=allow_absent,
    )
    if response is None:
        return None
    result = response.get("result")
    _require(isinstance(result, Mapping), "collection_result", "collection result missing")
    params = result.get("config", {}).get("params", {})
    vectors = params.get("vectors") if isinstance(params, Mapping) else None
    default_vector = vectors.get(EXPECTED_VECTOR_NAME) if isinstance(vectors, Mapping) else None
    _require(isinstance(default_vector, Mapping), "collection_vector", "default vector missing")
    return {
        "status": result.get("status"),
        "points_count": result.get("points_count"),
        "indexed_vectors_count": result.get("indexed_vectors_count"),
        "vector_name": EXPECTED_VECTOR_NAME,
        "vector_size": default_vector.get("size"),
        "vector_distance": default_vector.get("distance"),
        "sparse_vectors": params.get("sparse_vectors") if isinstance(params, Mapping) else None,
    }


def validate_collection_schema(snapshot: Mapping[str, Any], expected_count: int) -> None:
    expected = {
        "status": "green",
        "points_count": expected_count,
        "vector_name": EXPECTED_VECTOR_NAME,
        "vector_size": EXPECTED_VECTOR_DIMENSION,
        "vector_distance": EXPECTED_DISTANCE,
        "sparse_vectors": None,
    }
    for key, value in expected.items():
        _require(snapshot.get(key) == value, f"collection_{key}", f"collection {key} mismatch")


def create_collection(client: QdrantClient) -> None:
    _require(
        EXPECTED_COLLECTION != HISTORICAL_PILOT_COLLECTION,
        "collection_alias",
        "candidate aliases pilot",
    )
    response = client.request(
        "PUT",
        f"/collections/{_escaped_collection()}",
        {
            "vectors": {
                EXPECTED_VECTOR_NAME: {
                    "size": EXPECTED_VECTOR_DIMENSION,
                    "distance": EXPECTED_DISTANCE,
                }
            }
        },
    )
    _require(isinstance(response, Mapping), "create_response", "create response missing")
    _require(response.get("result") is True, "create_result", "collection create was not accepted")


def upsert_points(client: QdrantClient, points: Sequence[Mapping[str, Any]]) -> None:
    response = client.request(
        "PUT",
        f"/collections/{_escaped_collection()}/points?wait=true&ordering=strong",
        {"points": list(points)},
    )
    _require(isinstance(response, Mapping), "upsert_response", "upsert response missing")
    result = response.get("result")
    _require(isinstance(result, Mapping), "upsert_result", "upsert result missing")
    _require(
        result.get("status") in {"completed", "acknowledged"},
        "upsert_status",
        "upsert was not completed",
    )


def retrieve_points(client: QdrantClient, ids: Sequence[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for start in range(0, len(ids), READBACK_BATCH_SIZE):
        response = client.request(
            "POST",
            f"/collections/{_escaped_collection()}/points?consistency=all",
            {
                "ids": list(ids[start : start + READBACK_BATCH_SIZE]),
                "with_payload": True,
                "with_vector": [EXPECTED_VECTOR_NAME],
            },
        )
        _require(isinstance(response, Mapping), "readback_response", "readback response missing")
        result = response.get("result")
        _require(isinstance(result, list), "readback_result", "readback result missing")
        output.extend(result)
    return output


def rollback_collection(client: QdrantClient) -> bool:
    response = client.request("DELETE", f"/collections/{_escaped_collection()}")
    return (
        isinstance(response, Mapping)
        and response.get("result") is True
        and collection_snapshot(client, allow_absent=True) is None
    )


def _base_receipt(started_at: str) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "milestone": "M23.7-R3.6",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "started_at": started_at,
        "collection": EXPECTED_COLLECTION,
        "historical_pilot_collection": HISTORICAL_PILOT_COLLECTION,
        "contract_sha256": canonical_contract()["contract_sha256"],
        "r3_5_candidate_artifact_sha256": R3_5_CANDIDATE_ARTIFACT_SHA256,
        "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
        "privacy": {
            "credential_material_recorded": False,
            "service_url_recorded": False,
            "service_hostname_recorded": False,
            "raw_query_recorded": False,
            "raw_answer_recorded": False,
            "document_text_recorded": False,
        },
        "authority": {
            "historical_pilot_mutation_dispatched": False,
            "production_collection_mutation_dispatched": False,
            "r2_mutation_dispatched": False,
            "pointer_mutation_dispatched": False,
            "source_mutation_dispatched": False,
            "production_mutation_dispatched": False,
            "live_acceptance_complete": False,
            "retrieval_quality_blocker_cleared": False,
            "promotion_eligibility_granted": False,
            "production_retrieval": "lexical",
        },
    }


def _write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(receipt) + b"\n")


def execute(evidence_zip: Path, receipt_path: Path, timeout: int = 30) -> int:
    receipt = _base_receipt(utc_now())
    created = False
    client: QdrantClient | None = None
    try:
        manifest = build_candidate_points(evidence_zip)
        points = manifest["points"]
        ids = [str(point["id"]) for point in points]
        client = QdrantClient(
            os.environ.get("QDRANT_URL", ""),
            os.environ.get("QDRANT_API_KEY", ""),
            timeout,
        )
        _require(
            collection_snapshot(client, allow_absent=True) is None,
            "collection_exists",
            "candidate collection already exists",
        )
        create_collection(client)
        created = True
        created_snapshot = collection_snapshot(client)
        _require(created_snapshot is not None, "created_snapshot", "created collection missing")
        validate_collection_schema(created_snapshot, 0)
        upsert_points(client, points)
        returned = retrieve_points(client, ids)
        _require(len(returned) == EXPECTED_POINT_COUNT, "readback_count", "readback count mismatch")
        returned_by_id = {str(point.get("id")): point for point in returned}
        _require(
            len(returned_by_id) == EXPECTED_POINT_COUNT and set(returned_by_id) == set(ids),
            "readback_ids",
            "readback ID set mismatch",
        )
        expected_by_id = {str(point["id"]): point for point in points}
        mismatches = [
            point_id
            for point_id in sorted(ids)
            if point_fingerprint(expected_by_id[point_id])
            != point_fingerprint(returned_by_id[point_id])
        ]
        _require(not mismatches, "readback_fingerprint", "readback fingerprint mismatch")
        aggregate = aggregate_fingerprint(returned)
        _require(
            aggregate == manifest["aggregate_fingerprint_sha256"],
            "readback_aggregate",
            "readback aggregate mismatch",
        )
        final_snapshot = collection_snapshot(client)
        _require(final_snapshot is not None, "final_snapshot", "final collection missing")
        validate_collection_schema(final_snapshot, EXPECTED_POINT_COUNT)
        receipt.update(
            {
                "status": "pass_candidate_reingestion",
                "completed_at": utc_now(),
                "candidate_manifest_sha256": manifest["manifest_sha256"],
                "point_count": EXPECTED_POINT_COUNT,
                "ids_sha256": manifest["ids_sha256"],
                "aggregate_fingerprint_sha256": aggregate,
                "collection_absent_before_create": True,
                "collection_created": True,
                "collection_schema_verified_after_create": True,
                "strong_ordering_upsert_complete": True,
                "full_readback_complete": True,
                "readback_mismatch_count": 0,
                "rollback_dispatched": False,
                "rollback_complete": False,
                "network_calls": client.network_calls,
                "exit": {
                    "candidate_reingestion_complete": True,
                    "next_gate": "separately_governed_r3_live_acceptance",
                },
            }
        )
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        _write_receipt(receipt_path, receipt)
        return 0
    except (GateError, legacy.GateError) as exc:
        rollback_dispatched = created and client is not None
        rollback_complete = False
        if rollback_dispatched and client is not None:
            try:
                rollback_complete = rollback_collection(client)
            except (GateError, legacy.GateError):
                rollback_complete = False
        failure_code = exc.code if isinstance(exc, GateError) else "legacy_gate"
        receipt.update(
            {
                "status": (
                    "rejected_candidate_reingestion_rolled_back"
                    if rollback_complete
                    else "rejected_candidate_reingestion_no_mutation"
                    if not created
                    else "critical_candidate_reingestion_rollback_failed"
                ),
                "completed_at": utc_now(),
                "failure_code": failure_code,
                "collection_created": created,
                "rollback_dispatched": rollback_dispatched,
                "rollback_complete": rollback_complete,
                "network_calls": client.network_calls if client is not None else 0,
                "exit": {
                    "candidate_reingestion_complete": False,
                    "next_gate": "repair_iteration_required",
                },
            }
        )
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        _write_receipt(receipt_path, receipt)
        return 23 if created and not rollback_complete else 30


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guarded R3.6 candidate Qdrant reingestion")
    parser.add_argument("--evidence-zip", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return execute(
        Path(args.evidence_zip).expanduser().resolve(),
        Path(args.receipt).expanduser().resolve(),
        args.timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
