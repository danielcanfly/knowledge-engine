import pytest

from knowledge_engine.m15_feedback_triage import (
    CandidateState,
    FeedbackAuthority,
    FeedbackCategory,
    FeedbackEvidence,
    Severity,
    TriageState,
    finalize_candidate,
    finalize_report,
    triage_feedback,
)

ENGINE = "2f7d8a37768b9b8f6c86b93df94a9c243d11df79"
SOURCE = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"


def evidence(feedback_id: str = "feedback:1", **overrides: object) -> FeedbackEvidence:
    values: dict[str, object] = {
        "feedback_id": feedback_id,
        "category": FeedbackCategory.FACTUAL_ERROR,
        "severity": Severity.HIGH,
        "confidence": 0.95,
        "summary_code": "fact_mismatch",
        "target_id": "concept:1",
        "engine_sha": ENGINE,
        "expected_engine_sha": ENGINE,
        "source_sha": SOURCE,
        "expected_source_sha": SOURCE,
        "release_id": "20260708T040116Z-69a9f445699a",
        "audience": "public",
    }
    values.update(overrides)
    return FeedbackEvidence(**values)


def test_actionable_feedback_creates_review_gated_candidate() -> None:
    report = triage_feedback([evidence()])
    decision = report.decisions[0]
    assert decision.state == TriageState.ACTIONABLE
    assert decision.candidate is not None
    assert decision.candidate.state == CandidateState.PENDING_HUMAN_REVIEW
    assert decision.candidate.artifact_sha256


def test_duplicate_feedback_is_deduplicated_deterministically() -> None:
    report = triage_feedback([evidence("feedback:2"), evidence("feedback:1")])
    assert [item.feedback_id for item in report.decisions] == ["feedback:1", "feedback:2"]
    assert [item.state for item in report.decisions].count(TriageState.DUPLICATE) == 1


def test_low_confidence_does_not_create_candidate() -> None:
    report = triage_feedback([evidence(confidence=0.5)])
    assert report.decisions[0].state == TriageState.INSUFFICIENT_EVIDENCE
    assert report.decisions[0].candidate is None


def test_identity_drift_is_policy_rejected() -> None:
    report = triage_feedback([evidence(engine_sha="0" * 40)])
    assert report.decisions[0].state == TriageState.POLICY_REJECTED


def test_low_severity_quality_feedback_is_no_change() -> None:
    report = triage_feedback(
        [evidence(category=FeedbackCategory.QUALITY_PROBLEM, severity=Severity.LOW)]
    )
    assert report.decisions[0].state == TriageState.NO_CHANGE


def test_contract_rejects_private_and_secret_fields() -> None:
    with pytest.raises(ValueError):
        FeedbackEvidence(**{**evidence().model_dump(), "raw_query": "secret"})
    with pytest.raises(ValueError):
        evidence(summary_code="bearer token")


def test_mutation_authority_is_rejected() -> None:
    with pytest.raises(ValueError):
        FeedbackAuthority(source_write_allowed=True)
    with pytest.raises(ValueError):
        FeedbackAuthority(candidate_dispatch_allowed=True)
    with pytest.raises(ValueError):
        FeedbackAuthority(automatic_correction_allowed=True)


def test_candidate_and_report_are_tamper_evident() -> None:
    report = triage_feedback([evidence()])
    candidate = report.decisions[0].candidate
    assert candidate is not None
    with pytest.raises(ValueError):
        finalize_candidate(candidate.model_copy(update={"target_id": "concept:2"}))
    with pytest.raises(ValueError):
        finalize_report(report.model_copy(update={"decisions": []}))


def test_report_digest_is_deterministic() -> None:
    first = triage_feedback([evidence()])
    second = triage_feedback([evidence()])
    assert first.artifact_sha256 == second.artifact_sha256
