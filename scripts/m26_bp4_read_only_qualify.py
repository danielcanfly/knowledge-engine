#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

import boto3
import httpx
from botocore.config import Config

from knowledge_engine.m26_active_production_release import (
    PRODUCTION_POINTER_KEY,
    resolve_active_production_release,
)
from knowledge_engine.m26_production_promotion import (
    REQUIRED_QDRANT_PAYLOAD_INDEXES,
    ProductionQdrantQualification,
    QdrantQualification,
    build_promotion_plan,
    build_rollback_plan,
    pretty_json_bytes,
    promotion_plan_receipt,
    rollback_plan_receipt,
)
from knowledge_engine.storage import ObjectMetadata, sha256_bytes

BASE_COMMIT = "24e99a3deb20beb3e4d2888c3143fcc75962aa05"
BASE_TREE = "72d0e0969a6551ad15fa4947a524738b5176c5dc"
CANDIDATE_RELEASE = (
    "m26blog-ec79a3cad1d8-59012fe3818c-bp3r-"
    "24e99a3deb20beb3e4d2888c3143fcc75962aa05"
)
CANDIDATE_MANIFEST_KEY = f"releases/{CANDIDATE_RELEASE}/manifest.json"
CANDIDATE_MANIFEST_SHA256 = (
    "e6f8dc6d5e6e90afc7b5f1d7b36368f2127a7ea45584b223ea44d5546a3da2aa"
)
PROMOTED_AT = "2026-09-08T00:00:00Z"
OWNER_AUTHORIZATION = "BP-4 deterministic dry-run only; live production promotion forbidden"


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing required environment value: {name}")
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def json_object(data: bytes, label: str) -> dict[str, Any]:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a JSON object")
    return value


class R2ReadOnly:
    def __init__(self) -> None:
        self.bucket = required_env("R2_BUCKET")
        self.client = boto3.client(
            "s3",
            endpoint_url=required_env("R2_ENDPOINT_URL"),
            aws_access_key_id=required_env("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=required_env("R2_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("R2_REGION", "auto"),
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 4, "mode": "adaptive"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
        self.get_calls = 0
        self.head_calls = 0
        self.rejected_mutation_calls = 0

    def get(self, key: str) -> bytes:
        self.get_calls += 1
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def head(self, key: str) -> ObjectMetadata | None:
        self.head_calls += 1
        response = self.client.head_object(Bucket=self.bucket, Key=key)
        metadata = dict(response.get("Metadata") or {})
        return ObjectMetadata(
            key=key,
            bytes=int(response.get("ContentLength", 0)),
            etag=str(response.get("ETag", "")).strip(),
            sha256=metadata.get("sha256"),
            content_type=response.get("ContentType"),
        )

    def put(self, *_args: Any, **_kwargs: Any) -> ObjectMetadata:
        self.rejected_mutation_calls += 1
        raise SystemExit("BP4 read-only R2 guard rejected put")

    def delete(self, *_args: Any, **_kwargs: Any) -> None:
        self.rejected_mutation_calls += 1
        raise SystemExit("BP4 read-only R2 guard rejected delete")


class QdrantReadOnly:
    def __init__(self) -> None:
        self.url = required_env("QDRANT_URL").rstrip("/")
        self.api_key = required_env("QDRANT_READ_CREDENTIAL")
        self.calls: list[dict[str, str]] = []
        self.rejected_mutation_calls = 0

    def request(self, method: str, path: str, body: Any | None = None) -> dict[str, Any]:
        allowed_get = method == "GET" and body is None and (
            path == "/aliases" or path.startswith("/collections/")
        )
        allowed_post = method == "POST" and body is not None and (
            path.endswith("/points/count?consistency=all")
            or path.endswith("/points/scroll?consistency=all")
        )
        if not (allowed_get or allowed_post):
            self.rejected_mutation_calls += 1
            raise SystemExit(f"BP4 read-only Qdrant guard rejected {method} {path}")
        self.calls.append({"method": method, "path": path})
        response = httpx.request(
            method,
            self.url + path,
            headers={"api-key": self.api_key, "Accept": "application/json"},
            json=body,
            timeout=180.0,
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict) or value.get("status") != "ok":
            raise SystemExit(f"Qdrant returned invalid response for {path}")
        return value

    @staticmethod
    def collection_path(collection: str) -> str:
        return f"/collections/{quote(collection, safe='')}"

    def snapshot(self, collection: str) -> dict[str, Any]:
        raw = self.request("GET", self.collection_path(collection)).get("result")
        if not isinstance(raw, Mapping):
            raise SystemExit("Qdrant collection result missing")
        params = dict(dict(raw.get("config") or {}).get("params") or {})
        vectors = params.get("vectors")
        default = vectors.get("default") if isinstance(vectors, Mapping) else None
        if not isinstance(default, Mapping):
            raise SystemExit("Qdrant default vector missing")
        payload = raw.get("payload_schema")
        if not isinstance(payload, Mapping):
            raise SystemExit("Qdrant payload schema missing")
        return {
            "status": raw.get("status"),
            "points_count": raw.get("points_count"),
            "indexed_vectors_count": raw.get("indexed_vectors_count"),
            "vector_name": "default",
            "vector_dimension": default.get("size"),
            "distance": default.get("distance"),
            "payload_schema": {
                str(key): dict(value).get("data_type")
                for key, value in payload.items()
                if isinstance(value, Mapping)
            },
        }

    def aliases(self, collection: str) -> list[str]:
        raw = self.request("GET", "/aliases").get("result")
        aliases = raw.get("aliases") if isinstance(raw, Mapping) else None
        if not isinstance(aliases, list):
            raise SystemExit("Qdrant aliases result missing")
        return sorted(
            str(row["alias_name"])
            for row in aliases
            if isinstance(row, Mapping) and row.get("collection_name") == collection
        )

    def exact_count(
        self, collection: str, filter_value: Mapping[str, Any] | None = None
    ) -> int:
        body: dict[str, Any] = {"exact": True}
        if filter_value is not None:
            body["filter"] = dict(filter_value)
        raw = self.request(
            "POST",
            self.collection_path(collection) + "/points/count?consistency=all",
            body,
        ).get("result")
        count = raw.get("count") if isinstance(raw, Mapping) else None
        if isinstance(count, bool) or not isinstance(count, int):
            raise SystemExit("Qdrant count result missing")
        return count

    def inventory(self, collection: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset: Any = None
        path = self.collection_path(collection) + "/points/scroll?consistency=all"
        while True:
            body: dict[str, Any] = {
                "limit": 256,
                "with_payload": True,
                "with_vector": False,
            }
            if offset is not None:
                body["offset"] = offset
            raw = self.request("POST", path, body).get("result")
            points = raw.get("points") if isinstance(raw, Mapping) else None
            if not isinstance(points, list):
                raise SystemExit("Qdrant scroll result missing")
            rows.extend(dict(point) for point in points if isinstance(point, Mapping))
            offset = raw.get("next_page_offset") if isinstance(raw, Mapping) else None
            if offset is None:
                return rows


def artifact_census(
    store: R2ReadOnly, manifest: Mapping[str, Any], release_id: str
) -> dict[str, Any]:
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("manifest artifact family missing")
    rows = []
    for raw in sorted(entries, key=lambda value: str(dict(value).get("kind"))):
        if not isinstance(raw, Mapping):
            raise SystemExit("artifact entry malformed")
        kind, key = raw.get("kind"), raw.get("key")
        if not isinstance(kind, str) or not isinstance(key, str):
            raise SystemExit("artifact identity malformed")
        if not key.startswith(f"releases/{release_id}/"):
            raise SystemExit("artifact key escapes release namespace")
        data = store.get(key)
        head = store.head(key)
        observed_sha = sha256_bytes(data)
        if (
            observed_sha != raw.get("sha256")
            or len(data) != raw.get("bytes")
            or head is None
            or head.bytes != len(data)
        ):
            raise SystemExit(f"artifact integrity mismatch: {kind}")
        rows.append(
            {
                "kind": kind,
                "key": key,
                "sha256": observed_sha,
                "bytes": len(data),
                "etag": head.etag,
            }
        )
    return {"count": len(rows), "family": [row["kind"] for row in rows], "rows": rows}


def qdrant_identity_census(
    qdrant: QdrantReadOnly,
    *,
    collection: str,
    release_id: str,
    source_commit_sha: str,
    admission_sha256: str,
    expected_count: int,
    candidate: bool,
) -> dict[str, Any]:
    snapshot = qdrant.snapshot(collection)
    aliases = qdrant.aliases(collection)
    count = qdrant.exact_count(collection)
    points = qdrant.inventory(collection)
    identities = []
    drift = []
    for point in points:
        payload = point.get("payload")
        if not isinstance(payload, Mapping):
            raise SystemExit("Qdrant point payload missing")
        expected: dict[str, Any] = {
            "release_id": release_id,
            "source_commit_sha": source_commit_sha,
            "admission_sha256": admission_sha256,
        }
        if candidate:
            expected.update(
                {"candidate_release_eligible": True, "production_authority": False}
            )
        mismatches = sorted(key for key, value in expected.items() if payload.get(key) != value)
        if mismatches:
            drift.append({"point_id": str(point.get("id")), "fields": mismatches})
        identities.append(
            {
                "point_id": str(point.get("id")),
                "section_id": str(payload.get("section_id")),
                "release_id": payload.get("release_id"),
                "source_commit_sha": payload.get("source_commit_sha"),
                "admission_sha256": payload.get("admission_sha256"),
                "candidate_release_eligible": payload.get("candidate_release_eligible"),
                "production_authority": payload.get("production_authority"),
            }
        )
    point_ids = [row["point_id"] for row in identities]
    section_ids = [row["section_id"] for row in identities]
    if (
        snapshot.get("status") != "green"
        or snapshot.get("points_count") != expected_count
        or count != expected_count
        or len(points) != expected_count
        or "" in point_ids
        or "" in section_ids
        or len(set(point_ids)) != expected_count
        or len(set(section_ids)) != expected_count
        or drift
    ):
        raise SystemExit("Qdrant full identity census mismatch")
    return {
        "collection": collection,
        "snapshot": snapshot,
        "aliases": aliases,
        "exact_count": count,
        "full_scroll_count": len(points),
        "foreign_identity_count": len(drift),
        "point_ids_sha256": digest(sorted(point_ids)),
        "section_ids_sha256": digest(sorted(section_ids)),
        "aggregate_identity_sha256": digest(sorted(identities, key=lambda row: row["point_id"])),
    }


def production_census(store: R2ReadOnly, qdrant: QdrantReadOnly) -> dict[str, Any]:
    active = resolve_active_production_release(store)
    pointer_data = store.get(PRODUCTION_POINTER_KEY)
    pointer_head = store.head(PRODUCTION_POINTER_KEY)
    production_data = store.get(active.production_manifest_key)
    production_head = store.head(active.production_manifest_key)
    candidate_data = store.get(active.candidate_manifest_key)
    candidate_head = store.head(active.candidate_manifest_key)
    candidate_manifest = json_object(candidate_data, "active predecessor candidate")
    artifacts = artifact_census(store, candidate_manifest, active.release_id)
    qdrant_census = qdrant_identity_census(
        qdrant,
        collection=active.qdrant_collection,
        release_id=active.release_id,
        source_commit_sha=active.source_commit_sha,
        admission_sha256=active.admission_sha256,
        expected_count=active.semantic_point_count,
        candidate=False,
    )
    return {
        "pointer": {
            "key": PRODUCTION_POINTER_KEY,
            "sha256": sha256_bytes(pointer_data),
            "bytes": len(pointer_data),
            "etag": pointer_head.etag if pointer_head else None,
        },
        "release_id": active.release_id,
        "production_manifest": {
            "key": active.production_manifest_key,
            "sha256": sha256_bytes(production_data),
            "bytes": len(production_data),
            "etag": production_head.etag if production_head else None,
        },
        "candidate_manifest": {
            "key": active.candidate_manifest_key,
            "sha256": sha256_bytes(candidate_data),
            "bytes": len(candidate_data),
            "etag": candidate_head.etag if candidate_head else None,
        },
        "source_commit_sha": active.source_commit_sha,
        "admission_sha256": active.admission_sha256,
        "semantic_point_count": active.semantic_point_count,
        "artifacts": artifacts,
        "qdrant": qdrant_census,
        "deployment_identity": "not_observable_from_bounded_ingestion_credentials",
    }


def candidate_qdrant_qualification(
    qdrant: QdrantReadOnly, manifest: Mapping[str, Any]
) -> tuple[QdrantQualification, dict[str, Any]]:
    collection = str(manifest["qdrant_collection"])
    identities = dict(manifest["identities"])
    counts = dict(manifest["counts"])
    expected_count = int(counts["semantic_documents"])
    full = qdrant_identity_census(
        qdrant,
        collection=collection,
        release_id=str(manifest["release_id"]),
        source_commit_sha=str(identities["source_commit_sha"]),
        admission_sha256=str(identities["admission_sha256"]),
        expected_count=expected_count,
        candidate=True,
    )
    filt = {
        "must": [
            {"key": "release_id", "match": {"value": manifest["release_id"]}},
            {
                "key": "source_commit_sha",
                "match": {"value": identities["source_commit_sha"]},
            },
            {
                "key": "admission_sha256",
                "match": {"value": identities["admission_sha256"]},
            },
            {"key": "candidate_release_eligible", "match": {"value": True}},
            {"key": "production_authority", "match": {"value": False}},
        ]
    }
    filtered = qdrant.exact_count(collection, filt)
    snapshot = full["snapshot"]
    qualification = QdrantQualification(
        collection=collection,
        status=str(snapshot["status"]),
        points_count=int(snapshot["points_count"]),
        filtered_point_count=filtered,
        vector_name=str(snapshot["vector_name"]),
        vector_dimension=int(snapshot["vector_dimension"]),
        distance=str(snapshot["distance"]),
        payload_indexes=tuple(sorted(dict(snapshot["payload_schema"]))),
        alias_count=len(full["aliases"]),
    )
    if not REQUIRED_QDRANT_PAYLOAD_INDEXES.issubset(qualification.payload_indexes):
        raise SystemExit("candidate required Qdrant payload indexes missing")
    full["filtered_candidate_identity_count"] = filtered
    return qualification, full


def production_qdrant_qualification(
    census: Mapping[str, Any],
) -> ProductionQdrantQualification:
    qdrant = dict(census["qdrant"])
    snapshot = dict(qdrant["snapshot"])
    return ProductionQdrantQualification(
        collection=str(qdrant["collection"]),
        status=str(snapshot["status"]),
        points_count=int(snapshot["points_count"]),
        full_identity_count=int(qdrant["full_scroll_count"]),
        vector_name=str(snapshot["vector_name"]),
        vector_dimension=int(snapshot["vector_dimension"]),
        distance=str(snapshot["distance"]),
        aliases=tuple(str(value) for value in qdrant["aliases"]),
    )


def metadata(value: ObjectMetadata | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "key": value.key,
        "bytes": value.bytes,
        "etag": value.etag,
        "metadata_sha256": value.sha256,
        "content_type": value.content_type,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(pretty_json_bytes(value))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    store, qdrant = R2ReadOnly(), QdrantReadOnly()

    before = production_census(store, qdrant)
    candidate_data = store.get(CANDIDATE_MANIFEST_KEY)
    candidate_head = store.head(CANDIDATE_MANIFEST_KEY)
    if sha256_bytes(candidate_data) != CANDIDATE_MANIFEST_SHA256:
        raise SystemExit("exact BP-3 candidate manifest digest drift")
    candidate_manifest = json_object(candidate_data, "exact BP-3 candidate manifest")
    candidate_artifacts = artifact_census(store, candidate_manifest, CANDIDATE_RELEASE)
    qdrant_qualification, candidate_qdrant = candidate_qdrant_qualification(
        qdrant, candidate_manifest
    )

    plan = build_promotion_plan(
        store=store,
        candidate_manifest_key=CANDIDATE_MANIFEST_KEY,
        candidate_manifest_sha256=CANDIDATE_MANIFEST_SHA256,
        expected_predecessor_pointer_sha256=str(before["pointer"]["sha256"]),
        promoted_at=PROMOTED_AT,
        owner_authorization=OWNER_AUTHORIZATION,
        qdrant=qdrant_qualification,
        predecessor_qdrant=production_qdrant_qualification(before),
    )
    rollback = build_rollback_plan(plan)
    after = production_census(store, qdrant)
    if before != after:
        raise SystemExit("production before/after census mismatch")
    if store.rejected_mutation_calls or qdrant.rejected_mutation_calls:
        raise SystemExit("a remote mutation call reached a read-only guard")

    (output / "exact-predecessor-production-pointer.json").write_bytes(plan.predecessor.raw)
    (output / "proposed-production-manifest.json").write_bytes(
        plan.production_manifest_bytes
    )
    (output / "proposed-production-pointer.json").write_bytes(plan.target_pointer_bytes)
    write_json(output / "production-census-before.json", before)
    write_json(output / "production-census-after.json", after)
    write_json(
        output / "candidate-census.json",
        {
            "release_id": CANDIDATE_RELEASE,
            "manifest_key": CANDIDATE_MANIFEST_KEY,
            "manifest_sha256": sha256_bytes(candidate_data),
            "manifest_head": metadata(candidate_head),
            "artifacts": candidate_artifacts,
            "qdrant": candidate_qdrant,
        },
    )
    write_json(output / "promotion-dry-run-plan.json", promotion_plan_receipt(plan))
    write_json(output / "rollback-dry-run-plan.json", rollback_plan_receipt(rollback))
    receipt = {
        "schema_version": "knowledge-engine-m26-bp4-read-only-qualification/v1",
        "status": "PASS",
        "exact_base_commit": BASE_COMMIT,
        "exact_base_tree": BASE_TREE,
        "candidate_release_id": CANDIDATE_RELEASE,
        "candidate_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
        "predecessor_release_id": plan.predecessor.release_id,
        "predecessor_pointer_sha256": plan.predecessor.sha256,
        "proposed_production_manifest_key": plan.production_manifest_key,
        "proposed_production_manifest_sha256": plan.production_manifest_sha256,
        "proposed_production_pointer_sha256": plan.target_pointer_sha256,
        "production_before_after_equal": True,
        "dry_run_remote_writes": 0,
        "r2_get_calls": store.get_calls,
        "r2_head_calls": store.head_calls,
        "qdrant_read_calls": qdrant.calls,
        "r2_mutation_calls": 0,
        "qdrant_mutation_calls": 0,
        "candidate_qdrant_collection": qdrant_qualification.collection,
        "candidate_qdrant_full_count": candidate_qdrant["full_scroll_count"],
        "candidate_qdrant_filtered_count": qdrant_qualification.filtered_point_count,
        "production_pointer_writes": 0,
        "production_manifest_writes": 0,
        "candidate_mutations": 0,
        "active_qdrant_mutations": 0,
        "alias_mutations": 0,
        "deployments": 0,
        "public_traffic_mutations": 0,
    }
    receipt["receipt_sha256"] = digest(receipt)
    write_json(output / "qualification-receipt.json", receipt)
    checksums = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "CHECKSUMS.sha256":
            checksums.append(f"{sha256_bytes(path.read_bytes())}  {path.name}")
    (output / "CHECKSUMS.sha256").write_text("\n".join(checksums) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
