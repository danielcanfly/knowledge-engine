from __future__ import annotations

import copy
import hashlib
import math
import struct
import zipfile
from pathlib import Path

import pytest

from src.knowledge_engine.errors import IntegrityError
from src.knowledge_engine.m23_qdrant_pilot_ingestion import (
    BLOCKED_COLLECTION,
    EXPECTED_DOCUMENT_COUNT,
    EXPECTED_VECTOR_BYTES,
    QDRANT_COLLECTION,
    REQUIRED_PAYLOAD_FIELDS,
    SOURCE_MEMBERSHIP,
    build_dry_run,
    bytes_sha256,
    canonical_bytes,
    canonical_sha256,
    decide_content_action,
    load_authority_contract,
    write_dry_run,
)

SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
ENGINE_SHA = "913c8cbb19dd6c7b89b753aecd61afd943e373fc"
SEMANTIC_ID = "semantic-" + "7" * 64


def _authority_contract() -> dict:
    value = {
        "schema_version": "knowledge-engine-m23-pilot-authority/v1",
        "milestone": "M23.6.1",
        "identities": {
            "engine_commit_sha": "e6557ff8b3f6eb8ce7cd206df5bf0a4794ae34fb",
            "source_commit_sha": SOURCE_SHA,
            "foundation_commit_sha": FOUNDATION_SHA,
            "m23_5_evidence_zip_sha256": "1" * 64,
            "m23_5_semantic_artifact_id": SEMANTIC_ID,
        },
        "qdrant": {
            "blocked_collection": BLOCKED_COLLECTION,
            "collection": QDRANT_COLLECTION,
            "delete_authorized": False,
            "dimension": 1024,
            "distance": "Cosine",
            "embedding_model": "@cf/baai/bge-m3",
            "embedding_provider": "cloudflare-workers-ai",
            "first_write_authorized": False,
            "first_write_requires_empty_collection": True,
            "payload_fields": list(REQUIRED_PAYLOAD_FIELDS),
            "vector_name": "default",
            "write_default": "deny",
        },
        "source_adoption": {
            "adoption_invalidates_derived_identity": True,
            "candidate_requires_canonical_rebuild": True,
            "canonical_source_sha": SOURCE_SHA,
            "lane": SOURCE_MEMBERSHIP,
            "pending_candidate_release_eligible": False,
            "pending_canonical_knowledge": False,
            "pending_production_authority": False,
            "pending_proposal_point_count": EXPECTED_DOCUMENT_COUNT,
            "source_merge_authorized": False,
            "source_pr_head_sha": "d" * 40,
            "source_pr_number": 19,
            "source_pr_state": "draft-open-unmerged",
        },
        "authority": {
            "credential_rotation": False,
            "graph_neural_retrieval": False,
            "permanent_ledger_mutation": False,
            "physical_delete": False,
            "pointer_mutation": False,
            "production_mutation_dispatched": False,
            "production_traffic_change": False,
            "public_graph_explorer": False,
            "qdrant_write": False,
            "r2_mutation": False,
            "source_mutation": False,
            "source_pr_19_merge": False,
        },
    }
    value["contract_sha256"] = canonical_sha256(value)
    return value


def _documents() -> list[dict]:
    items = []
    for row in range(EXPECTED_DOCUMENT_COUNT):
        text = f"frozen section text {row:03d}"
        section_id = f"blog/en/harness-{row // 4:03d}/chunk-{row % 4:03d}"
        items.append(
            {
                "section_id": section_id,
                "concept_id": f"concept-{row // 4:03d}",
                "language": "en" if row % 2 == 0 else "zh-TW",
                "title": f"Frozen section {row:03d}",
                "text": text,
                "source_path": f"/blog/harness-{row // 4:03d}/",
                "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "audience": "internal" if row % 17 == 0 else "public",
            }
        )
    return items


def _vector_bytes() -> bytes:
    values: list[float] = []
    for row in range(EXPECTED_DOCUMENT_COUNT):
        vector = [0.0] * 1024
        vector[row] = 1.0
        assert math.isclose(math.sqrt(sum(item * item for item in vector)), 1.0)
        values.extend(vector)
    data = struct.pack(f"<{len(values)}f", *values)
    assert len(data) == EXPECTED_VECTOR_BYTES
    return data


def _semantic_metadata(suite: dict, vectors: bytes, *, swap_rows: bool = False) -> dict:
    documents = [
        {
            "row": row,
            "concept_id": document["concept_id"],
            "section_id": document["section_id"],
            "language": document["language"],
            "audience": document["audience"],
            "source_path": document["source_path"],
            "source_sha256": document["source_sha256"],
        }
        for row, document in enumerate(suite["documents"])
    ]
    if swap_rows:
        documents[0], documents[1] = documents[1], documents[0]
    value = {
        "schema_version": "knowledge-engine-semantic/v2",
        "artifact_id": SEMANTIC_ID,
        "immutable": True,
        "read_only": True,
        "production_authority": False,
        "identities": {
            "builder_engine_commit_sha": "b" * 40,
            "provider_contract_engine_commit_sha": "c" * 40,
            "source_commit_sha": SOURCE_SHA,
            "foundation_commit_sha": FOUNDATION_SHA,
        },
        "provider_contract_sha256": "2" * 64,
        "benchmark_suite_sha256": canonical_sha256(suite),
        "model": {
            "provider": "cloudflare-workers-ai",
            "provider_implementation": "Cloudflare Workers AI REST API",
            "model_id": "@cf/baai/bge-m3",
            "model_revision": "cloudflare-managed",
            "tokenizer_id": "BAAI/bge-m3",
            "tokenizer_revision": "cloudflare-managed",
            "dimension": 1024,
            "dtype": "float32",
            "endianness": "little",
            "normalized": True,
            "pooling": "provider-native",
            "input_template": "{text}",
            "query_template": "{text}",
            "maximum_input_length": 60000,
            "truncation": "error",
            "unicode_normalization": "NFKC",
        },
        "vectors": {
            "filename": "semantic-vectors.f32",
            "sha256": bytes_sha256(vectors),
            "byte_length": len(vectors),
            "row_count": EXPECTED_DOCUMENT_COUNT,
            "dimension": 1024,
            "dtype": "float32",
            "endianness": "little",
            "normalized": True,
        },
        "documents": documents,
    }
    value["metadata_sha256"] = canonical_sha256(value)
    return value


def _make_evidence(path: Path, *, swap_semantic_rows: bool = False) -> str:
    suite = {
        "schema_version": "knowledge-os-bilingual-blog-benchmark/v1",
        "suite_id": "synthetic-m23-6-2",
        "suite_revision": "1",
        "identities": {
            "engine_baseline_sha": "c" * 40,
            "source_commit_sha": SOURCE_SHA,
            "foundation_commit_sha": FOUNDATION_SHA,
        },
        "documents": _documents(),
        "queries": [],
        "read_only": True,
        "production_authority": False,
    }
    vectors = _vector_bytes()
    semantic = _semantic_metadata(suite, vectors, swap_rows=swap_semantic_rows)
    files = {
        "benchmark-suite.json": canonical_bytes(suite),
        "pilot-document-vectors.f32": vectors,
        "semantic-artifact/semantic-metadata.json": canonical_bytes(semantic),
        "semantic-artifact/semantic-vectors.f32": vectors,
    }
    receipt = {
        "schema_version": "synthetic-m23-receipt/v1",
        "files": {
            name: {"sha256": bytes_sha256(data), "bytes": len(data)}
            for name, data in sorted(files.items())
        },
        "qdrant_write": False,
        "r2_mutation": False,
        "pointer_mutation": False,
        "source_write": False,
        "traffic_change": False,
        "production_authority": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            archive.writestr(f"evidence/{name}", data)
        archive.writestr("evidence/run-receipt.json", canonical_bytes(receipt))
    return bytes_sha256(path.read_bytes())


def _inputs(tmp_path: Path, *, swap_semantic_rows: bool = False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    authority = _authority_contract()
    authority_path = tmp_path / "authority.json"
    authority_path.write_bytes(canonical_bytes(authority))
    evidence_path = tmp_path / "evidence.zip"
    evidence_sha = _make_evidence(evidence_path, swap_semantic_rows=swap_semantic_rows)
    return authority, authority_path, evidence_path, evidence_sha


def _build(tmp_path: Path):
    authority, authority_path, evidence_path, evidence_sha = _inputs(tmp_path)
    return build_dry_run(
        evidence_zip=evidence_path,
        authority_contract_path=authority_path,
        builder_engine_sha=ENGINE_SHA,
        expected_evidence_sha256=evidence_sha,
        expected_semantic_artifact_id=SEMANTIC_ID,
        expected_authority_contract_sha256=authority["contract_sha256"],
    )


def test_builds_exact_107_point_evaluation_manifest(tmp_path: Path):
    result = _build(tmp_path)
    manifest = result["manifest"]
    points = result["points"]["points"]
    assert manifest["qdrant"]["point_count"] == 107
    assert len(points) == 107
    assert len({point["id"] for point in points}) == 107
    assert manifest["qdrant"]["collection"] == QDRANT_COLLECTION
    assert manifest["qdrant"]["vector_name"] == "default"
    assert manifest["release"]["release_id"].startswith("m23pilot-")
    assert all(
        point["payload"]["source_membership"] == SOURCE_MEMBERSHIP
        and point["payload"]["canonical_knowledge"] is False
        and point["payload"]["candidate_release_eligible"] is False
        and point["payload"]["production_authority"] is False
        for point in points
    )


def test_replay_is_byte_and_digest_stable(tmp_path: Path):
    result_a = _build(tmp_path / "a")
    result_b = _build(tmp_path / "b")
    output_a = tmp_path / "out-a"
    output_b = tmp_path / "out-b"
    receipt_a = write_dry_run(output_a, result_a)
    receipt_b = write_dry_run(output_b, result_b)
    assert receipt_a == receipt_b
    for name in (
        "ingestion-manifest.json",
        "qdrant-points.json",
        "dry-run-receipt.json",
    ):
        assert (output_a / name).read_bytes() == (output_b / name).read_bytes()


def test_content_hash_skip_logic_is_closed_and_deterministic():
    planned = "a" * 64
    assert decide_content_action(None, planned) == "insert"
    assert decide_content_action(planned, planned) == "skip"
    assert decide_content_action("b" * 64, planned) == "replace"
    with pytest.raises(IntegrityError, match="SHA-256"):
        decide_content_action("not-a-digest", planned)


def test_tampered_evidence_digest_fails_closed(tmp_path: Path):
    authority, authority_path, evidence_path, _ = _inputs(tmp_path)
    with pytest.raises(IntegrityError, match="evidence ZIP digest mismatch"):
        build_dry_run(
            evidence_zip=evidence_path,
            authority_contract_path=authority_path,
            builder_engine_sha=ENGINE_SHA,
            expected_evidence_sha256="0" * 64,
            expected_semantic_artifact_id=SEMANTIC_ID,
            expected_authority_contract_sha256=authority["contract_sha256"],
        )


def test_semantic_row_order_drift_fails_closed(tmp_path: Path):
    authority, authority_path, evidence_path, evidence_sha = _inputs(
        tmp_path, swap_semantic_rows=True
    )
    with pytest.raises(IntegrityError, match="semantic row order mismatch"):
        build_dry_run(
            evidence_zip=evidence_path,
            authority_contract_path=authority_path,
            builder_engine_sha=ENGINE_SHA,
            expected_evidence_sha256=evidence_sha,
            expected_semantic_artifact_id=SEMANTIC_ID,
            expected_authority_contract_sha256=authority["contract_sha256"],
        )


def test_authority_collection_or_write_drift_fails_closed(tmp_path: Path):
    authority = _authority_contract()
    authority["qdrant"]["collection"] = BLOCKED_COLLECTION
    authority.pop("contract_sha256")
    authority["contract_sha256"] = canonical_sha256(authority)
    path = tmp_path / "authority.json"
    path.write_bytes(canonical_bytes(authority))
    with pytest.raises(IntegrityError, match="wrong Qdrant collection"):
        load_authority_contract(path, expected_sha256=authority["contract_sha256"])

    authority = _authority_contract()
    authority["qdrant"]["first_write_authorized"] = True
    authority.pop("contract_sha256")
    authority["contract_sha256"] = canonical_sha256(authority)
    path.write_bytes(canonical_bytes(authority))
    with pytest.raises(IntegrityError, match="deny writes"):
        load_authority_contract(path, expected_sha256=authority["contract_sha256"])


def test_payload_fields_are_exact_and_content_hashes_change_with_content(tmp_path: Path):
    result = _build(tmp_path)
    points = result["points"]["points"]
    summaries = result["manifest"]["points"]
    assert tuple(points[0]["payload"]) == REQUIRED_PAYLOAD_FIELDS
    assert summaries[0]["content_hash_sha256"] != summaries[1]["content_hash_sha256"]
    assert len({item["vector_sha256"] for item in summaries}) == 107


def test_output_is_immutable(tmp_path: Path):
    result = _build(tmp_path / "input")
    output = tmp_path / "output"
    write_dry_run(output, result)
    with pytest.raises(IntegrityError, match="immutable output already exists"):
        write_dry_run(output, result)


def test_manifest_self_digest_detects_tampering(tmp_path: Path):
    result = _build(tmp_path)
    manifest = copy.deepcopy(result["manifest"])
    original = manifest.pop("manifest_sha256")
    assert canonical_sha256(manifest) == original
    manifest["qdrant"]["collection"] = BLOCKED_COLLECTION
    assert canonical_sha256(manifest) != original
