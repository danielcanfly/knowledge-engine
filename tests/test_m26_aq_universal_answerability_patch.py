from __future__ import annotations

import json
from typing import Any

from knowledge_engine import m26_aq_universal_answerability_patch as patch
from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy
from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime
from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes


def _evidence(
    evidence_id: str,
    text: str,
    *,
    source: str = "source-a",
    channels: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "passage",
        "locator_id": f"loc-{evidence_id}",
        "release_id": "release-test",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "concept_id": f"concept-{evidence_id}",
        "section_id": f"section-{evidence_id}",
        "source_id": source,
        "source_identity": source,
        "title": "Evidence",
        "section_title": "Overview",
        "channels": channels or ["dense"],
        "passage_text": text,
        "passage_text_sha256": sha256_bytes(text.encode("utf-8")),
        "provenance_record_sha256": "b" * 64,
        "retrieved_at": "",
        "retrieval_metadata": {"query_overlap_score": 0.0},
    }


def _base_evidence() -> list[dict[str, Any]]:
    return [
        _evidence(
            "ev1",
            "A founder should compare the strength of the problem with current constraints, "
            "including regulation, trust, capital intensity, timing, and market education.",
            source="source-a",
        ),
        _evidence(
            "ev2",
            "A decision to continue or pause should separate conviction in the problem from "
            "runway, people, timing, resources, and the cost of changing the market.",
            source="source-b",
        ),
    ]


def test_semantic_admission_allows_nonlexical_semantic_evidence() -> None:
    question = "如果客戶承認問題存在，為什麼市場仍然可能不動？"
    assert not legacy._requires_precise_overlap(legacy._meaningful_terms(question))
    assert patch._semantic_admission_overlap(
        legacy=legacy,
        question=question,
        evidence=_base_evidence(),
        original=lambda _question, _evidence: False,
    )


def test_semantic_admission_keeps_precise_identifier_questions_strict() -> None:
    question = "Which artifact has sha256 token xqzprtvbnm 838561e6bc4f1fd74ea98f024b16da19815087cd?"
    assert legacy._requires_precise_overlap(legacy._meaningful_terms(question))
    assert not patch._semantic_admission_overlap(
        legacy=legacy,
        question=question,
        evidence=_base_evidence(),
        original=lambda _question, _evidence: False,
    )


def test_evidence_bound_recovery_candidate_verifies_without_internal_labels() -> None:
    question = (
        "Why does evidence of demand still not prove that there is a viable business?"
    )
    evidence = _base_evidence()
    candidate = patch._evidence_bound_recovery_candidate(
        runtime=runtime,
        legacy=legacy,
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=[],
    )
    assert candidate is not None
    assert "e1" not in candidate["answer_text"]
    verified = legacy._verify_multi_evidence_provider_output(
        trace_id="trace-test",
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_text=json.dumps(candidate, ensure_ascii=False),
    )
    answer = legacy._verified_multi_evidence_answer(
        intent_class="direct_grounded_knowledge",
        verified=verified,
        evidence=evidence,
        calls=[],
        repair_attempted=True,
    )
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["unsupported_accepted_claims"] == 0
    assert answer["citation_locator_valid"] is True
    assert answer["citations"]


def test_recovery_does_not_trigger_for_provider_abstention() -> None:
    assert not patch._should_attempt_evidence_recovery(
        {
            "status": "owner_only_safe_abstention",
            "reason_codes": ["PROVIDER_ABSTAINED", "SEMANTIC_CLOSURE_FAILED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
        },
        {"failures": ["PROVIDER_ABSTAINED", "SEMANTIC_CLOSURE_FAILED"]},
        _base_evidence(),
    )
