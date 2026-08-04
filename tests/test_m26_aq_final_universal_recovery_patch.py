from __future__ import annotations

import json
from typing import Any

from knowledge_engine import m26_aq_final_universal_recovery_patch as patch
from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy
from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime
from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes


def _evidence(evidence_id: str, text: str, *, source: str = "source-a") -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "passage",
        "locator_id": f"loc-{evidence_id}",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "concept_id": f"concept-{evidence_id}",
        "section_id": f"section-{evidence_id}",
        "source_id": source,
        "source_identity": source,
        "channels": ["query_coverage"],
        "passage_text": text,
        "passage_text_sha256": sha256_bytes(text.encode()),
        "provenance_record_sha256": "b" * 64,
        "retrieval_metadata": {"coverage_terms": list(legacy._meaningful_terms(text))},
    }


def test_precise_intent_keeps_changed_direction_out_of_temporal_conflict() -> None:
    question = "A startup changes direction; is that learning or founder drift?"
    assert (
        patch._precise_intent(question, lambda _q: "temporal_conflict")
        == "direct_grounded_knowledge"
    )
    assert (
        patch._precise_intent(
            "Which source version is newer?",
            lambda _q: "temporal_conflict",
        )
        == "temporal_conflict"
    )


def test_precise_facets_remove_ordering_from_generic_prove_question() -> None:
    facets = patch._precise_direct_facets(
        "Why does demand not prove a viable business?",
        lambda _q: [
            {"facet_id": "non_entailment_boundary", "terms": ["prove", "demand"]},
            {"facet_id": "ordering_boundary", "terms": ["ordering", "sequence"]},
            {"facet_id": "direct_answer", "terms": ["business", "demand"]},
        ],
    )
    assert {item["facet_id"] for item in facets} == {
        "non_entailment_boundary",
        "direct_answer",
    }


def test_final_recovery_passes_runtime_and_legacy_into_original_v3_path() -> None:
    captured: dict[str, Any] = {}

    def original(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        captured.update(kwargs)
        return (
            {
                "status": "owner_only_cited_answer",
                "multi_evidence_verification": {},
                "reason_codes": [],
            },
            {"failures": []},
        )

    verification, closure = patch._synthesize_with_final_recovery(
        legacy=legacy,
        runtime=runtime,
        original=original,
        question="What should a production router inspect?",
        trace_id="trace-wrapper",
        intent_class="direct_grounded_knowledge",
        evidence=[],
        provider_client=object(),
        requirements=[],
        endpoint_proof={},
    )
    assert captured["legacy"] is legacy
    assert captured["runtime"] is runtime
    assert verification["status"] == "owner_only_cited_answer"
    assert closure["failures"] == []


def test_final_recovery_rejects_benchmark_shaped_generic_business_fallback() -> None:
    question = (
        "Why does evidence of demand still not prove that there is a viable business? "
        "Walk through value capture, economics, delivery and repeatability."
    )
    evidence = [
        _evidence(
            "ev1",
            (
                "Demand does not prove a viable business because value capture, economics, "
                "delivery, and repeatability must also work."
            ),
            source="source-a",
        ),
        _evidence(
            "ev2",
            (
                "A founder must test whether a customer problem can become durable delivery "
                "and repeatable economics."
            ),
            source="source-b",
        ),
    ]
    telemetry = patch._telemetry(
        question,
        {
            "status": "owner_only_safe_abstention",
            "reason_codes": ["SEMANTIC_CLOSURE_FAILED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
        },
        {"failures": ["SEMANTIC_CLOSURE_FAILED"]},
        evidence,
    )
    candidate = patch._candidate(
        legacy=legacy,
        runtime=runtime,
        question=question,
        evidence=evidence,
        requirements=[],
        telemetry=telemetry,
    )
    assert candidate is None
    assert telemetry["question_alignment_checked"] is True
    assert telemetry["question_alignment_passed"] is False
    assert telemetry["published_verified_answer"] is False


def test_final_recovery_rejects_irrelevant_true_evidence() -> None:
    question = (
        "When is pausing a venture rational survival rather than loss of conviction? "
        "Separate conviction, runway, timing, people, and resources."
    )
    evidence = [
        _evidence(
            "ev1",
            (
                "The build side shows how documents come in Station 1: data source. "
                "This is not an AI problem."
            ),
        )
    ]
    telemetry = patch._telemetry(
        question,
        {
            "status": "owner_only_safe_abstention",
            "reason_codes": ["SEMANTIC_CLOSURE_FAILED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
        },
        {"failures": ["SEMANTIC_CLOSURE_FAILED"]},
        evidence,
    )
    candidate = patch._candidate(
        legacy=legacy,
        runtime=runtime,
        question=question,
        evidence=evidence,
        requirements=[],
        telemetry=telemetry,
    )
    assert candidate is None
    assert telemetry["question_alignment_checked"] is True
    assert telemetry["question_alignment_passed"] is False
    assert "evidence_relevance_below_threshold" in telemetry[
        "question_alignment_failure_codes"
    ]
    assert telemetry["published_verified_answer"] is False


def test_final_recovery_rejects_best_of_bad_evidence() -> None:
    question = "Walk through checkpoints, LoRAs, VAE, and missing requirements."
    evidence = [
        _evidence("ev1", "SDXL is a balanced starting point for a 16GB Mac."),
        _evidence("ev2", "Flux is visually strong but heavier than SDXL."),
    ]
    assert (
        patch._candidate(
            legacy=legacy,
            runtime=runtime,
            question=question,
            evidence=evidence,
            requirements=[],
        )
        is None
    )


def test_final_recovery_rejects_partial_multifacet_support() -> None:
    question = (
        "Give a ComfyUI debugging order covering red nodes, OOM, checkpoints, "
        "LoRAs, VAE, CLIP/T5XXL, GGUF/FP8, missing requirements, and memory pressure."
    )
    evidence = [
        _evidence(
            "ev1",
            "If ComfyUI runs out of memory, reduce batch size and close other apps.",
        )
    ]
    telemetry = patch._telemetry(
        question,
        {
            "status": "owner_only_safe_abstention",
            "reason_codes": ["PROVIDER_ABSTAINED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
        },
        {"failures": ["PROVIDER_ABSTAINED"]},
        evidence,
    )
    candidate = patch._candidate(
        legacy=legacy,
        runtime=runtime,
        question=question,
        evidence=evidence,
        requirements=[],
        telemetry=telemetry,
    )
    assert candidate is None
    assert telemetry["missing_question_facets"]
    assert telemetry["question_alignment_passed"] is False


def test_post_render_alignment_rejects_removed_required_semantics() -> None:
    telemetry = {
        "required_question_facets": ["red nodes", "OOM", "checkpoints"],
    }
    result = patch._post_render_alignment(
        legacy,
        "Give a debugging order covering red nodes, OOM, and checkpoints.",
        {"answer_text": "ComfyUI can use GPU memory."},
        telemetry,
    )
    assert result["post_render_alignment_checked"] is True
    assert result["post_render_alignment_passed"] is False
    assert result["missing_question_facets"] == ["red nodes", "OOM", "checkpoints"]


def test_final_recovery_telemetry_preserves_external_hard_stop() -> None:
    evidence = [_evidence("ev1", "A supported passage exists.")]
    telemetry = patch._telemetry(
        "Give Toyota 2025 audited quarterly revenue.",
        {
            "status": "owner_only_safe_abstention",
            "reason_codes": ["PROVIDER_ABSTAINED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
        },
        {"failures": ["PROVIDER_ABSTAINED"]},
        evidence,
    )
    assert telemetry["universal_recovery_should_attempt"] is False
    assert telemetry["universal_recovery_hard_stop_codes"] == ["PROVIDER_ABSTAINED"]
    assert telemetry["unsupported_external_markers"] == ["2025", "Toyota"]
