from __future__ import annotations

import hashlib
import inspect
import math

from knowledge_engine import (
    m23_7_r3_5_rank_quality_calibration as base_r35,
)
from knowledge_engine import (
    m23_7_r3_5_rank_quality_calibration_runtime as r35,
)


def _unit(values: dict[int, float]) -> list[float]:
    vector = [0.0] * r35.r34.VECTOR_DIMENSION
    for index, value in values.items():
        vector[index] = value
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


def _candidate(*, hard_case: bool = False) -> tuple[dict[str, object], list[list[float]]]:
    points: list[dict[str, object]] = []
    documents: list[dict[str, object]] = []
    for index in range(r35.r34.EXPECTED_POINT_COUNT):
        section_id = f"docs/topic-{index:03d}/chunk-{index:03d}"
        token = f"quasar{index}"
        points.append(
            {
                "payload": {
                    "section_id": section_id,
                    "payload_schema_version": r35.r34.PAYLOAD_SCHEMA_V2,
                },
                "vector": {"default": _unit({index: 1.0})},
            }
        )
        documents.append(
            {
                "section_id": section_id,
                "section_title": f"{token} decision boundary",
                "concept_id": f"concept-{token}-orbit{index}",
                "source_path": f"docs/topic-{index:03d}.md",
                "language": "en",
                "text": f"{token} orbit{index} policy{index} " * 3,
            }
        )

    probes: list[dict[str, object]] = []
    query_vectors: list[list[float]] = []
    for index in range(r35.r34.SAMPLE_CAP):
        target = points[index]["payload"]["section_id"]
        variants = []
        for variant_index in range(r35.r34.VARIANTS_PER_PROBE):
            text = (
                f"Find quasar{index} orbit{index} policy{index} "
                f"variant{variant_index}"
            )
            variants.append(
                {
                    "variant_id": f"probe-{index}-v{variant_index}",
                    "query_text": text,
                    "query_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            )
            if hard_case and index == 1:
                start = 20 + variant_index * 20
                values = {
                    row: 0.7 - offset * 0.02
                    for offset, row in enumerate(range(start, start + 12))
                }
                values[index] = 0.35
                query_vectors.append(_unit(values))
            else:
                distractors = [8 + index * 10 + offset for offset in range(9)]
                query_vectors.append(
                    _unit(
                        {
                            index: 0.95,
                            **{
                                row: 0.1 - offset * 0.005
                                for offset, row in enumerate(distractors)
                            },
                        }
                    )
                )
        probes.append(
            {
                "probe_id": f"r1-probe-{index + 1:02d}",
                "offline_case_id": f"m23q-{index + 1:02d}",
                "query_class": "terminology" if index in {1, 5} else "direct-fact",
                "target_section_id": target,
                "expected_relevant_ids": [target],
                "variants": variants,
            }
        )

    candidate = {
        "points": points,
        "probe_plan": probes,
        "lexical_documents": documents,
        "lexical_bindings": [],
        "specificity": {
            point["payload"]["section_id"]: 0.8 for point in points
        },
        "corpus_centrality": {
            point["payload"]["section_id"]: 0.2 for point in points
        },
        "evidence": {
            "evidence_zip_sha256": r35.r34.EXPECTED_EVIDENCE_SHA256,
        },
        "candidate_artifact_sha256": "a" * 64,
    }
    return candidate, query_vectors


def test_contract_freezes_thresholds_and_target_unaware_ranker() -> None:
    contract = r35.canonical_contract()
    assert contract["implementation_issue"] == 502
    assert contract["repair"]["target_aware_reranking"] is False
    assert contract["repair"]["query_variants_changed"] is False
    assert contract["thresholds"]["min_recall_at_5"] == 0.82
    assert contract["thresholds"]["min_mrr_at_10"] == 0.68
    assert contract["thresholds"]["min_ndcg_at_10"] == 0.72
    assert contract["thresholds"]["thresholds_changed"] is False
    assert contract["authority"]["qdrant_read_authorized"] is False
    assert contract["authority"]["qdrant_write_authorized"] is False
    source = inspect.getsource(r35.calibrated_hybrid_ranking)
    for forbidden in contract["repair"]["ranker_forbidden_inputs"]:
        assert forbidden not in source


def test_perfect_vectors_pass_all_gates() -> None:
    candidate, query_vectors = _candidate()
    report = r35.evaluate_calibration_candidate(candidate, query_vectors)
    assert all(report["gates"].values()), report["gates"]
    assert report["status"] == "pass_rank_quality_calibration"
    assert report["metrics"] == {
        "recall_at_5": 1.0,
        "mrr_at_10": 1.0,
        "ndcg_at_10": 1.0,
    }
    assert report["gates"]["target_unaware_score_path"] is True
    assert report["maximum_top10_hub_frequency"] <= 6
    assert report["external_calls"]["qdrant_reads"] == 0
    assert report["external_calls"]["qdrant_writes"] == 0


def test_runtime_compatibility_restores_base_state() -> None:
    old_bm25 = base_r35._bm25_ranking
    old_ranker = base_r35.calibrated_hybrid_ranking
    candidate, query_vectors = _candidate()
    r35.evaluate_calibration_candidate(candidate, query_vectors)
    assert base_r35._bm25_ranking is old_bm25
    assert base_r35.calibrated_hybrid_ranking is old_ranker


def test_query_visible_lexical_fusion_recovers_dense_hard_case() -> None:
    candidate, query_vectors = _candidate(hard_case=True)
    report = r35.evaluate_calibration_candidate(candidate, query_vectors)
    hard = next(case for case in report["cases"] if case["offline_case_id"] == "m23q-02")
    assert hard["calibrated_rank"] <= 5
    assert hard["calibration"]["target_aware_inputs_accepted"] is False
    assert report["metrics"]["recall_at_5"] >= 0.875
    assert report["metrics"]["mrr_at_10"] >= 0.68
    assert report["metrics"]["ndcg_at_10"] >= 0.72


def test_wrong_vectors_reject_calibration() -> None:
    candidate, _ = _candidate()
    wrong = [
        _unit({106: 1.0})
        for _ in range(r35.r34.TOTAL_QUERY_VARIANTS)
    ]
    for document in candidate["lexical_documents"]:
        document["section_title"] = "generic common title"
        document["concept_id"] = "generic-common-concept"
        document["text"] = "generic common content"
    report = r35.evaluate_calibration_candidate(candidate, wrong)
    assert report["status"] == "rejected_rank_quality_calibration"
    assert report["gates"]["recall_at_5"] is False
    assert report["exit"]["next_gate"] == "repair_iteration_required"


def test_redacted_candidate_removes_queries_and_document_text() -> None:
    candidate, _ = _candidate()
    unsigned = {
        key: value
        for key, value in candidate.items()
        if key not in {"candidate_artifact_sha256", "lexical_documents", "probe_plan"}
    }
    unsigned["probe_plan"] = r35._redacted_probe_plan(candidate["probe_plan"])
    candidate["candidate_artifact_sha256"] = r35.canonical_sha256(unsigned)
    redacted = r35.redacted_candidate_artifact(candidate)
    assert "lexical_documents" not in redacted
    assert all(
        "query_text" not in variant
        for probe in redacted["probe_plan"]
        for variant in probe["variants"]
    )
