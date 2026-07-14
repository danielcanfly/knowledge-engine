from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .m23_benchmark_correction import (
    DECISION_SCHEMA,
    VECTOR_DIMENSION,
    canonical_sha256,
)


def build_decision(
    *,
    source_evidence_sha256: str,
    source_semantic_artifact_id: str,
    corrected_gold_sha256: str,
    methods: Mapping[str, Mapping[str, Any]],
    calibration: Mapping[str, Any],
    held_out: Mapping[str, Any],
) -> dict[str, Any]:
    vector = methods["vector"]
    vector_summary = {
        "evaluation_unit": vector["evaluation_unit"],
        "k": vector["k"],
        "query_count": vector["query_count"],
        "answered_query_count": vector["answered_query_count"],
        "recall_at_3": vector["recall_at_3"],
        "mean_reciprocal_rank": vector["mean_reciprocal_rank"],
        "ndcg_at_3": vector["ndcg_at_3"],
        "cross_language_recall_at_3": vector[
            "cross_language_recall_at_3"
        ],
        "not_found_accuracy": vector["not_found_accuracy"],
    }
    provider_selection_pass = (
        vector["recall_at_3"] >= 0.70
        and vector["mean_reciprocal_rank"] >= 0.95
        and vector["cross_language_recall_at_3"] >= 0.90
        and vector["not_found_accuracy"] == 1.0
        and held_out["accuracy"] == 1.0
        and calibration["separation_margin"] > 0.0
    )
    abstention_promotion_pass = (
        held_out["held_out_negative_count"] >= 3
        and held_out["negative_threshold_clearance"] >= 0.02
        and held_out["separation_margin"] >= 0.05
    )
    decision = {
        "schema_version": DECISION_SCHEMA,
        "milestone": "M23.5",
        "embedding_provider": "cloudflare-workers-ai",
        "embedding_model": "@cf/baai/bge-m3",
        "vector_dimension": VECTOR_DIMENSION,
        "source_evidence_sha256": source_evidence_sha256,
        "source_semantic_artifact_id": source_semantic_artifact_id,
        "corrected_gold_sha256": corrected_gold_sha256,
        "decision": (
            "select_for_non_production_pilot"
            if provider_selection_pass
            else "do_not_select"
        ),
        "provider_selection_pass": provider_selection_pass,
        "abstention_promotion_pass": abstention_promotion_pass,
        "preferred_retrieval_candidate": "vector-first",
        "simple_rrf_selected": False,
        "retrieval_default": "lexical",
        "qdrant_pilot_write_authorized": False,
        "candidate_release_eligible": False,
        "production_authority": False,
        "gates": {
            "article_recall_at_3_minimum": 0.70,
            "article_mrr_minimum": 0.95,
            "cross_language_recall_at_3_minimum": 0.90,
            "not_found_accuracy_required": 1.0,
            "held_out_negative_count_for_promotion": 3,
            "held_out_negative_threshold_clearance_minimum": 0.02,
            "held_out_separation_margin_minimum": 0.05,
        },
        "observed": {
            "vector": vector_summary,
            "threshold_calibration": dict(calibration),
            "held_out_abstention": dict(held_out),
        },
        "authority": {
            "canonical_knowledge": False,
            "source_write": False,
            "r2_mutation": False,
            "pointer_mutation": False,
            "traffic_change": False,
            "qdrant_write": False,
            "production_authority": False,
        },
        "required_follow_up": [
            "retain RETRIEVAL_MODE=lexical",
            "collect at least three independent semantic held-out negatives",
            "require at least 0.02 negative threshold clearance and 0.05 held-out separation",
            "use named Qdrant vector default and collection preflight before any pilot upsert",
            "require explicit operator authorization for the first Qdrant pilot write",
        ],
    }
    decision["decision_sha256"] = canonical_sha256(decision)
    return decision
