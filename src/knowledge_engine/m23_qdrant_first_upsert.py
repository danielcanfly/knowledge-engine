from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPECTED_COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024"
EXPECTED_VECTOR_NAME = "default"
EXPECTED_VECTOR_DIMENSION = 1024
EXPECTED_DISTANCE = "Cosine"
EXPECTED_POINT_COUNT = 107
EXPECTED_POINTS_FILE_SHA256 = "0f1178949a5eccd7dec6c41ad09da423d65ff88de3a2d91c4a01319bd964963b"
EXPECTED_MANIFEST_SHA256 = "2814f138f2314779d77738f1e9bd3d0d0d7d388769244c3367232e5b278a0868"
EXPECTED_RELEASE_ID = "m23pilot-a07eb79e381ca7e635cc9139"
EXPECTED_RELEASE_MANIFEST_SHA256 = "a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9"
RECEIPT_SCHEMA = "knowledge-engine-m23-qdrant-first-upsert-receipt/v1"


class GateError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def f32_bytes(values: list[Any]) -> bytes:
    if len(values) != EXPECTED_VECTOR_DIMENSION:
        raise GateError(f"vector dimension mismatch: {len(values)}")
    floats: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GateError("vector contains a non-numeric value")
        number = float(value)
        if not math.isfinite(number):
            raise GateError("vector contains a non-finite value")
        floats.append(number)
    return struct.pack(f"<{EXPECTED_VECTOR_DIMENSION}f", *floats)


def point_fingerprint(point: dict[str, Any]) -> str:
    vector_container = point.get("vector")
    if not isinstance(vector_container, dict):
        raise GateError("point vector must be a named-vector object")
    vector = vector_container.get(EXPECTED_VECTOR_NAME)
    if not isinstance(vector, list):
        raise GateError("point lacks the default named vector")
    payload = point.get("payload")
    if not isinstance(payload, dict):
        raise GateError("point payload must be an object")
    point_id = point.get("id")
    if not isinstance(point_id, (str, int)) or isinstance(point_id, bool):
        raise GateError("point id must be a string or integer")
    vector_sha = sha256_bytes(f32_bytes(vector))
    return canonical_sha256(
        {
            "point_id": point_id,
            "payload": payload,
            "vector_sha256": vector_sha,
        }
    )


def aggregate_fingerprint(points: list[dict[str, Any]]) -> str:
    entries = [
        {"id": str(point["id"]), "fingerprint_sha256": point_fingerprint(point)}
        for point in points
    ]
    entries.sort(key=lambda item: item["id"])
    return canonical_sha256(entries)


def validate_points_artifact(path: Path) -> tuple[dict[str, Any], bytes, str, str]:
    raw = path.read_bytes()
    file_sha = sha256_bytes(raw)
    if file_sha != EXPECTED_POINTS_FILE_SHA256:
        raise GateError(
            "qdrant-points artifact SHA-256 mismatch: "
            f"expected {EXPECTED_POINTS_FILE_SHA256}, got {file_sha}"
        )
    try:
        artifact = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError(f"qdrant-points artifact is invalid JSON: {exc}") from exc
    if not isinstance(artifact, dict):
        raise GateError("qdrant-points artifact must be an object")
    expected_top = {
        "collection": EXPECTED_COLLECTION,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "point_count": EXPECTED_POINT_COUNT,
        "production_authority": False,
        "qdrant_write_authorized": False,
        "vector_name": EXPECTED_VECTOR_NAME,
    }
    for key, expected in expected_top.items():
        if artifact.get(key) != expected:
            raise GateError(f"qdrant-points artifact field mismatch: {key}")
    points = artifact.get("points")
    if not isinstance(points, list) or len(points) != EXPECTED_POINT_COUNT:
        raise GateError("qdrant-points artifact must contain exactly 107 points")
    ids: list[str] = []
    section_ids: list[str] = []
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            raise GateError(f"point {index} is not an object")
        point_id = point.get("id")
        if not isinstance(point_id, str) or not point_id:
            raise GateError(f"point {index} id must be a non-empty UUID string")
        ids.append(point_id)
        payload = point.get("payload")
        if not isinstance(payload, dict):
            raise GateError(f"point {index} payload is invalid")
        section_id = payload.get("section_id")
        if not isinstance(section_id, str) or not section_id:
            raise GateError(f"point {index} section_id is invalid")
        section_ids.append(section_id)
        required_payload = {
            "release_id": EXPECTED_RELEASE_ID,
            "release_manifest_sha256": EXPECTED_RELEASE_MANIFEST_SHA256,
            "vector_name": EXPECTED_VECTOR_NAME,
            "vector_dimension": EXPECTED_VECTOR_DIMENSION,
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
        }
        for key, expected in required_payload.items():
            if payload.get(key) != expected:
                raise GateError(f"point {index} payload mismatch: {key}")
        point_fingerprint(point)
    if len(set(ids)) != EXPECTED_POINT_COUNT:
        raise GateError("point IDs are not unique")
    if len(set(section_ids)) != EXPECTED_POINT_COUNT:
        raise GateError("section IDs are not unique")
    ids_sha = canonical_sha256(sorted(ids))
    aggregate_sha = aggregate_fingerprint(points)
    return artifact, raw, ids_sha, aggregate_sha


class QdrantClient:
    def __init__(self, base_url: str, api_key: str, timeout: int) -> None:
        if not base_url.startswith(("https://", "http://")):
            raise GateError("QDRANT_URL must start with https:// or http://")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.network_calls = 0

    def request(self, method: str, path: str, body: Any | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"api-key": self.api_key, "Accept": "application/json"}
        data = None
        if body is not None:
            data = canonical_json_bytes(body)
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        self.network_calls += 1
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            raise GateError(f"Qdrant HTTP {exc.code} at {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise GateError(f"Qdrant request failed at {path}: {exc.reason}") from exc
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GateError(f"Qdrant returned invalid JSON at {path}") from exc
        if not isinstance(result, dict):
            raise GateError(f"Qdrant returned a non-object response at {path}")
        if result.get("status") != "ok":
            raise GateError(f"Qdrant returned non-ok status at {path}")
        return result


def collection_snapshot(client: QdrantClient) -> dict[str, Any]:
    escaped = urllib.parse.quote(EXPECTED_COLLECTION, safe="")
    response = client.request("GET", f"/collections/{escaped}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise GateError("collection response lacks result object")
    vectors = result.get("config", {}).get("params", {}).get("vectors")
    sparse_vectors = result.get("config", {}).get("params", {}).get("sparse_vectors")
    default_vector = vectors.get(EXPECTED_VECTOR_NAME) if isinstance(vectors, dict) else None
    if not isinstance(default_vector, dict):
        raise GateError("collection lacks the expected default named vector")
    return {
        "status": result.get("status"),
        "points_count": result.get("points_count"),
        "indexed_vectors_count": result.get("indexed_vectors_count"),
        "vector_name": EXPECTED_VECTOR_NAME,
        "vector_size": default_vector.get("size"),
        "vector_distance": default_vector.get("distance"),
        "sparse_vectors": sparse_vectors,
    }


def validate_empty_preflight(snapshot: dict[str, Any]) -> None:
    expected = {
        "status": "green",
        "points_count": 0,
        "indexed_vectors_count": 0,
        "vector_name": EXPECTED_VECTOR_NAME,
        "vector_size": EXPECTED_VECTOR_DIMENSION,
        "vector_distance": EXPECTED_DISTANCE,
        "sparse_vectors": None,
    }
    if snapshot != expected:
        raise GateError(f"write-time preflight failed: {snapshot}")


def validate_final_collection(snapshot: dict[str, Any]) -> None:
    if snapshot.get("status") != "green":
        raise GateError(f"collection is not green after upsert: {snapshot}")
    if snapshot.get("points_count") != EXPECTED_POINT_COUNT:
        raise GateError(f"unexpected final point count: {snapshot}")
    if snapshot.get("vector_name") != EXPECTED_VECTOR_NAME:
        raise GateError("final vector name mismatch")
    if snapshot.get("vector_size") != EXPECTED_VECTOR_DIMENSION:
        raise GateError("final vector dimension mismatch")
    if snapshot.get("vector_distance") != EXPECTED_DISTANCE:
        raise GateError("final distance mismatch")
    if snapshot.get("sparse_vectors") is not None:
        raise GateError("unexpected sparse vectors after upsert")


def retrieve_points(client: QdrantClient, ids: list[str], batch_size: int = 32) -> list[dict[str, Any]]:
    escaped = urllib.parse.quote(EXPECTED_COLLECTION, safe="")
    output: list[dict[str, Any]] = []
    for start in range(0, len(ids), batch_size):
        batch = ids[start : start + batch_size]
        response = client.request(
            "POST",
            f"/collections/{escaped}/points?consistency=all",
            {
                "ids": batch,
                "with_payload": True,
                "with_vector": [EXPECTED_VECTOR_NAME],
            },
        )
        result = response.get("result")
        if not isinstance(result, list):
            raise GateError("retrieve-points response lacks result list")
        output.extend(result)
    return output


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(receipt) + b"\n")


def run(args: argparse.Namespace) -> int:
    started_at = utc_now()
    receipt_path = Path(args.receipt).expanduser().resolve()
    points_path = Path(args.points).expanduser().resolve()
    qdrant_url = os.environ.get("QDRANT_URL", "")
    qdrant_api_key = os.environ.get("QDRANT_API_KEY", "")
    if not qdrant_url or not qdrant_api_key:
        raise GateError("QDRANT_URL and QDRANT_API_KEY must both be set")

    artifact, _raw, ids_sha, expected_aggregate_sha = validate_points_artifact(points_path)
    points = artifact["points"]
    ids = [point["id"] for point in points]
    client = QdrantClient(qdrant_url, qdrant_api_key, args.timeout)
    before = collection_snapshot(client)
    validate_empty_preflight(before)

    escaped = urllib.parse.quote(EXPECTED_COLLECTION, safe="")
    upsert_response = client.request(
        "PUT",
        f"/collections/{escaped}/points?wait=true&ordering=strong",
        {"points": points},
    )
    upsert_result = upsert_response.get("result")
    if not isinstance(upsert_result, dict):
        raise GateError("upsert response lacks result object")
    if upsert_result.get("status") not in {"completed", "acknowledged"}:
        raise GateError(f"unexpected upsert status: {upsert_result}")

    returned = retrieve_points(client, ids)
    if len(returned) != EXPECTED_POINT_COUNT:
        raise GateError(f"readback returned {len(returned)} points, expected 107")
    returned_by_id = {str(point.get("id")): point for point in returned}
    if len(returned_by_id) != EXPECTED_POINT_COUNT:
        raise GateError("readback IDs are missing or duplicated")
    if set(returned_by_id) != set(ids):
        missing = sorted(set(ids) - set(returned_by_id))
        extra = sorted(set(returned_by_id) - set(ids))
        raise GateError(f"readback ID set mismatch; missing={missing}, extra={extra}")

    expected_by_id = {point["id"]: point for point in points}
    mismatches: list[str] = []
    for point_id in sorted(ids):
        expected_fingerprint = point_fingerprint(expected_by_id[point_id])
        actual_fingerprint = point_fingerprint(returned_by_id[point_id])
        if actual_fingerprint != expected_fingerprint:
            mismatches.append(point_id)
    if mismatches:
        raise GateError(f"readback content mismatch for point IDs: {mismatches}")

    actual_aggregate_sha = aggregate_fingerprint(returned)
    if actual_aggregate_sha != expected_aggregate_sha:
        raise GateError("aggregate readback fingerprint mismatch")

    after = collection_snapshot(client)
    validate_final_collection(after)
    completed_at = utc_now()
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "milestone": "M23.6.3",
        "operation": "first-non-production-pilot-upsert-and-readback",
        "status": "pass",
        "started_at": started_at,
        "completed_at": completed_at,
        "collection": EXPECTED_COLLECTION,
        "vector_contract": {
            "name": EXPECTED_VECTOR_NAME,
            "dimension": EXPECTED_VECTOR_DIMENSION,
            "distance": EXPECTED_DISTANCE,
        },
        "artifact": {
            "filename": points_path.name,
            "sha256": EXPECTED_POINTS_FILE_SHA256,
            "manifest_sha256": EXPECTED_MANIFEST_SHA256,
            "release_id": EXPECTED_RELEASE_ID,
            "release_manifest_sha256": EXPECTED_RELEASE_MANIFEST_SHA256,
            "point_count": EXPECTED_POINT_COUNT,
            "point_ids_sha256": ids_sha,
            "aggregate_point_fingerprint_sha256": expected_aggregate_sha,
        },
        "preflight": before,
        "upsert": {
            "wait": True,
            "ordering": "strong",
            "result_status": upsert_result.get("status"),
            "operation_id": upsert_result.get("operation_id"),
        },
        "readback": {
            "point_count": len(returned),
            "unique_point_ids": len(returned_by_id),
            "all_expected_ids_present": True,
            "all_payloads_and_vectors_match": True,
            "aggregate_point_fingerprint_sha256": actual_aggregate_sha,
        },
        "postflight": after,
        "network_calls": client.network_calls,
        "credential_material_recorded": False,
        "service_url_recorded": False,
        "canonical_knowledge": False,
        "candidate_release_eligible": False,
        "production_authority": False,
        "production_mutation_dispatched": False,
        "source_mutation_dispatched": False,
        "r2_mutation_dispatched": False,
        "pointer_mutation_dispatched": False,
        "permanent_ledger_mutation_dispatched": False,
        "delete_dispatched": False,
    }
    write_receipt(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"M23.6.3_UPSERT_READBACK_PASS receipt={receipt_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute the explicitly authorised M23.6.3 first Qdrant pilot upsert and verified readback."
    )
    parser.add_argument(
        "--points",
        required=True,
        help="Path to the exact M23.6.2 qdrant-points.json artifact.",
    )
    parser.add_argument(
        "--receipt",
        default="M23.6.3_first-upsert-receipt.json",
        help="Path for the redacted verification receipt.",
    )
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    try:
        return run(args)
    except (GateError, OSError) as exc:
        print(f"M23.6.3_FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
