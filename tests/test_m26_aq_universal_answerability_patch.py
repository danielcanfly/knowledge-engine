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


def test_semantic_admission_allows_nonlexical_semantic_evidence() -> None:
    evidence = [
        _evidence(
            "ev1",
            (
                "Customers may recognize the problem but still avoid adoption when "
                "switching cost, trust, timing, and incentives are unresolved."
            ),
            source="source-a",
            channels=["dense"],
        ),
        _evidence(
            "ev2",
            (
                "A useful market signal is not only pain, but willingness to change "
                "behavior under real constraints."
            ),
            source="source-b",
            channels=["semantic_requirement_recovery"],
        ),
    ]

    assert patch._semantic_admission_overlap(
        legacy=legacy,
        question="為什麼大家承認問題存在卻仍然不願意採用？",
        evidence=evidence,
        original=lambda question, evidence: False,
    )


def test_semantic_admission_keeps_precise_identifier_questions_strict() -> None:
    evidence = [
        _evidence(
            "ev1",
            "This unrelated paragraph has hydrated section identity but no requested digest.",
            source="source-a",
            channels=["dense"],
        ),
        _evidence(
            "ev2",
            "Another unrelated paragraph should not admit exact token questions.",
            source="source-b",
            channels=["dense"],
        ),
    ]

    assert not patch._semantic_admission_overlap(
        legacy=legacy,
        question="What is the sha256 token BCDFGHJKLMNPQRST for this release digest?",
        evidence=evidence,
        original=lambda question, evidence: False,
    )


def test_runtime_overlap_rejects_dense_without_semantic_metadata_signal() -> None:
    evidence = [
        _evidence(
            "ev1",
            "This passage is only a dense candidate with no positive semantic metadata.",
            source="source-a",
            channels=["dense"],
        ),
        _evidence(
            "ev2",
            "This second passage is also dense-only and has no admission proof.",
            source="source-b",
            channels=["dense"],
        ),
    ]

    assert not legacy._has_meaningful_overlap(
        "完全不同語言的問題沒有字面重疊時不能靠空白語義訊號放行",
        evidence,
    )


def test_evidence_bound_recovery_candidate_verifies_without_internal_labels() -> None:
    evidence = [
        _evidence(
            "ev1",
            (
                "Evidence-driven learning is shown by a changed constraint, a changed "
                "problem frame, and a changed market reality."
            ),
            source="source-a",
            channels=["query_coverage"],
        ),
        _evidence(
            "ev2",
            (
                "Aimless drift is weaker when the decision cannot be tied back to new "
                "evidence about the problem or constraints."
            ),
            source="source-b",
            channels=["dense"],
        ),
    ]

    candidate = patch._evidence_bound_recovery_candidate(
        runtime=runtime,
        legacy=legacy,
        question="How can a builder distinguish evidence-driven learning from aimless drift?",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=[],
    )
    assert candidate is not None
    assert "e1" not in candidate["answer_text"]
    verified = legacy._verify_multi_evidence_provider_output(
        trace_id="trace-test",
        question="How can a builder distinguish evidence-driven learning from aimless drift?",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_text=json.dumps(candidate),
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
    verification = {
        "status": "owner_only_safe_abstention",
        "reason_codes": ["PROVIDER_ABSTAINED"],
        "unsupported_accepted_claims": 0,
        "citation_locator_valid": True,
    }
    closure = {"failures": ["PROVIDER_ABSTAINED"]}

    assert not patch._should_attempt_evidence_recovery(
        verification,
        closure,
        [_evidence("ev1", "A supported passage exists.", source="source-a")],
    )
