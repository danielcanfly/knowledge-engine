#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

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
    deterministic_point_id,
    embed_sections,
    validate_sections,
)
from knowledge_engine.m26_active_production_release import (
    PRODUCTION_POINTER_KEY,
    resolve_active_production_release,
)
from knowledge_engine.m26_admin_ingestion_sync import build_sync_plan
from knowledge_engine.storage import ObjectStore, create_object_store
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
    sha256_bytes,
    validate_with_runtime_code,
)

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
    vector = (
        (point.get("vector") or {}).get(QDRANT_VECTOR_NAME)
        if isinstance(point.get("vector"), Mapping)
        else None
    )
    payload = point.get("payload")
    point_id = point.get("id")
    if not isinstance(point_id, (str, int)) or isinstance(point_id, bool):
        raise SystemExit("point id invalid")
    if not isinstance(payload, Mapping):
        raise SystemExit("point payload invalid")
    if not isinstance(vector, list):
        raise SystemExit("point vector invalid")
    return canonical_sha256(
        {"id": str(point_id), "payload": dict(payload), "vector_sha256": vector_sha256(vector)}
    )


def aggregate_point_fingerprint(points: Sequence[Mapping[str, Any]]) -> str:
    rows = [
        {"id": str(point["id"]), "fingerprint_sha256": point_fingerprint(point)} for point in points
    ]
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

    def collection_path(self, collection_name: str = QDRANT_COLLECTION) -> str:
        return f"/collections/{quote(collection_name, safe='')}"

    def aliases_for(self, collection_name: str) -> list[str]:
        payload = self.request("GET", "/aliases")
        result = payload.get("result")
        aliases = result.get("aliases") if isinstance(result, Mapping) else None
        if not isinstance(aliases, list):
            raise SystemExit("Qdrant alias census response is malformed")
        return sorted(
            str(row["alias_name"])
            for row in aliases
            if isinstance(row, Mapping)
            and row.get("collection_name") == collection_name
            and isinstance(row.get("alias_name"), str)
        )

    def snapshot(self, collection_name: str = QDRANT_COLLECTION) -> dict[str, Any] | None:
        payload = self.request("GET", self.collection_path(collection_name))
        if payload.get("status") == "missing":
            return None
        result = payload.get("result")
        if not isinstance(result, dict):
            raise SystemExit("Qdrant collection response lacks result")
        params = (result.get("config") or {}).get("params") or {}
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

    def upsert_points_batched(
        self, points: Sequence[Mapping[str, Any]], *, batch_size: int = BATCH_SIZE
    ) -> list[dict[str, Any]]:
        operations = []
        path = self.collection_path() + "/points?wait=true&ordering=strong"
        for start in range(0, len(points), batch_size):
            batch = list(points[start : start + batch_size])
            response = self.request("PUT", path, {"points": batch})
            result = response.get("result")
            if not isinstance(result, Mapping) or result.get("status") not in {
                "completed",
                "acknowledged",
            }:
                raise SystemExit(f"Qdrant upsert batch failed at {start}: {response}")
            operations.append(
                {
                    "start": start,
                    "count": len(batch),
                    "status": result.get("status"),
                    "operation_id": result.get("operation_id"),
                }
            )
        return operations

    def retrieve_points(
        self,
        ids: Sequence[str],
        collection_name: str = QDRANT_COLLECTION,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        path = self.collection_path(collection_name) + "/points?consistency=all"
        for start in range(0, len(ids), READBACK_BATCH_SIZE):
            batch = list(ids[start : start + READBACK_BATCH_SIZE])
            response = self.request(
                "POST",
                path,
                {"ids": batch, "with_payload": True, "with_vector": [QDRANT_VECTOR_NAME]},
            )
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


def _put_or_verify_exact(store: ObjectStore, *, key: str, data: bytes) -> bool:
    digest = sha256_bytes(data)
    current = store.head(key)
    if current is not None:
        remote = store.get(key)
        if sha256_bytes(remote) != digest:
            raise SystemExit(f"R2 object exists with different digest: {key}")
        return False
    store.put(
        key,
        data,
        content_type="application/json",
        sha256=digest,
        only_if_absent=True,
    )
    if sha256_bytes(store.get(key)) != digest:
        raise SystemExit(f"R2 object readback digest mismatch: {key}")
    return True


def stage_bundle_artifacts_to_r2(
    store: ObjectStore,
    bundle_root: Path,
    manifest_key: str,
) -> dict[str, Any]:
    manifest_path = bundle_root / manifest_key
    manifest_data = manifest_path.read_bytes()
    if store.head(manifest_key) is not None:
        _put_or_verify_exact(store, key=manifest_key, data=manifest_data)
    manifest = read_json_bytes(manifest_data)
    release_id = manifest.get("release_id")
    if not isinstance(release_id, str) or not release_id:
        raise SystemExit("candidate manifest release identity is missing")
    if manifest_key != f"releases/{release_id}/manifest.json":
        raise SystemExit("candidate manifest key is not canonical")
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise SystemExit("candidate manifest artifact inventory is missing")
    inventory: list[tuple[str, Path, str, int]] = []
    seen_keys: set[str] = set()
    for entry in raw_artifacts:
        if not isinstance(entry, Mapping):
            raise SystemExit("candidate manifest artifact entry is malformed")
        key = entry.get("key")
        digest = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not isinstance(key, str) or not key.startswith(f"releases/{release_id}/artifacts/"):
            raise SystemExit("candidate artifact key escapes release namespace")
        if key in seen_keys:
            raise SystemExit(f"candidate artifact key is duplicated: {key}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise SystemExit(f"candidate artifact digest is malformed: {key}")
        if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool):
            raise SystemExit(f"candidate artifact byte count is malformed: {key}")
        path = (bundle_root / key).resolve()
        try:
            path.relative_to(bundle_root.resolve())
        except ValueError as exc:
            raise SystemExit("candidate artifact path escapes bundle root") from exc
        if not path.is_file():
            raise SystemExit(f"candidate artifact is missing: {key}")
        data = path.read_bytes()
        if len(data) != expected_bytes or sha256_bytes(data) != digest:
            raise SystemExit(f"candidate artifact inventory mismatch: {key}")
        seen_keys.add(key)
        inventory.append((key, path, digest, expected_bytes))
    uploaded = []
    skipped_exact = []
    for key, path, digest, expected_bytes in sorted(inventory):
        data = path.read_bytes()
        row = {"key": key, "sha256": digest, "bytes": expected_bytes}
        if _put_or_verify_exact(store, key=key, data=data):
            uploaded.append(row)
        else:
            skipped_exact.append(row)
    return {
        "uploaded": uploaded,
        "skipped_exact": skipped_exact,
        "total_artifact_files": len(inventory),
        "manifest_key": manifest_key,
        "manifest_deferred": True,
    }


def finalize_candidate_manifest(
    store: ObjectStore,
    bundle_root: Path,
    manifest_key: str,
) -> dict[str, Any]:
    data = (bundle_root / manifest_key).read_bytes()
    created = _put_or_verify_exact(store, key=manifest_key, data=data)
    return {
        "key": manifest_key,
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "created": created,
        "verified_exact": True,
    }


def _artifact_key(manifest: Mapping[str, Any], kind: str) -> str:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise SystemExit("active candidate manifest artifacts missing")
    matches = [
        item.get("key")
        for item in artifacts
        if isinstance(item, Mapping) and item.get("kind") == kind
    ]
    if len(matches) != 1 or not isinstance(matches[0], str):
        raise SystemExit(f"active candidate artifact missing: {kind}")
    return matches[0]


def _source_digests(value: Mapping[str, Any]) -> dict[str, str]:
    rows: Any = None
    for key in ("entries", "sources", "documents", "rows"):
        if isinstance(value.get(key), list):
            rows = value[key]
            break
    if not isinstance(rows, list):
        raise SystemExit("source index rows missing")
    output: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise SystemExit("source index contains a non-object row")
        source_id = row.get("source_id") or row.get("document_id") or row.get("id")
        digest = row.get("content_sha256") or row.get("digest") or row.get("record_sha256")
        if not isinstance(source_id, str) or not source_id:
            raise SystemExit("source index row identity missing")
        if not isinstance(digest, str) or len(digest) != 64:
            raise SystemExit(f"source index digest missing: {source_id}")
        if source_id in output:
            raise SystemExit(f"source index duplicate identity: {source_id}")
        output[source_id] = digest
    if not output:
        raise SystemExit("source index is empty")
    return output


def build_active_sync_evidence(
    store: ObjectStore,
    bundle_root: Path,
    bundle_info: Mapping[str, Any],
) -> dict[str, Any]:
    pointer_bytes = store.get(PRODUCTION_POINTER_KEY)
    active = resolve_active_production_release(store)
    if active.release_id == EXPECTED_RELEASE_ID:
        raise SystemExit("candidate release collides with active production release")
    if active.qdrant_collection == QDRANT_COLLECTION:
        raise SystemExit("candidate collection collides with active production collection")

    active_index_key = _artifact_key(
        active.candidate_manifest,
        "document_source_index",
    )
    active_digests = _source_digests(read_json_bytes(store.get(active_index_key)))
    candidate_index_key = str(dict(bundle_info["artifact_keys"])["document_source_index"])
    candidate_index = read_json(bundle_root / candidate_index_key)
    if not isinstance(candidate_index, Mapping):
        raise SystemExit("candidate source index must be an object")
    candidate_digests = _source_digests(candidate_index)
    documents = [
        {"document_id": source_id, "digest": digest}
        for source_id, digest in sorted(candidate_digests.items())
    ]
    plan = build_sync_plan(
        source_revision=EXPECTED_BLOG_SOURCE_SHA,
        documents=documents,
        active_document_digests=active_digests,
    )
    return {
        "production_pointer_key": PRODUCTION_POINTER_KEY,
        "production_pointer_sha256": sha256_bytes(pointer_bytes),
        "active_release_id": active.release_id,
        "active_production_manifest_key": active.production_manifest_key,
        "active_production_manifest_sha256": active.production_manifest_sha256,
        "active_candidate_manifest_key": active.candidate_manifest_key,
        "active_candidate_manifest_sha256": active.candidate_manifest_sha256,
        "active_qdrant_collection": active.qdrant_collection,
        "active_source_count": len(active_digests),
        "candidate_source_count": len(candidate_digests),
        "candidate_source_digests_sha256": canonical_sha256(candidate_digests),
        **plan,
    }


def build_production_census(
    store: ObjectStore,
    qdrant: Qdrant,
    bundle_root: Path,
    bundle_info: Mapping[str, Any],
) -> dict[str, Any]:
    sync = build_active_sync_evidence(store, bundle_root, bundle_info)
    return {
        "pointer_key": sync["production_pointer_key"],
        "pointer_sha256": sync["production_pointer_sha256"],
        "release_id": sync["active_release_id"],
        "production_manifest_key": sync["active_production_manifest_key"],
        "production_manifest_sha256": sync["active_production_manifest_sha256"],
        "candidate_manifest_key": sync["active_candidate_manifest_key"],
        "candidate_manifest_sha256": sync["active_candidate_manifest_sha256"],
        "qdrant_collection": sync["active_qdrant_collection"],
        "qdrant_collection_snapshot": qdrant.snapshot(sync["active_qdrant_collection"]),
        "qdrant_aliases": qdrant.aliases_for(sync["active_qdrant_collection"]),
        "deployment_identity": "not_observable_from_bounded_ingestion_path",
    }


def read_json_bytes(data: bytes) -> dict[str, Any]:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise SystemExit("JSON object expected")
    return value


def build_points(
    sections: Sequence[SectionInput],
    qdrant: Qdrant,
) -> tuple[list[dict[str, Any]], str, str, dict[str, Any]]:
    reuse_collection = os.environ.get("VECTOR_REUSE_COLLECTION", "").strip()
    if reuse_collection:
        reuse_release_id = require_env("VECTOR_REUSE_RELEASE_ID")
        expected_ids = [deterministic_point_id(section.section_id) for section in sections]
        returned = qdrant.retrieve_points(expected_ids, reuse_collection)
        by_id = {str(point.get("id")): point for point in returned}
        if len(returned) != len(sections) or set(by_id) != set(expected_ids):
            raise SystemExit("vector reuse collection has incomplete point identity set")
        vectors = []
        for section, point_id in zip(sections, expected_ids, strict=True):
            point = by_id[point_id]
            payload = point.get("payload")
            vector_map = point.get("vector")
            vector = vector_map.get(QDRANT_VECTOR_NAME) if isinstance(vector_map, Mapping) else None
            if not isinstance(payload, Mapping) or not isinstance(vector, list):
                raise SystemExit("vector reuse point shape mismatch")
            expected_payload = {
                "section_id": section.section_id,
                "text_sha256": hashlib.sha256(section.text.encode("utf-8")).hexdigest(),
                "embedding_provider": CLOUDFLARE_PROVIDER,
                "embedding_model": CLOUDFLARE_MODEL,
                "vector_dimension": VECTOR_DIMENSION,
                "vector_name": QDRANT_VECTOR_NAME,
                "release_id": reuse_release_id,
                "candidate_release_eligible": True,
                "production_authority": False,
            }
            for key, value in expected_payload.items():
                if payload.get(key) != value:
                    raise SystemExit(f"vector reuse payload mismatch {key}: {point_id}")
            vector_sha256(vector)
            vectors.append(vector)
        vector_lineage = {
            "mode": "verified_candidate_vector_reuse",
            "source_collection": reuse_collection,
            "source_release_id": reuse_release_id,
            "full_readback_count": len(returned),
            "text_identity_verified_count": len(returned),
            "provider_requests": 0,
            "provider": CLOUDFLARE_PROVIDER,
            "model": CLOUDFLARE_MODEL,
            "vector_dimension": VECTOR_DIMENSION,
        }
    else:
        cf = CloudflareConfig(
            account_id=require_env("CLOUDFLARE_ACCOUNT_ID"),
            api_token=os.environ.get("CLOUDFLARE_AI_TOKEN") or require_env("CLOUDFLARE_API_TOKEN"),
        )
        vectors = embed_sections(sections, cf)
        vector_lineage = {
            "mode": "fresh_cloudflare_workers_ai",
            "source_collection": None,
            "source_release_id": None,
            "full_readback_count": 0,
            "text_identity_verified_count": 0,
            "provider_requests": "batched_remote_inference",
            "provider": CLOUDFLARE_PROVIDER,
            "model": CLOUDFLARE_MODEL,
            "vector_dimension": VECTOR_DIMENSION,
        }
    points = build_qdrant_points(sections, vectors)
    for point in points:
        payload = point["payload"]
        payload["candidate_release_eligible"] = True
        payload["production_authority"] = False
        payload["release_id"] = EXPECTED_RELEASE_ID
        payload["source_commit_sha"] = EXPECTED_BLOG_SOURCE_SHA
        payload["source_repository_head_sha"] = EXPECTED_SOURCE_HEAD_SHA
        payload["admission_sha256"] = EXPECTED_ADMISSION_SHA256
    return (
        points,
        canonical_sha256([point["id"] for point in points]),
        aggregate_point_fingerprint(points),
        vector_lineage,
    )


def verify_qdrant_exact(
    qdrant: Qdrant, points: Sequence[Mapping[str, Any]], expected_aggregate: str
) -> dict[str, Any]:
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
    expected_section_ids = sorted(
        str(dict(point.get("payload") or {}).get("section_id") or "") for point in points
    )
    actual_section_ids = sorted(
        str(dict(point.get("payload") or {}).get("section_id") or "") for point in returned
    )
    missing_count = sum(not value for value in actual_section_ids)
    duplicate_count = len(actual_section_ids) - len(set(actual_section_ids))
    if missing_count:
        raise SystemExit("Qdrant readback contains missing section_id values")
    if duplicate_count:
        raise SystemExit("Qdrant readback contains duplicate section_id values")
    if actual_section_ids != expected_section_ids:
        raise SystemExit("Qdrant readback section_id set mismatch")
    payload_samples = []
    for point_id in ids[:5]:
        payload = dict(by_id[point_id].get("payload") or {})
        payload_samples.append(
            {
                k: payload.get(k)
                for k in sorted(payload)
                if k
                in {
                    "section_id",
                    "source_id",
                    "release_id",
                    "source_commit_sha",
                    "source_repository_head_sha",
                    "admission_sha256",
                    "candidate_release_eligible",
                    "production_authority",
                    "embedding_model",
                    "embedding_provider",
                    "vector_dimension",
                    "vector_name",
                    "text_sha256",
                }
            }
        )
    return {
        "point_count": len(returned),
        "aggregate_point_fingerprint_sha256": actual_aggregate,
        "section_id_count": len(actual_section_ids),
        "section_id_duplicate_count": duplicate_count,
        "section_id_missing_count": missing_count,
        "section_ids_sha256": canonical_sha256(actual_section_ids),
        "payload_samples": payload_samples,
    }


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
    settings = Settings.from_env()
    store = create_object_store(settings)
    qdrant = Qdrant(require_env("QDRANT_URL"), require_env("QDRANT_API_KEY"))
    initial_sync = build_active_sync_evidence(store, bundle_root, bundle_info)
    production_before = build_production_census(
        store,
        qdrant,
        bundle_root,
        bundle_info,
    )
    sections = load_materialization_sections(bundle_root)
    points, point_ids_sha, expected_aggregate, vector_lineage = build_points(
        sections,
        qdrant,
    )

    # Re-read authority immediately before the first candidate write. Any source
    # plan or active pointer drift invalidates the entire attempt.
    revalidated_sync = build_active_sync_evidence(store, bundle_root, bundle_info)
    if revalidated_sync != initial_sync:
        raise SystemExit("active production authority or deterministic sync plan drifted")
    r2_artifacts = stage_bundle_artifacts_to_r2(
        store,
        bundle_root,
        str(bundle_info["manifest_key"]),
    )

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
    pre_finalize_sync = build_active_sync_evidence(store, bundle_root, bundle_info)
    production_pre_finalize = build_production_census(
        store,
        qdrant,
        bundle_root,
        bundle_info,
    )
    if pre_finalize_sync != initial_sync or production_pre_finalize != production_before:
        raise SystemExit("production authority drifted before candidate manifest finalization")
    manifest = finalize_candidate_manifest(
        store,
        bundle_root,
        str(bundle_info["manifest_key"]),
    )
    production_after = build_production_census(
        store,
        qdrant,
        bundle_root,
        bundle_info,
    )
    if production_after != production_before:
        raise SystemExit("production authority changed during candidate materialization")

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
            "runtime_compatibility_mismatch_counts": validation["compatibility_report"].get(
                "mismatch_counts"
            ),
        },
        "qualification": {
            "REAL_CANDIDATE_SCHEMA_AND_ARTIFACT_QUALIFICATION": {
                **bundle_info["real_candidate_qualification"],
                "immutable_remote_artifact_count": r2_artifacts["total_artifact_files"],
                "immutable_remote_manifest_verified": manifest["verified_exact"],
                "qdrant_full_readback_count": readback["point_count"],
                "qdrant_payload_eligibility_verified": True,
            },
            "LOCAL_SYNTHETIC_POINTER_FIXTURE_VALIDATION": validation,
        },
        "lexical_candidate": bundle_info["section_identity"],
        "deterministic_sync": {
            **initial_sync,
            "revalidated_before_candidate_write": True,
        },
        "r2": {
            "artifacts": r2_artifacts,
            "manifest": manifest,
            "manifest_finalized_last": True,
        },
        "embedding": {
            "provider": CLOUDFLARE_PROVIDER,
            "model": CLOUDFLARE_MODEL,
            "vector_dimension": VECTOR_DIMENSION,
            "vector_name": QDRANT_VECTOR_NAME,
            "point_ids_sha256": point_ids_sha,
            "aggregate_point_fingerprint_sha256": expected_aggregate,
            "lineage": vector_lineage,
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
        "lexical_qdrant_parity": {
            "exact_section_id_set_equal": (
                bundle_info["section_identity"]["section_ids_sha256"]
                == readback["section_ids_sha256"]
            ),
            "lexical_section_ids_sha256": bundle_info["section_identity"]["section_ids_sha256"],
            "qdrant_section_ids_sha256": readback["section_ids_sha256"],
        },
        "authority": {
            "semantic_requests": 0,
            "provider_answer_requests": 0,
            "embedding_provider_requests": vector_lineage["provider_requests"],
            "qdrant_writes": len(operations),
            "r2_writes": len(r2_artifacts["uploaded"]) + int(manifest["created"]),
            "production_pointer_writes": 0,
            "canonical_route_mutations": 0,
            "source_repo_mutations": 0,
            "e5_consumed_attempts": 0,
        },
        "candidate_mutations": {
            "r2_artifact_creates": len(r2_artifacts["uploaded"]),
            "r2_manifest_creates": int(manifest["created"]),
            "qdrant_collection_creates": int(collection_action == "created"),
            "qdrant_upsert_batches": len(operations),
            "candidate_only": True,
        },
        "production_mutations": {
            "production_pointer_writes": 0,
            "production_manifest_writes": 0,
            "active_store_writes": 0,
            "active_collection_writes": 0,
            "qdrant_alias_writes": 0,
            "promotion_actions": 0,
            "deploy_actions": 0,
            "dns_mutations": 0,
            "access_mutations": 0,
            "public_traffic_mutations": 0,
            "merge_actions": 0,
            "before": production_before,
            "pre_finalize": production_pre_finalize,
            "after": production_after,
            "before_equals_after": True,
        },
    }
    if not receipt["lexical_qdrant_parity"]["exact_section_id_set_equal"]:
        raise SystemExit("lexical/Qdrant section identity digest mismatch")
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    receipt_path = output_dir / "m26-e4-isolated-materialization-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("M26_E4_ISOLATED_RUNTIME_MATERIALIZATION_PASS")
    print(
        json.dumps(
            {
                "release_id": EXPECTED_RELEASE_ID,
                "manifest_sha256": bundle_info["manifest_sha256"],
                "qdrant_collection": QDRANT_COLLECTION,
                "final_points": final_snapshot.get("points_count"),
                "r2_uploaded": len(r2_artifacts["uploaded"]) + int(manifest["created"]),
                "r2_skipped_exact": len(r2_artifacts["skipped_exact"])
                + int(not manifest["created"]),
                "upsert_batches": len(operations),
                "receipt_sha256": receipt["receipt_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
