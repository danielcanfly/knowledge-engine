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


def test_final_recovery_builds_verified_direct_propositions() -> None:
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
    candidate = patch._candidate(
        legacy=legacy,
        runtime=runtime,
        question=question,
        evidence=evidence,
        requirements=[],
    )
    assert candidate is not None
    assert "e1" not in candidate["answer_text"]
    assert "ordering_boundary" not in {
        facet_id for claim in candidate["claims"] for facet_id in claim["facet_ids"]
    }
    verified = legacy._verify_multi_evidence_provider_output(
        trace_id="trace-final-recovery",
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_text=json.dumps(candidate),
    )
    assert verified["terminal_status"] == "verified_answer_ready_candidate"
    assert verified["missing_facets"] == []


def test_final_recovery_telemetry_preserves_hard_stop() -> None:
    evidence = [_evidence("ev1", "A supported passage exists.")]
    telemetry = patch._telemetry(
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
