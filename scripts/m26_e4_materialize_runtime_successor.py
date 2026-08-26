#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote

import httpx

from m26_e4_build_runtime_bundle import (
    EXPECTED_ADMISSION_SHA256,
    EXPECTED_BLOG_SOURCE_SHA,
    EXPECTED_EDGE_COUNT,
    EXPECTED_NODE_COUNT,
    EXPECTED_PACK_SHA256,
    EXPECTED_RELEASE_ID,
    EXPECTED_SEMANTIC_COUNT,
    EXPECTED_SOURCE_COUNT,
    EXPECTED_SOURCE_HEAD_SHA,
    QDRANT_COLLECTION,
    build_bundle,
    canonical_json_bytes,
    find_pack,
    read_json,
    read_jsonl,
    sha256_bytes,
    validate_with_runtime_code,
)

from knowledge_engine.config import Settings
from knowledge_engine.m23_cloudflare_qdrant import (
    CLOUDFLARE_MODEL,
    CLOUDFLARE_PROVIDER,
    QDRANT_DISTANCE,
    QDRANT_VECTOR_NAME,
    VECTOR_DIMENSION,
    CloudflareConfig,
    SectionInput,
    build_qdrant_points,
    embed_sections,
    validate_sections,
)
from knowledge_engine.storage import create_object_store

RECEIPT_SCHEMA = "m26-e4-isolated-runtime-materialization/v1"
BATCH_SIZE = 96
READBACK_BATCH_SIZE = 128


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value).rstrip(b"\n"))


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing required env: {name}")
    return value


def vector_sha256(vector: Sequence[Any]) -> str:
    if len(vector) != VECTOR_DIMENSION:
        raise SystemExit(f"vector dimension mismatch: {len(vector)}")
    floats = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SystemExit("vector contains non-numeric value")
        number = float(value)
        if not math.isfinite(number):
            raise SystemExit("vector contains non-finite value")
        floats.append(number)
    return hashlib.sha256(struct.pack(f"<{VECTOR_DIMENSION}f", *floats)).hexdigest()


def point_fingerprint(point: Mapping[str, Any]) -> str:
    vector = (point.get("vector") or {}).get(QDRANT_VECTOR_NAME) if isinstance(point.get("vector"), Mapping) else None
    payload = point.get("payload")
    point_id = point.get("id")
    if not isinstance(point_id, (str, int)) or isinstance(point_id, bool):
        raise SystemExit("point id invalid")
    if not isinstance(payload, Mapping):
        raise SystemExit("point payload invalid")
    if not isinstance(vector, list):
        raise SystemExit("point vector invalid")
    return canonical_sha256({"id": str(point_id), "payload": dict(payload), "vector_sha256": vector_sha256(vector)})


def aggregate_point_fingerprint(points: Sequence[Mapping[str, Any]]) -> str:
    rows = [{"id": str(point["id"]), "fingerprint_sha256": point_fingerprint(point)} for point in points]
    return canonical_sha256(sorted(rows, key=lambda item: item["id"]))


class Qdrant:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.network_calls = 0

    def request(self, method: str, path: str, body: Any | None = None) -> dict[str, Any]:
        headers = {"api-key": self.api_key, "Accept": "application/json"}
        kwargs: dict[str, Any] = {"headers": headers, "timeout": self.timeout}
        if body is not None:
            headers["Content-Type"] = "application/json"
            kwargs["json"] = body
        with httpx.Client(timeout=self.timeout) as client:
            self.network_calls += 1
            response = client.request(method, f"{self.base_url}{path}", **kwargs)
        if response.status_code == 404:
            return {"status": "missing", "result": None}
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise SystemExit(f"Qdrant non-object response at {path}")
        if payload.get("status") not in {"ok", "missing"}:
            raise SystemExit(f"Qdrant non-ok response at {path}: {payload.get('status')}")
        return payload

    def collection_path(self) -> str:
        return f"/collections/{quote(QDRANT_COLLECTION, safe='')}"

    def snapshot(self) -> dict[str, Any] | None:
        payload = self.request("GET", self.collection_path())
        if payload.get("status") == "missing":
            return None
        result = payload.get("result")
        if not isinstance(result, dict):
            raise SystemExit("Qdrant collection response lacks result")
        params = (((result.get("config") or {}).get("params") or {}))
        vectors = params.get("vectors") if isinstance(params, Mapping) else None
        default = vectors.get(QDRANT_VECTOR_NAME) if isinstance(vectors, Mapping) else None
        return {
            "status": result.get("status"),
            "points_count": result.get("points_count"),
            "indexed_vectors_count": result.get("indexed_vectors_count"),
            "vector_name": QDRANT_VECTOR_NAME if isinstance(default, Mapping) else None,
            "vector_dimension": default.get("size") if isinstance(default, Mapping) else None,
            "distance": default.get("distance") if isinstance(default, Mapping) else None,
            "sparse_vectors": params.get("sparse_vectors") if isinstance(params, Mapping) else None,
        }

    def ensure_collection(self) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
        before = self.snapshot()
        if before is None:
            payload = {
                "vectors": {
                    QDRANT_VECTOR_NAME: {
                        "size": VECTOR_DIMENSION,
                        "distance": QDRANT_DISTANCE,
                    }
                }
            }
            self.request("PUT", self.collection_path(), payload)
            after = self.snapshot()
            if after is None:
                raise SystemExit("Qdrant collection missing after create")
            return "created", before, after
        self.validate_collection_shape(before)
        return "preexisting", before, before

    def validate_collection_shape(self, snapshot: Mapping[str, Any]) -> None:
        expected = {
            "status": "green",
            "vector_name": QDRANT_VECTOR_NAME,
            "vector_dimension": VECTOR_DIMENSION,
            "distance": QDRANT_DISTANCE,
            "sparse_vectors": None,
        }
        for key, value in expected.items():
            if snapshot.get(key) != value:
                raise SystemExit(f"Qdrant collection shape mismatch {key}: {snapshot}")

    def upsert_points_batched(self, points: Sequence[Mapping[str, Any]], *, batch_size: int = BATCH_SIZE) -> list[dict[str, Any]]:
        operations = []
        path = self.collection_path() + "/points?wait=true&ordering=strong"
        for start in range(0, len(points), batch_size):
            batch = list(points[start : start + batch_size])
            response = self.request("PUT", path, {"points": batch})
            result = response.get("result")
            if not isinstance(result, Mapping) or result.get("status") not in {"completed", "acknowledged"}:
                raise SystemExit(f"Qdrant upsert batch failed at {start}: {response}")
            operations.append({"start": start, "count": len(batch), "status": result.get("status"), "operation_id": result.get("operation_id")})
        return operations

    def retrieve_points(self, ids: Sequence[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        path = self.collection_path() + "/points?consistency=all"
        for start in range(0, len(ids), READBACK_BATCH_SIZE):
            batch = list(ids[start : start + READBACK_BATCH_SIZE])
            response = self.request("POST", path, {"ids": batch, "with_payload": True, "with_vector": [QDRANT_VECTOR_NAME]})
            result = response.get("result")
            if not isinstance(result, list):
                raise SystemExit("Qdrant retrieve points response lacks result list")
            output.extend(result)
        return output


def load_materialization_sections(bundle_root: Path) -> list[SectionInput]:
    semantic_path = bundle_root / f"releases/{EXPECTED_RELEASE_ID}/artifacts/semantic_inputs.json"
    payload = read_json(semantic_path)
    documents = payload.get("documents")
    if not isinstance(documents, list) or len(documents) != EXPECTED_SEMANTIC_COUNT:
        raise SystemExit("semantic_inputs artifact document count mismatch")
    raw = []
    for row in documents:
        if not isinstance(row, Mapping):
            raise SystemExit("semantic input row not object")
        section_id = str(row.get("section_id") or "")
        text = str(row.get("text") or "")
        payload = dict(row.get("payload") if isinstance(row.get("payload"), Mapping) else {})
        payload.update(
            {
                "section_id": section_id,
                "release_id": EXPECTED_RELEASE_ID,
                "source_commit_sha": EXPECTED_BLOG_SOURCE_SHA,
                "source_repository_head_sha": EXPECTED_SOURCE_HEAD_SHA,
                "admission_sha256": EXPECTED_ADMISSION_SHA256,
                "candidate_release_eligible": True,
                "production_authority": False,
            }
        )
        raw.append({"section_id": section_id, "text": text, "payload": payload})
    return validate_sections(raw)


def upload_bundle_to_r2(bundle_root: Path, manifest_key: str) -> dict[str, Any]:
    settings = Settings.from_env()
    store = create_object_store(settings)
    files = sorted(path for path in bundle_root.rglob("*.json") if path.is_file())
    uploaded = []
    skipped_exact = []
    for path in files:
        key = str(path.relative_to(bundle_root)).replace(os.sep, "/")
        data = path.read_bytes()
        digest = sha256_bytes(data)
        current = store.head(key)
        if current is not None:
            if current.sha256 == digest or current.sha256 is None and current.bytes == len(data):
                skipped_exact.append({"key": key, "sha256": digest, "bytes": len(data)})
                continue
            raise SystemExit(f"R2 object exists with different digest: {key}")
        meta = store.put(key, data, content_type="application/json", sha256=digest, only_if_absent=True)
        uploaded.append({"key": key, "sha256": digest, "bytes": meta.bytes})
    if not any(item["key"] == manifest_key for item in [*uploaded, *skipped_exact]):
        raise SystemExit("manifest key was not uploaded or verified")
    return {"uploaded": uploaded, "skipped_exact": skipped_exact, "total_files": len(files), "manifest_key": manifest_key}


def build_points(sections: Sequence[SectionInput]) -> tuple[list[dict[str, Any]], str, str]:
    cf = CloudflareConfig(
        account_id=require_env("CLOUDFLARE_ACCOUNT_ID"),
        api_token=os.environ.get("CLOUDFLARE_AI_TOKEN") or require_env("CLOUDFLARE_API_TOKEN"),
    )
    vectors = embed_sections(sections, cf)
    points = build_qdrant_points(sections, vectors)
    for point in points:
        payload = point["payload"]
        payload["candidate_release_eligible"] = True
        payload["production_authority"] = False
        payload["release_id"] = EXPECTED_RELEASE_ID
        payload["source_commit_sha"] = EXPECTED_BLOG_SOURCE_SHA
        payload["source_repository_head_sha"] = EXPECTED_SOURCE_HEAD_SHA
        payload["admission_sha256"] = EXPECTED_ADMISSION_SHA256
    return points, canonical_sha256([point["id"] for point in points]), aggregate_point_fingerprint(points)


def verify_qdrant_exact(qdrant: Qdrant, points: Sequence[Mapping[str, Any]], expected_aggregate: str) -> dict[str, Any]:
    ids = [str(point["id"]) for point in points]
    returned = qdrant.retrieve_points(ids)
    if len(returned) != len(points):
        raise SystemExit(f"Qdrant readback point count mismatch: {len(returned)} vs {len(points)}")
    by_id = {str(point.get("id")): point for point in returned}
    if set(by_id) != set(ids):
        raise SystemExit("Qdrant readback ID set mismatch")
    actual_aggregate = aggregate_point_fingerprint([by_id[point_id] for point_id in ids])
    if actual_aggregate != expected_aggregate:
        raise SystemExit("Qdrant readback aggregate fingerprint mismatch")
    payload_samples = []
    for point_id in ids[:5]:
        payload = dict(by_id[point_id].get("payload") or {})
        payload_samples.append({k: payload.get(k) for k in sorted(payload) if k in {"section_id", "source_id", "release_id", "source_commit_sha", "source_repository_head_sha", "admission_sha256", "candidate_release_eligible", "production_authority", "embedding_model", "embedding_provider", "vector_dimension", "vector_name", "text_sha256"}})
    return {"point_count": len(returned), "aggregate_point_fingerprint_sha256": actual_aggregate, "payload_samples": payload_samples}


def validate_payload_samples(samples: Sequence[Mapping[str, Any]]) -> None:
    required = {
        "release_id": EXPECTED_RELEASE_ID,
        "source_commit_sha": EXPECTED_BLOG_SOURCE_SHA,
        "source_repository_head_sha": EXPECTED_SOURCE_HEAD_SHA,
        "admission_sha256": EXPECTED_ADMISSION_SHA256,
        "candidate_release_eligible": True,
        "production_authority": False,
        "embedding_model": CLOUDFLARE_MODEL,
        "embedding_provider": CLOUDFLARE_PROVIDER,
        "vector_dimension": VECTOR_DIMENSION,
        "vector_name": QDRANT_VECTOR_NAME,
    }
    for sample in samples:
        for key, value in required.items():
            if sample.get(key) != value:
                raise SystemExit(f"payload sample mismatch {key}: {sample}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-extract", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    started_at = utc_now()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pack = find_pack(Path(args.source_extract).resolve())
    bundle_info = build_bundle(pack, output_dir / "bundle-build")
    validation = validate_with_runtime_code(bundle_info, Path(args.repo_root).resolve())
    if validation["compatibility_report"].get("status") != "compatible":
        raise SystemExit("runtime compatibility failed before materialization")

    bundle_root = Path(str(bundle_info["bundle_root"]))
    r2 = upload_bundle_to_r2(bundle_root, str(bundle_info["manifest_key"]))
    sections = load_materialization_sections(bundle_root)
    points, point_ids_sha, expected_aggregate = build_points(sections)

    qdrant = Qdrant(require_env("QDRANT_URL"), require_env("QDRANT_API_KEY"))
    collection_action, before, after_create = qdrant.ensure_collection()
    qdrant.validate_collection_shape(after_create)
    if after_create.get("points_count") not in (0, EXPECTED_SEMANTIC_COUNT):
        raise SystemExit(f"unexpected pre-materialization point count: {after_create}")
    operations: list[dict[str, Any]] = []
    if after_create.get("points_count") == 0:
        operations = qdrant.upsert_points_batched(points)
        time.sleep(2)
    readback = verify_qdrant_exact(qdrant, points, expected_aggregate)
    validate_payload_samples(readback["payload_samples"])
    final_snapshot = qdrant.snapshot()
    if final_snapshot is None:
        raise SystemExit("Qdrant final snapshot missing")
    qdrant.validate_collection_shape(final_snapshot)
    if final_snapshot.get("points_count") != EXPECTED_SEMANTIC_COUNT:
        raise SystemExit(f"Qdrant final point count mismatch: {final_snapshot}")

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "M26_E4_ISOLATED_RUNTIME_MATERIALIZATION_PASS",
        "started_at": started_at,
        "completed_at": utc_now(),
        "source_head_sha": EXPECTED_SOURCE_HEAD_SHA,
        "source_commit_sha": EXPECTED_BLOG_SOURCE_SHA,
        "release_id": EXPECTED_RELEASE_ID,
        "source_admission_sha256": EXPECTED_ADMISSION_SHA256,
        "pack_sha256": EXPECTED_PACK_SHA256,
        "source_count": EXPECTED_SOURCE_COUNT,
        "semantic_point_count": EXPECTED_SEMANTIC_COUNT,
        "graph_node_count": EXPECTED_NODE_COUNT,
        "graph_edge_count": EXPECTED_EDGE_COUNT,
        "bundle": {
            "manifest_key": bundle_info["manifest_key"],
            "manifest_sha256": bundle_info["manifest_sha256"],
            "artifact_sha256": bundle_info["artifact_sha256"],
            "artifact_keys": bundle_info["artifact_keys"],
            "runtime_compatibility_status": validation["compatibility_report"].get("status"),
            "runtime_compatibility_mismatch_counts": validation["compatibility_report"].get("mismatch_counts"),
        },
        "r2": r2,
        "embedding": {
            "provider": CLOUDFLARE_PROVIDER,
            "model": CLOUDFLARE_MODEL,
            "vector_dimension": VECTOR_DIMENSION,
            "vector_name": QDRANT_VECTOR_NAME,
            "point_ids_sha256": point_ids_sha,
            "aggregate_point_fingerprint_sha256": expected_aggregate,
        },
        "qdrant": {
            "collection": QDRANT_COLLECTION,
            "collection_action": collection_action,
            "before": before,
            "after_create": after_create,
            "upsert_batches": operations,
            "final_snapshot": final_snapshot,
            "readback": readback,
            "network_calls": qdrant.network_calls,
        },
        "authority": {
            "semantic_requests": 0,
            "provider_answer_requests": 0,
            "embedding_provider_requests": "cloudflare_workers_ai_only_for_vector_materialization",
            "qdrant_writes": len(operations),
            "r2_writes": len(r2["uploaded"]),
            "production_pointer_writes": 0,
            "canonical_route_mutations": 0,
            "source_repo_mutations": 0,
            "e5_consumed_attempts": 0,
        },
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    receipt_path = output_dir / "m26-e4-isolated-materialization-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("M26_E4_ISOLATED_RUNTIME_MATERIALIZATION_PASS")
    print(json.dumps({
        "release_id": EXPECTED_RELEASE_ID,
        "manifest_sha256": bundle_info["manifest_sha256"],
        "qdrant_collection": QDRANT_COLLECTION,
        "final_points": final_snapshot.get("points_count"),
        "r2_uploaded": len(r2["uploaded"]),
        "r2_skipped_exact": len(r2["skipped_exact"]),
        "upsert_batches": len(operations),
        "receipt_sha256": receipt["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
