from __future__ import annotations

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
    bytes_sha256,
    canonical_bytes,
    canonical_sha256,
)
from src.knowledge_engine.m23_qdrant_pilot_ingestion_real import build_dry_run


SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
ENGINE_SHA = "913c8cbb19dd6c7b89b753aecd61afd943e373fc"
SEMANTIC_ID = "semantic-" + "8" * 64
M20_SUITE_SHA = "6" * 64


def _authority_contract() -> dict:
    value = {
        "schema_version": "knowledge-engine-m23-pilot-authority/v1",
        "milestone": "M23.6.1",
        "identities": {
            "engine_commit_sha": "e" * 40,
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
    documents = []
    for row in range(EXPECTED_DOCUMENT_COUNT):
        text = f"real-shape frozen section {row:03d}"
        documents.append(
            {
                "section_id": f"pilot/article-{row // 5:03d}/chunk-{row % 5:03d}",
                "concept_id": f"concept-{row // 5:03d}",
                "language": "en" if row % 2 == 0 else "zh-TW",
                "title": f"Frozen section {row:03d}",
                "text": text,
                "source_path": f"M23.2/review-packets/article-{row // 5:03d}.md",
                "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "audience": "public",
            }
        )
    return documents


def _one_hot_vectors(*, shift: int) -> bytes:
    values: list[float] = []
    for row in range(EXPECTED_DOCUMENT_COUNT):
        vector = [0.0] * 1024
        vector[(row + shift) % 1024] = 1.0
        assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0)
        values.extend(vector)
    data = struct.pack(f"<{len(values)}f", *values)
    assert len(data) == EXPECTED_VECTOR_BYTES
    return data


def _semantic_metadata(suite: dict, vectors: bytes, *, drop_last: bool = False) -> dict:
    ordered = list(reversed(suite["documents"]))
    if drop_last:
        ordered[-1] = ordered[-2]
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
        for row, document in enumerate(ordered)
    ]
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
        "benchmark_suite_sha256": M20_SUITE_SHA,
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
            "input_template": "{title}\\n\\n{text}",
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


def _make_evidence(path: Path, *, drop_semantic_section: bool = False) -> str:
    suite = {
        "schema_version": "knowledge-os-bilingual-blog-benchmark/v1",
        "suite_id": "synthetic-real-evidence-shape",
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
    pilot_vectors = _one_hot_vectors(shift=0)
    semantic_vectors = _one_hot_vectors(shift=1)
    semantic = _semantic_metadata(
        suite,
        semantic_vectors,
        drop_last=drop_semantic_section,
    )
    benchmark_results = {
        "schema_version": "synthetic-m23-results/v1",
        "m20_results": {
            method: {"suite_sha256": M20_SUITE_SHA}
            for method in ("lexical", "vector", "rrf_hybrid_k60")
        },
    }
    files = {
        "benchmark-results.json": canonical_bytes(benchmark_results),
        "benchmark-suite.json": canonical_bytes(suite),
        "pilot-document-vectors.f32": pilot_vectors,
        "semantic-artifact/semantic-metadata.json": canonical_bytes(semantic),
        "semantic-artifact/semantic-vectors.f32": semantic_vectors,
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


def _inputs(tmp_path: Path, *, drop_semantic_section: bool = False):
    authority = _authority_contract()
    authority_path = tmp_path / "authority.json"
    authority_path.write_bytes(canonical_bytes(authority))
    evidence_path = tmp_path / "evidence.zip"
    evidence_sha = _make_evidence(
        evidence_path,
        drop_semantic_section=drop_semantic_section,
    )
    return authority, authority_path, evidence_path, evidence_sha


def test_accepts_real_evidence_shape_and_keeps_pilot_vectors(tmp_path: Path):
    authority, authority_path, evidence_path, evidence_sha = _inputs(tmp_path)
    result = build_dry_run(
        evidence_zip=evidence_path,
        authority_contract_path=authority_path,
        builder_engine_sha=ENGINE_SHA,
        expected_evidence_sha256=evidence_sha,
        expected_semantic_artifact_id=SEMANTIC_ID,
        expected_authority_contract_sha256=authority["contract_sha256"],
    )
    points = result["points"]["points"]
    assert len(points) == EXPECTED_DOCUMENT_COUNT
    assert points[0]["vector"]["default"][0] == 1.0
    assert points[0]["vector"]["default"][1] == 0.0
    assert result["manifest"]["authority"]["qdrant_writes"] is False


def test_rejects_semantic_section_set_drift(tmp_path: Path):
    authority, authority_path, evidence_path, evidence_sha = _inputs(
        tmp_path,
        drop_semantic_section=True,
    )
    with pytest.raises(IntegrityError, match="semantic section"):
        build_dry_run(
            evidence_zip=evidence_path,
            authority_contract_path=authority_path,
            builder_engine_sha=ENGINE_SHA,
            expected_evidence_sha256=evidence_sha,
            expected_semantic_artifact_id=SEMANTIC_ID,
            expected_authority_contract_sha256=authority["contract_sha256"],
        )
