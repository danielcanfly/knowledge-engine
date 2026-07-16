from __future__ import annotations

import hashlib
import json
import math
import struct
import zipfile
from pathlib import Path

import pytest
from knowledge_engine import m23_7_r3_3_offline_rebuild_evaluation as r33
from knowledge_engine.errors import IntegrityError


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _documents() -> list[dict[str, object]]:
    titles = (
        "Canonical run authority and acceptance boundaries",
        "Request boundary admission control and rejection",
        "Agent loop stopping policy and retry budget",
        "Evidence provenance verification and source binding",
        "Durable thread state and checkpoint recovery",
        "Tool calling proposal boundary and approval",
        "Graph explorer read only access boundary",
        "Lexical rollback authority and recovery policy",
    )
    output: list[dict[str, object]] = []
    for row in range(r33.EXPECTED_POINT_COUNT):
        title = titles[row % len(titles)] + f" item {row:03d}"
        text = f"frozen semantic text {row:03d}"
        output.append(
            {
                "section_id": f"docs/part-{row:03d}/chunk-{row:03d}",
                "concept_id": title.lower().replace(" ", "-"),
                "language": "en" if row % 2 == 0 else "zh-TW",
                "title": title,
                "text": text,
                "source_path": f"docs/part-{row:03d}.md",
                "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "audience": "public",
            }
        )
    return output


def _vectors() -> tuple[list[list[float]], bytes]:
    vectors: list[list[float]] = []
    flat: list[float] = []
    for row in range(r33.EXPECTED_POINT_COUNT):
        vector = [0.0] * r33.VECTOR_DIMENSION
        vector[row] = 1.0
        assert math.isclose(math.sqrt(sum(item * item for item in vector)), 1.0)
        vectors.append(vector)
        flat.extend(vector)
    return vectors, struct.pack(f"<{len(flat)}f", *flat)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o600 << 16
    return info


def _evidence(path: Path) -> tuple[str, list[list[float]]]:
    documents = _documents()
    vectors, vector_bytes = _vectors()
    suite = {
        "schema_version": "knowledge-os-bilingual-blog-benchmark/v1",
        "suite_id": "r3-3-synthetic",
        "suite_revision": "1",
        "identities": {
            "engine_baseline_sha": "a" * 40,
            "source_commit_sha": "b" * 40,
            "foundation_commit_sha": "c" * 40,
        },
        "documents": documents,
        "queries": [],
        "read_only": True,
        "production_authority": False,
    }
    semantic_documents = [
        {
            "row": row,
            "concept_id": document["concept_id"],
            "section_id": document["section_id"],
            "language": document["language"],
            "audience": document["audience"],
            "source_path": document["source_path"],
            "source_sha256": document["source_sha256"],
        }
        for row, document in enumerate(documents)
    ]
    metadata = {
        "schema_version": "knowledge-engine-semantic/v2",
        "artifact_id": r33.EXPECTED_SEMANTIC_ARTIFACT_ID,
        "immutable": True,
        "read_only": True,
        "production_authority": False,
        "identities": {
            "builder_engine_commit_sha": "d" * 40,
            "provider_contract_engine_commit_sha": "e" * 40,
            "source_commit_sha": "b" * 40,
            "foundation_commit_sha": "c" * 40,
        },
        "provider_contract_sha256": "f" * 64,
        "benchmark_suite_sha256": r33.canonical_sha256(suite),
        "model": {
            "provider": "cloudflare-workers-ai",
            "provider_implementation": "Cloudflare Workers AI REST API",
            "model_id": "@cf/baai/bge-m3",
            "model_revision": "cloudflare-managed",
            "tokenizer_id": "BAAI/bge-m3",
            "tokenizer_revision": "cloudflare-managed",
            "dimension": r33.VECTOR_DIMENSION,
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
            "sha256": hashlib.sha256(vector_bytes).hexdigest(),
            "byte_length": len(vector_bytes),
            "row_count": r33.EXPECTED_POINT_COUNT,
            "dimension": r33.VECTOR_DIMENSION,
            "dtype": "float32",
            "endianness": "little",
            "normalized": True,
        },
        "documents": semantic_documents,
    }
    metadata["metadata_sha256"] = r33.canonical_sha256(metadata)

    files = {
        "benchmark-suite.json": _canonical_bytes(suite),
        "pilot-document-vectors.f32": vector_bytes,
        "semantic-artifact/semantic-metadata.json": _canonical_bytes(metadata),
        "semantic-artifact/semantic-vectors.f32": vector_bytes,
    }
    receipt = {
        "schema_version": "synthetic-m23-receipt/v1",
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in sorted(files.items())
        },
        "qdrant_write": False,
        "r2_mutation": False,
        "pointer_mutation": False,
        "source_write": False,
        "traffic_change": False,
        "production_authority": False,
    }
    receipt["receipt_sha256"] = r33.canonical_sha256(receipt)

    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(_zip_info(f"evidence/{name}"), data)
        archive.writestr(
            _zip_info("evidence/run-receipt.json"),
            _canonical_bytes(receipt),
        )
    return hashlib.sha256(path.read_bytes()).hexdigest(), vectors


def _candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, list[list[float]]]:
    evidence = tmp_path / "evidence.zip"
    digest, vectors = _evidence(evidence)
    monkeypatch.setattr(r33, "EXPECTED_EVIDENCE_SHA256", digest)
    return r33.build_offline_candidate(evidence), vectors


def test_contract_preserves_frozen_thresholds_and_authority() -> None:
    contract = r33.canonical_contract()
    assert contract["implementation_issue"] == 487
    assert contract["thresholds"]["min_recall_at_5"] == 0.82
    assert contract["thresholds"]["min_mrr_at_10"] == 0.68
    assert contract["thresholds"]["min_ndcg_at_10"] == 0.72
    assert contract["thresholds"]["thresholds_changed"] is False
    assert contract["authority"]["qdrant_read_authorized"] is False
    assert contract["authority"]["qdrant_write_authorized"] is False
    assert contract["exit"]["live_acceptance_still_required"] is True


def test_rebuilds_107_payload_v2_points_and_unique_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, _ = _candidate(tmp_path, monkeypatch)
    assert candidate["point_count"] == 107
    assert len(candidate["points"]) == 107
    assert len(candidate["bindings"]) == 107
    assert len(candidate["probe_plan"]) == 8
    assert len({probe["query_text_sha256"] for probe in candidate["probe_plan"]}) == 8
    assert all(
        point["payload"]["payload_schema_version"] == r33.PAYLOAD_SCHEMA_V2
        and point["payload"]["section_title"]
        and point["payload"]["language"]
        and point["payload"]["production_authority"] is False
        for point in candidate["points"]
    )
    redacted = r33.redacted_candidate_artifact(candidate)
    assert all("query_text" not in probe for probe in redacted["probe_plan"])


def test_perfect_target_vectors_pass_offline_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, _ = _candidate(tmp_path, monkeypatch)
    by_section = {
        point["payload"]["section_id"]: point["vector"]["default"]
        for point in candidate["points"]
    }
    query_vectors = [
        by_section[probe["target_section_id"]] for probe in candidate["probe_plan"]
    ]
    report = r33.evaluate_offline_candidate(candidate, query_vectors)
    assert report["status"] == "pass_offline_rebuild_evaluation"
    assert report["metrics"] == {
        "recall_at_5": 1.0,
        "mrr_at_10": 1.0,
        "ndcg_at_10": 1.0,
    }
    assert report["exit"]["offline_ready_for_candidate_reingestion"] is True
    assert report["exit"]["live_acceptance_still_required"] is True
    assert report["authority"]["qdrant_read_dispatched"] is False


def test_wrong_vectors_reject_offline_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, _ = _candidate(tmp_path, monkeypatch)
    points = candidate["points"]
    wrong = [points[-1 - index]["vector"]["default"] for index in range(8)]
    report = r33.evaluate_offline_candidate(candidate, wrong)
    assert report["status"] == "rejected_offline_rebuild_evaluation"
    assert report["exit"]["offline_ready_for_candidate_reingestion"] is False
    assert report["exit"]["next_gate"] == "repair_iteration_required"


def test_tampered_evidence_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "evidence.zip"
    digest, _ = _evidence(evidence)
    monkeypatch.setattr(r33, "EXPECTED_EVIDENCE_SHA256", digest)
    evidence.write_bytes(evidence.read_bytes() + b"tamper")
    with pytest.raises(IntegrityError, match="evidence ZIP drifted"):
        r33.build_offline_candidate(evidence)
