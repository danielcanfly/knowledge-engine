from __future__ import annotations

import json
import math
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .m23_7_r3_2_semantic_payload_repair import (
    PAYLOAD_SCHEMA_V2,
    build_repaired_ingestion_preview,
    compile_repaired_probe_plan,
)
from .m23_qdrant_pilot_ingestion import (
    _archive_root,
    _read_json_bytes,
    _receipt_files,
    _unpack_vectors,
    _validate_receipt,
    _validate_semantic_metadata,
    _validate_suite,
    bytes_sha256,
    canonical_sha256,
    file_sha256,
)

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-3-offline-rebuild-evaluation/v1"
REPORT_SCHEMA_VERSION = f"{SCHEMA_VERSION.removesuffix('/v1')}-report/v1"
CANDIDATE_SCHEMA_VERSION = f"{SCHEMA_VERSION.removesuffix('/v1')}-candidate/v1"
ENTRY_ENGINE_SHA = "2511269cb46cefd24c15636480e9592cdfcf8964"
IMPLEMENTATION_ISSUE = 487
PARENT_ISSUE = 474
R3_2_REPAIR_CONTRACT_SHA256 = (
    "9ed7a5bea7ce85aed67bf6f263c8b06420e1c67bd7cac62f9368f0f48c29c33e"
)
EXPECTED_EVIDENCE_SHA256 = (
    "1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272"
)
EXPECTED_SEMANTIC_ARTIFACT_ID = (
    "semantic-35314911af0a514c9f0d64b7cfb1d6d0d2ec88cfa50317fa614e92f21f185f0d"
)
EXPECTED_POINT_COUNT = 107
VECTOR_DIMENSION = 1024
SAMPLE_CAP = 8
TOP_K = 10
MIN_RECALL_AT_5 = 0.82
MIN_MRR_AT_10 = 0.68
MIN_NDCG_AT_10 = 0.72
_NDCG = tuple(1.0 / math.log2(rank + 1) for rank in range(1, TOP_K + 1))


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7-R3.3-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), 101, f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    valid = isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    _require(valid, 102, f"{label} must be a list")
    return tuple(value)


def _vector(value: Any, label: str) -> list[float]:
    rows = _sequence(value, label)
    _require(len(rows) == VECTOR_DIMENSION, 103, f"{label} dimension drifted")
    numbers: list[float] = []
    for item in rows:
        _require(
            isinstance(item, int | float) and not isinstance(item, bool),
            104,
            f"{label} contains non-numeric data",
        )
        number = float(item)
        _require(math.isfinite(number), 105, f"{label} contains non-finite data")
        numbers.append(number)
    norm = math.sqrt(math.fsum(number * number for number in numbers))
    _require(abs(norm - 1.0) <= 1e-4, 106, f"{label} is not L2-normalized")
    return numbers


def canonical_contract() -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R3.3",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "r3_2_reconciliation_merge_sha": ENTRY_ENGINE_SHA,
            "r3_2_repair_contract_sha256": R3_2_REPAIR_CONTRACT_SHA256,
            "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
            "semantic_artifact_id": EXPECTED_SEMANTIC_ARTIFACT_ID,
        },
        "rebuild": {
            "mode": "offline-no-write",
            "point_count": EXPECTED_POINT_COUNT,
            "payload_schema": PAYLOAD_SCHEMA_V2,
            "sample_count": SAMPLE_CAP,
            "sample_order": "eligible-point-id-ascending-first-eight",
            "embedding_model": "@cf/baai/bge-m3",
            "embedding_model_changed": False,
            "query_prefix_changed": False,
            "local_full_corpus_cosine": True,
            "top_k": TOP_K,
        },
        "thresholds": {
            "min_recall_at_5": MIN_RECALL_AT_5,
            "min_mrr_at_10": MIN_MRR_AT_10,
            "min_ndcg_at_10": MIN_NDCG_AT_10,
            "thresholds_changed": False,
        },
        "privacy": {
            "raw_query_persisted": False,
            "raw_answer_persisted": False,
            "credentials_persisted": False,
            "account_id_persisted": False,
            "service_url_persisted": False,
        },
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "qdrant_read_authorized": False,
            "qdrant_write_authorized": False,
            "qdrant_delete_authorized": False,
            "r2_mutation_authorized": False,
            "pointer_mutation_authorized": False,
            "source_mutation_authorized": False,
            "promotion_eligibility_granted": False,
        },
        "exit": {
            "pass_authorizes": "separately_governed_candidate_qdrant_reingestion",
            "live_acceptance_still_required": True,
            "retrieval_quality_blocker_cleared": False,
        },
    }
    contract["contract_sha256"] = canonical_sha256(contract)
    return contract


def _load_inputs(path: Path) -> dict[str, Any]:
    _require(file_sha256(path) == EXPECTED_EVIDENCE_SHA256, 107, "evidence ZIP drifted")
    with zipfile.ZipFile(path) as archive:
        root = _archive_root(archive.namelist())
        receipt = _read_json_bytes(
            archive.read(f"{root}/run-receipt.json"),
            "run-receipt.json",
        )
        _validate_receipt(receipt)
        receipt_files = _receipt_files(archive, root, receipt)
        suite = _read_json_bytes(
            archive.read(f"{root}/benchmark-suite.json"),
            "benchmark-suite.json",
        )
        vector_bytes = archive.read(f"{root}/pilot-document-vectors.f32")
        semantic_bytes = archive.read(
            f"{root}/semantic-artifact/semantic-metadata.json"
        )
        semantic = _read_json_bytes(semantic_bytes, "semantic-metadata.json")
        semantic_vectors = archive.read(
            f"{root}/semantic-artifact/semantic-vectors.f32"
        )

    identities = _mapping(suite.get("identities"), "suite identities")
    authority = {
        "identities": {
            "source_commit_sha": identities.get("source_commit_sha"),
            "foundation_commit_sha": identities.get("foundation_commit_sha"),
        }
    }
    documents = _validate_suite(suite, authority)
    _require(len(documents) == EXPECTED_POINT_COUNT, 108, "document count drifted")
    _require(vector_bytes == semantic_vectors, 109, "semantic vector bytes drifted")
    vectors = _unpack_vectors(vector_bytes, EXPECTED_POINT_COUNT)
    _validate_semantic_metadata(
        semantic,
        semantic_vectors,
        suite,
        documents,
        expected_artifact_id=EXPECTED_SEMANTIC_ARTIFACT_ID,
    )
    return {
        "receipt_files": receipt_files,
        "suite_sha256": canonical_sha256(suite),
        "vector_sha256": bytes_sha256(vector_bytes),
        "semantic_metadata_sha256": bytes_sha256(semantic_bytes),
        "documents": documents,
        "vectors": vectors,
    }


def _release(inputs: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        "schema_version": "knowledge-engine-m23-7-r3-3-candidate-release/v1",
        "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
        "semantic_artifact_id": EXPECTED_SEMANTIC_ARTIFACT_ID,
        "benchmark_suite_sha256": inputs["suite_sha256"],
        "document_vectors_sha256": inputs["vector_sha256"],
        "repair_contract_sha256": R3_2_REPAIR_CONTRACT_SHA256,
        "payload_schema_version": PAYLOAD_SCHEMA_V2,
        "point_count": EXPECTED_POINT_COUNT,
        "embedding_model": "@cf/baai/bge-m3",
        "vector_dimension": VECTOR_DIMENSION,
        "vector_name": "default",
        "candidate_release_eligible": False,
        "production_authority": False,
    }
    digest = canonical_sha256(body)
    return {
        **body,
        "release_id": f"m23r33-{digest[:24]}",
        "release_manifest_sha256": digest,
    }


def _redacted_probes(probes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in probe.items() if key != "query_text"}
        for probe in probes
    ]


def build_offline_candidate(path: Path) -> dict[str, Any]:
    inputs = _load_inputs(path)
    preview = build_repaired_ingestion_preview(
        inputs["documents"],
        inputs["vectors"],
        release=_release(inputs),
        expected_point_count=EXPECTED_POINT_COUNT,
    )
    eligible = sorted(
        (
            point
            for point in preview["points"]
            if point["payload"]["source_membership"]
            == "evaluation-only-pending-proposal"
            and point["payload"]["canonical_knowledge"] is False
            and point["payload"]["candidate_release_eligible"] is False
            and point["payload"]["production_authority"] is False
        ),
        key=lambda point: point["id"],
    )
    _require(len(eligible) == EXPECTED_POINT_COUNT, 110, "eligible count drifted")
    samples = eligible[:SAMPLE_CAP]
    _require(
        all(sample["payload"]["audience"] == "public" for sample in samples),
        111,
        "bounded sample audience drifted",
    )
    probes = compile_repaired_probe_plan(samples)
    _require(
        len({probe["query_text_sha256"] for probe in probes}) == SAMPLE_CAP,
        112,
        "query identity collision",
    )
    candidate: dict[str, Any] = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "milestone": "M23.7-R3.3",
        "mode": "offline-no-write-candidate",
        "contract_sha256": canonical_contract()["contract_sha256"],
        "evidence": {
            "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
            "benchmark_suite_sha256": inputs["suite_sha256"],
            "document_vectors_sha256": inputs["vector_sha256"],
            "semantic_metadata_sha256": inputs["semantic_metadata_sha256"],
            "semantic_artifact_id": EXPECTED_SEMANTIC_ARTIFACT_ID,
        },
        "release": _release(inputs),
        "point_count": len(preview["points"]),
        "payload_schema_version": PAYLOAD_SCHEMA_V2,
        "preview_sha256": preview["preview_sha256"],
        "points": preview["points"],
        "bindings": preview["bindings"],
        "probe_plan": probes,
        "authority": preview["authority"],
    }
    unsigned = {**candidate, "probe_plan": _redacted_probes(probes)}
    candidate["candidate_artifact_sha256"] = canonical_sha256(unsigned)
    return candidate


def redacted_candidate_artifact(candidate: Mapping[str, Any]) -> dict[str, Any]:
    output = {**candidate, "probe_plan": _redacted_probes(candidate["probe_plan"])}
    expected = output.pop("candidate_artifact_sha256")
    _require(canonical_sha256(output) == expected, 113, "candidate digest drifted")
    return {**output, "candidate_artifact_sha256": expected}


def _rank(
    query: Sequence[float],
    corpus: Sequence[tuple[str, Sequence[float]]],
) -> list[tuple[float, str]]:
    return sorted(
        (
            (
                math.fsum(
                    left * right
                    for left, right in zip(query, vector, strict=True)
                ),
                section_id,
            )
            for section_id, vector in corpus
        ),
        key=lambda item: (-item[0], item[1]),
    )


def evaluate_offline_candidate(
    candidate: Mapping[str, Any],
    query_vectors: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    points = _sequence(candidate.get("points"), "candidate points")
    probes = _sequence(candidate.get("probe_plan"), "probe plan")
    _require(len(points) == EXPECTED_POINT_COUNT, 114, "candidate count drifted")
    _require(len(probes) == SAMPLE_CAP, 115, "probe count drifted")
    _require(len(query_vectors) == SAMPLE_CAP, 116, "query vector count drifted")
    corpus = [
        (
            point["payload"]["section_id"],
            _vector(point["vector"]["default"], f"point vector {index}"),
        )
        for index, point in enumerate(points)
    ]

    cases: list[dict[str, Any]] = []
    hubs: Counter[str] = Counter()
    for index, (probe, raw_vector) in enumerate(
        zip(probes, query_vectors, strict=True)
    ):
        ranked = _rank(_vector(raw_vector, f"query vector {index}"), corpus)
        ranked_ids = [section_id for _, section_id in ranked[:TOP_K]]
        hubs.update(ranked_ids)
        target = probe["target_section_id"]
        target_rank = next(
            rank
            for rank, (_, section_id) in enumerate(ranked, start=1)
            if section_id == target
        )
        target_score = ranked[target_rank - 1][0]
        reciprocal = 1.0 / target_rank if target_rank <= TOP_K else 0.0
        ndcg = _NDCG[target_rank - 1] if target_rank <= TOP_K else 0.0
        cases.append(
            {
                "probe_id": probe["probe_id"],
                "offline_case_id": probe["offline_case_id"],
                "query_class": probe["query_class"],
                "query_text_sha256": probe["query_text_sha256"],
                "query_digest": probe["query_digest"],
                "target_section_id": target,
                "ranked_section_ids": ranked_ids,
                "target_rank": target_rank,
                "target_in_top_5": target in ranked_ids[:5],
                "reciprocal_rank_at_10": round(reciprocal, 12),
                "ndcg_at_10": round(ndcg, 12),
                "target_cosine": round(target_score, 12),
                "top_cosine": round(ranked[0][0], 12),
                "target_margin_from_top": round(ranked[0][0] - target_score, 12),
                "raw_query_persisted": False,
                "raw_answer_persisted": False,
            }
        )

    metrics = {
        "recall_at_5": round(
            sum(case["target_in_top_5"] for case in cases) / SAMPLE_CAP,
            12,
        ),
        "mrr_at_10": round(
            math.fsum(case["reciprocal_rank_at_10"] for case in cases)
            / SAMPLE_CAP,
            12,
        ),
        "ndcg_at_10": round(
            math.fsum(case["ndcg_at_10"] for case in cases) / SAMPLE_CAP,
            12,
        ),
    }
    gates = {
        "evidence_identity": candidate["evidence"]["evidence_zip_sha256"]
        == EXPECTED_EVIDENCE_SHA256,
        "semantic_artifact_identity": candidate["evidence"]["semantic_artifact_id"]
        == EXPECTED_SEMANTIC_ARTIFACT_ID,
        "point_count": len(points) == EXPECTED_POINT_COUNT,
        "payload_schema_v2": all(
            point["payload"]["payload_schema_version"] == PAYLOAD_SCHEMA_V2
            for point in points
        ),
        "query_identity_unique": len(
            {case["query_text_sha256"] for case in cases}
        )
        == SAMPLE_CAP,
        "recall_at_5": metrics["recall_at_5"] >= MIN_RECALL_AT_5,
        "mrr_at_10": metrics["mrr_at_10"] >= MIN_MRR_AT_10,
        "ndcg_at_10": metrics["ndcg_at_10"] >= MIN_NDCG_AT_10,
        "qdrant_io_zero": True,
        "protected_mutations_zero": True,
    }
    passed = all(gates.values())
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "milestone": "M23.7-R3.3",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "status": (
            "pass_offline_rebuild_evaluation"
            if passed
            else "rejected_offline_rebuild_evaluation"
        ),
        "contract_sha256": canonical_contract()["contract_sha256"],
        "candidate_artifact_sha256": candidate["candidate_artifact_sha256"],
        "candidate_preview_sha256": candidate["preview_sha256"],
        "evidence": candidate["evidence"],
        "release": candidate["release"],
        "metrics": metrics,
        "gates": gates,
        "cases": cases,
        "hubness_top_10": [
            {"section_id": section_id, "frequency": frequency}
            for section_id, frequency in sorted(
                hubs.items(),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        ],
        "external_calls": {
            "workers_ai_bge_m3_batches": 1,
            "qdrant_reads": 0,
            "qdrant_writes": 0,
        },
        "privacy": canonical_contract()["privacy"],
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "qdrant_read_dispatched": False,
            "qdrant_write_dispatched": False,
            "qdrant_delete_dispatched": False,
            "r2_mutation_dispatched": False,
            "pointer_mutation_dispatched": False,
            "source_mutation_dispatched": False,
            "production_mutation_dispatched": False,
            "promotion_eligibility_granted": False,
        },
        "exit": {
            "offline_ready_for_candidate_reingestion": passed,
            "live_acceptance_still_required": True,
            "retrieval_quality_blocker_cleared": False,
            "next_gate": (
                "separately_governed_candidate_qdrant_reingestion"
                if passed
                else "repair_iteration_required"
            ),
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    return report
