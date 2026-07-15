from __future__ import annotations

import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import m23_qdrant_pilot_ingestion as base
from .errors import IntegrityError
from .m23_cloudflare_qdrant import (
    CLOUDFLARE_MODEL,
    CLOUDFLARE_PROVIDER,
    QDRANT_DISTANCE,
    QDRANT_VECTOR_NAME,
    VECTOR_DIMENSION,
    deterministic_point_id,
)


def _benchmark_results_suite_sha256(raw: Mapping[str, Any]) -> str:
    m20_results = raw.get("m20_results")
    if not isinstance(m20_results, Mapping):
        raise IntegrityError("M23-INGEST-168 benchmark results lack M20 results")
    required = {"lexical", "vector", "rrf_hybrid_k60"}
    if not required <= set(m20_results):
        raise IntegrityError("M23-INGEST-169 benchmark results lack required methods")
    suite_hashes: set[str] = set()
    for method in sorted(required):
        value = m20_results.get(method)
        if not isinstance(value, Mapping):
            raise IntegrityError("M23-INGEST-170 benchmark method result must be an object")
        suite_hashes.add(
            base._sha256(value.get("suite_sha256"), f"m20_results.{method}.suite_sha256")
        )
    if len(suite_hashes) != 1:
        raise IntegrityError("M23-INGEST-171 benchmark method suite digests disagree")
    return next(iter(suite_hashes))


def _validate_semantic_sidecar(
    metadata: Mapping[str, Any],
    semantic_vectors: bytes,
    suite: Mapping[str, Any],
    benchmark_results: Mapping[str, Any] | None,
    documents: Sequence[Mapping[str, Any]],
    *,
    expected_artifact_id: str,
) -> None:
    if metadata.get("schema_version") != "knowledge-engine-semantic/v2":
        raise IntegrityError("M23-INGEST-151 unsupported semantic metadata schema")
    if metadata.get("artifact_id") != expected_artifact_id:
        raise IntegrityError("M23-INGEST-152 semantic artifact ID mismatch")
    if metadata.get("immutable") is not True or metadata.get("read_only") is not True:
        raise IntegrityError("M23-INGEST-153 semantic artifact must be immutable/read-only")
    if metadata.get("production_authority") is not False:
        raise IntegrityError("M23-INGEST-154 semantic artifact cannot carry production authority")
    base._self_digest(metadata, "metadata_sha256", "semantic metadata")

    expected_suite_sha = (
        base.canonical_sha256(suite)
        if benchmark_results is None
        else _benchmark_results_suite_sha256(benchmark_results)
    )
    if metadata.get("benchmark_suite_sha256") != expected_suite_sha:
        raise IntegrityError("M23-INGEST-155 semantic benchmark digest mismatch")

    model = metadata.get("model")
    vectors = metadata.get("vectors")
    semantic_documents = metadata.get("documents")
    if (
        not isinstance(model, Mapping)
        or not isinstance(vectors, Mapping)
        or not isinstance(semantic_documents, list)
    ):
        raise IntegrityError("M23-INGEST-156 incomplete semantic metadata")

    expected_model = {
        "provider": CLOUDFLARE_PROVIDER,
        "model_id": CLOUDFLARE_MODEL,
        "dimension": VECTOR_DIMENSION,
        "dtype": "float32",
        "endianness": "little",
        "normalized": True,
    }
    for key, value in expected_model.items():
        if model.get(key) != value:
            raise IntegrityError(f"M23-INGEST-157 semantic model mismatch: {key}")

    expected_vectors = {
        "filename": "semantic-vectors.f32",
        "sha256": base.bytes_sha256(semantic_vectors),
        "byte_length": base.EXPECTED_VECTOR_BYTES,
        "row_count": base.EXPECTED_DOCUMENT_COUNT,
        "dimension": VECTOR_DIMENSION,
        "dtype": "float32",
        "endianness": "little",
        "normalized": True,
    }
    if dict(vectors) != expected_vectors:
        raise IntegrityError("M23-INGEST-158 semantic vector metadata mismatch")
    if len(semantic_documents) != base.EXPECTED_DOCUMENT_COUNT:
        raise IntegrityError("M23-INGEST-159 semantic document count mismatch")

    by_section: dict[str, Mapping[str, Any]] = {}
    semantic_rows: set[int] = set()
    for item in semantic_documents:
        if not isinstance(item, Mapping):
            raise IntegrityError("M23-INGEST-160 semantic document must be an object")
        section_id = base._required_string(item.get("section_id"), "semantic.section_id", 500)
        if section_id in by_section:
            raise IntegrityError(f"M23-INGEST-172 duplicate semantic section_id: {section_id}")
        row = item.get("row")
        if (
            not isinstance(row, int)
            or isinstance(row, bool)
            or row < 0
            or row >= base.EXPECTED_DOCUMENT_COUNT
            or row in semantic_rows
        ):
            raise IntegrityError("M23-INGEST-173 invalid or duplicate semantic row")
        semantic_rows.add(row)
        by_section[section_id] = item

    expected_sections = {document["section_id"] for document in documents}
    if set(by_section) != expected_sections:
        raise IntegrityError("M23-INGEST-174 semantic section set mismatch")

    for document in documents:
        semantic = by_section[document["section_id"]]
        expected = {
            "concept_id": document["concept_id"],
            "section_id": document["section_id"],
            "language": document["language"],
            "audience": document["audience"],
            "source_path": document["source_path"],
            "source_sha256": document["source_sha256"],
        }
        actual = {key: semantic.get(key) for key in expected}
        if actual != expected:
            raise IntegrityError(
                f"M23-INGEST-175 semantic identity mismatch: {document['section_id']}"
            )


def build_dry_run(
    *,
    evidence_zip: Path,
    authority_contract_path: Path,
    builder_engine_sha: str,
    expected_evidence_sha256: str = base.EXPECTED_EVIDENCE_SHA256,
    expected_semantic_artifact_id: str = base.EXPECTED_SEMANTIC_ARTIFACT_ID,
    expected_authority_contract_sha256: str = base.EXPECTED_AUTHORITY_CONTRACT_SHA256,
) -> dict[str, Any]:
    evidence_sha = base.file_sha256(evidence_zip)
    if evidence_sha != base._sha256(expected_evidence_sha256, "expected_evidence_sha256"):
        raise IntegrityError("M23-INGEST-161 evidence ZIP digest mismatch")

    authority = base.load_authority_contract(
        authority_contract_path,
        expected_sha256=expected_authority_contract_sha256,
    )
    with zipfile.ZipFile(evidence_zip) as archive:
        root = base._archive_root(archive.namelist())
        receipt = base._read_json_bytes(
            archive.read(f"{root}/run-receipt.json"),
            "run-receipt.json",
        )
        base._validate_receipt(receipt)
        files = base._receipt_files(archive, root, receipt)
        suite = base._read_json_bytes(
            archive.read(f"{root}/benchmark-suite.json"),
            "benchmark-suite.json",
        )
        documents = base._validate_suite(suite, authority)
        vector_bytes = archive.read(f"{root}/pilot-document-vectors.f32")
        semantic_metadata_bytes = archive.read(
            f"{root}/semantic-artifact/semantic-metadata.json"
        )
        semantic_metadata = base._read_json_bytes(
            semantic_metadata_bytes,
            "semantic-artifact/semantic-metadata.json",
        )
        semantic_vectors = archive.read(
            f"{root}/semantic-artifact/semantic-vectors.f32"
        )
        benchmark_results: dict[str, Any] | None = None
        if f"{root}/benchmark-results.json" in archive.namelist():
            benchmark_results = base._read_json_bytes(
                archive.read(f"{root}/benchmark-results.json"),
                "benchmark-results.json",
            )

    if len(vector_bytes) != base.EXPECTED_VECTOR_BYTES:
        raise IntegrityError("M23-INGEST-162 frozen document vector byte count mismatch")
    if len(semantic_vectors) != base.EXPECTED_VECTOR_BYTES:
        raise IntegrityError("M23-INGEST-176 semantic vector byte count mismatch")

    vectors = base._unpack_vectors(vector_bytes, base.EXPECTED_DOCUMENT_COUNT)
    base._unpack_vectors(semantic_vectors, base.EXPECTED_DOCUMENT_COUNT)
    _validate_semantic_sidecar(
        semantic_metadata,
        semantic_vectors,
        suite,
        benchmark_results,
        documents,
        expected_artifact_id=expected_semantic_artifact_id,
    )

    suite_sha = base.canonical_sha256(suite)
    vector_sha = base.bytes_sha256(vector_bytes)
    semantic_metadata_sha = base.bytes_sha256(semantic_metadata_bytes)
    release = base._release_descriptor(
        builder_engine_sha=builder_engine_sha,
        authority=authority,
        suite_sha256=suite_sha,
        vector_sha256=vector_sha,
        semantic_metadata_sha256=semantic_metadata_sha,
        expected_evidence_sha256=evidence_sha,
        expected_semantic_artifact_id=expected_semantic_artifact_id,
    )

    point_summaries: list[dict[str, Any]] = []
    qdrant_points: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for document, vector in zip(documents, vectors, strict=True):
        row = document["row"]
        offset = row * VECTOR_DIMENSION * 4
        vector_row_bytes = vector_bytes[offset : offset + VECTOR_DIMENSION * 4]
        vector_row_sha = base.bytes_sha256(vector_row_bytes)
        point_id = deterministic_point_id(document["section_id"])
        if point_id in seen_ids:
            raise IntegrityError("M23-INGEST-164 duplicate deterministic point ID")
        seen_ids.add(point_id)
        article_id = base._article_id(document["section_id"])
        payload = {
            "payload_schema_version": base.PAYLOAD_SCHEMA,
            "section_id": document["section_id"],
            "article_id": article_id,
            "document_id": article_id,
            "concept_id": document["concept_id"],
            "source_path": document["source_path"],
            "source_sha256": document["source_sha256"],
            "text_sha256": document["text_sha256"],
            "audience": document["audience"],
            "source_membership": base.SOURCE_MEMBERSHIP,
            "release_id": release["release_id"],
            "release_manifest_sha256": release["release_manifest_sha256"],
            "graph_node_id": document["concept_id"],
            "embedding_provider": CLOUDFLARE_PROVIDER,
            "embedding_model": CLOUDFLARE_MODEL,
            "vector_dimension": VECTOR_DIMENSION,
            "vector_name": QDRANT_VECTOR_NAME,
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
        }
        if tuple(payload) != base.REQUIRED_PAYLOAD_FIELDS:
            raise IntegrityError("M23-INGEST-165 payload field ordering drift")
        content_hash = base.canonical_sha256(
            {
                "point_id": point_id,
                "payload": payload,
                "vector_sha256": vector_row_sha,
            }
        )
        point_summaries.append(
            {
                "row": row,
                "section_id": document["section_id"],
                "point_id": point_id,
                "vector_byte_offset": offset,
                "vector_byte_length": VECTOR_DIMENSION * 4,
                "vector_sha256": vector_row_sha,
                "content_hash_sha256": content_hash,
                "source_membership": base.SOURCE_MEMBERSHIP,
                "canonical_knowledge": False,
                "candidate_release_eligible": False,
                "production_authority": False,
            }
        )
        qdrant_points.append(
            {
                "id": point_id,
                "vector": {QDRANT_VECTOR_NAME: list(vector)},
                "payload": payload,
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": base.MANIFEST_SCHEMA,
        "milestone": "M23.6.2",
        "mode": "offline-dry-run",
        "builder_engine_commit_sha": builder_engine_sha,
        "source_evidence": {
            "archive_root": root,
            "evidence_zip_sha256": evidence_sha,
            "receipt_files": files,
            "benchmark_suite_sha256": suite_sha,
            "document_vectors_filename": "pilot-document-vectors.f32",
            "document_vectors_sha256": vector_sha,
            "document_vectors_byte_length": len(vector_bytes),
            "semantic_metadata_sha256": semantic_metadata_sha,
            "semantic_artifact_id": expected_semantic_artifact_id,
        },
        "authority_contract_sha256": authority["contract_sha256"],
        "release": release,
        "source_membership": {
            "membership": base.SOURCE_MEMBERSHIP,
            "point_count": base.EXPECTED_DOCUMENT_COUNT,
            "all_points_noncanonical": True,
            "candidate_release_eligible": False,
            "production_authority": False,
            "full_rebuild_required_after_source_adoption": True,
        },
        "qdrant": {
            "collection": base.QDRANT_COLLECTION,
            "blocked_collection": base.BLOCKED_COLLECTION,
            "vector_name": QDRANT_VECTOR_NAME,
            "dimension": VECTOR_DIMENSION,
            "distance": QDRANT_DISTANCE,
            "point_count": base.EXPECTED_DOCUMENT_COUNT,
            "payload_schema_version": base.PAYLOAD_SCHEMA,
            "payload_fields": list(base.REQUIRED_PAYLOAD_FIELDS),
            "write_authorized": False,
        },
        "content_hash_policy": {
            "missing": "insert",
            "equal": "skip",
            "different": "replace",
            "network_read_required_by_m23_6_2": False,
        },
        "points": point_summaries,
        "authority": {
            "network_calls": False,
            "cloudflare_calls": False,
            "qdrant_reads": False,
            "qdrant_writes": False,
            "r2_mutation": False,
            "pointer_mutation": False,
            "source_mutation": False,
            "production_traffic_change": False,
            "production_authority": False,
        },
    }
    manifest["manifest_sha256"] = base.canonical_sha256(manifest)
    points_document = {
        "schema_version": base.POINTS_SCHEMA,
        "manifest_sha256": manifest["manifest_sha256"],
        "collection": base.QDRANT_COLLECTION,
        "vector_name": QDRANT_VECTOR_NAME,
        "point_count": base.EXPECTED_DOCUMENT_COUNT,
        "points": qdrant_points,
        "qdrant_write_authorized": False,
        "production_authority": False,
    }
    return {"manifest": manifest, "points": points_document}


write_dry_run = base.write_dry_run
decide_content_action = base.decide_content_action
