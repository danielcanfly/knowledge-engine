from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from knowledge_engine.m16_promotion_containment import (
    CandidateArtifactEvidence,
    CandidateFailureReason,
    CandidateObservation,
    CandidateValidationState,
    CompensationState,
    ContainmentDecision,
    M16PromotionContainmentAuthority,
    PromotionAttemptObservation,
    PromotionIdentity,
    PromotionPhase,
    VerificationGateName,
    containment_report_sha256,
    evaluate_candidate,
    evaluate_containment_report,
    evaluate_promotion_attempt,
    finalize_containment_report,
)
from knowledge_engine.m16_security_contracts import M16Identity

NOW = datetime(2026, 7, 10, 5, 30, tzinfo=UTC)
ENGINE = "a" * 40
SOURCE = "b" * 40
CANDIDATE_MANIFEST = "c" * 64
PREVIOUS_MANIFEST = "d" * 64
PREVIOUS_POINTER = "e" * 64


def identity() -> PromotionIdentity:
    return PromotionIdentity(
        engine_sha=ENGINE,
        source_sha=SOURCE,
        candidate_release_id="candidate-release-001",
        candidate_manifest_sha256=CANDIDATE_MANIFEST,
        previous_release_id="production-release-001",
        previous_manifest_sha256=PREVIOUS_MANIFEST,
        previous_pointer_sha256=PREVIOUS_POINTER,
    )


def baseline() -> M16Identity:
    return identity().as_m16_identity()


def artifacts() -> list[CandidateArtifactEvidence]:
    return [
        CandidateArtifactEvidence(
            artifact_id="manifest.json",
            present=True,
            checksum_valid=True,
        ),
        CandidateArtifactEvidence(
            artifact_id="graph.json",
            present=True,
            checksum_valid=True,
        ),
    ]


def candidate(**updates: object) -> CandidateObservation:
    payload: dict[str, object] = {
        "candidate_id": "candidate-001",
        "operation_id": "operation-candidate-001",
        "generated_at": NOW,
        "identity": identity(),
        "observed_engine_sha": ENGINE,
        "observed_source_sha": SOURCE,
        "observed_release_id": "candidate-release-001",
        "observed_manifest_sha256": CANDIDATE_MANIFEST,
        "observed_previous_pointer_sha256": PREVIOUS_POINTER,
        "approval_present": True,
        "operation_seen_before": False,
        "production_scope": False,
        "production_mutated": False,
        "artifacts": artifacts(),
        "evidence_codes": ["m16.3.candidate-evidence"],
    }
    payload.update(updates)
    return CandidateObservation.model_validate(payload)


def attempt(**updates: object) -> PromotionAttemptObservation:
    payload: dict[str, object] = {
        "attempt_id": "attempt-001",
        "operation_id": "operation-attempt-001",
        "generated_at": NOW,
        "identity": identity(),
        "phase": PromotionPhase.VERIFYING,
        "exact_identity_verified": True,
        "approval_verified": True,
        "operation_seen_before": False,
        "activation_occurred": True,
        "runtime_acceptance_passed": False,
        "compensation_state": CompensationState.COMPLETED,
        "observed_pointer_sha256": PREVIOUS_POINTER,
        "observed_runtime_release_id": "production-release-001",
        "observed_cache_release_id": "production-release-001",
        "query_verified": True,
        "citation_verified": True,
        "acl_negative_verified": True,
        "evidence_codes": ["m16.3.promotion-evidence"],
    }
    payload.update(updates)
    return PromotionAttemptObservation.model_validate(payload)


def test_bad_candidate_is_contained_before_production_mutation() -> None:
    result = evaluate_candidate(candidate(observed_manifest_sha256="f" * 64))
    assert result.state == CandidateValidationState.INVALID
    assert result.decision == ContainmentDecision.CONTAINED
    assert result.production_mutated is False
    assert result.reasons == [CandidateFailureReason.MANIFEST_MISMATCH]


def test_bad_candidate_mutating_production_is_uncompensated() -> None:
    result = evaluate_candidate(
        candidate(
            observed_source_sha="f" * 40,
            production_mutated=True,
        )
    )
    assert result.decision == ContainmentDecision.UNCOMPENSATED
    assert CandidateFailureReason.SOURCE_DRIFT in result.reasons


def test_candidate_detects_missing_artifact_checksum_and_replay() -> None:
    broken_artifacts = [
        CandidateArtifactEvidence(
            artifact_id="manifest.json",
            present=False,
            checksum_valid=False,
        ),
        CandidateArtifactEvidence(
            artifact_id="graph.json",
            present=True,
            checksum_valid=False,
        ),
    ]
    result = evaluate_candidate(
        candidate(
            artifacts=broken_artifacts,
            operation_seen_before=True,
            approval_present=False,
        )
    )
    assert result.state == CandidateValidationState.INVALID
    assert result.reasons == sorted(
        [
            CandidateFailureReason.APPROVAL_MISSING,
            CandidateFailureReason.CHECKSUM_FAILURE,
            CandidateFailureReason.DUPLICATE_OPERATION,
            CandidateFailureReason.MISSING_ARTIFACT,
        ],
        key=lambda item: item.value,
    )


def test_valid_candidate_is_not_a_containment_event() -> None:
    result = evaluate_candidate(candidate())
    assert result.state == CandidateValidationState.VALID
    assert result.reasons == []
    assert result.decision == ContainmentDecision.NOT_APPLICABLE


def test_failed_promotion_is_contained_only_after_full_restoration() -> None:
    result = evaluate_promotion_attempt(attempt(), expected_baseline=baseline())
    assert result.decision == ContainmentDecision.CONTAINED
    assert result.failed_checks == []
    assert result.compensation_state == CompensationState.COMPLETED


def test_failed_promotion_requires_compensation_when_not_started() -> None:
    result = evaluate_promotion_attempt(
        attempt(
            compensation_state=CompensationState.REQUIRED,
            observed_pointer_sha256=None,
            observed_runtime_release_id=None,
            observed_cache_release_id=None,
            query_verified=None,
            citation_verified=None,
            acl_negative_verified=None,
        ),
        expected_baseline=baseline(),
    )
    assert result.decision == ContainmentDecision.COMPENSATION_REQUIRED
    assert VerificationGateName.POINTER_RESTORED in result.failed_checks
    assert VerificationGateName.RUNTIME_RESTORED in result.failed_checks


def test_completed_compensation_with_pointer_drift_is_uncompensated() -> None:
    result = evaluate_promotion_attempt(
        attempt(observed_pointer_sha256="f" * 64),
        expected_baseline=baseline(),
    )
    assert result.decision == ContainmentDecision.UNCOMPENSATED
    assert result.failed_checks == [VerificationGateName.POINTER_RESTORED]


def test_identity_drift_is_never_contained() -> None:
    drifted = baseline().model_copy(update={"engine_sha": "f" * 40})
    result = evaluate_promotion_attempt(attempt(), expected_baseline=drifted)
    assert result.decision == ContainmentDecision.UNCOMPENSATED
    assert VerificationGateName.EVIDENCE_COMPLETE in result.failed_checks


def test_nonactivated_attempt_is_not_applicable() -> None:
    result = evaluate_promotion_attempt(
        attempt(
            phase=PromotionPhase.PREVALIDATION,
            activation_occurred=False,
            runtime_acceptance_passed=None,
            compensation_state=CompensationState.NOT_REQUIRED,
            observed_pointer_sha256=None,
            observed_runtime_release_id=None,
            observed_cache_release_id=None,
            query_verified=None,
            citation_verified=None,
            acl_negative_verified=None,
        ),
        expected_baseline=baseline(),
    )
    assert result.decision == ContainmentDecision.NOT_APPLICABLE


def test_report_is_deterministic_and_tamper_evident() -> None:
    report_a = evaluate_containment_report(
        [candidate(observed_manifest_sha256="f" * 64)],
        [attempt()],
        generated_at=NOW,
        baseline_identity=baseline(),
    )
    report_b = evaluate_containment_report(
        list(reversed([candidate(observed_manifest_sha256="f" * 64)])),
        list(reversed([attempt()])),
        generated_at=NOW,
        baseline_identity=baseline(),
    )
    assert report_a.decision == ContainmentDecision.CONTAINED
    assert report_a.artifact_sha256 == report_b.artifact_sha256
    assert report_a.artifact_sha256 == containment_report_sha256(report_a)

    tampered = report_a.model_copy(update={"decision": ContainmentDecision.UNKNOWN})
    with pytest.raises(ValueError, match="digest mismatch"):
        finalize_containment_report(tampered)


def test_report_rejects_duplicate_ids() -> None:
    duplicated = candidate(operation_id="operation-candidate-002")
    with pytest.raises(ValueError, match="candidate IDs must be unique"):
        evaluate_containment_report(
            [candidate(), duplicated],
            [],
            generated_at=NOW,
            baseline_identity=baseline(),
        )


def test_contract_rejects_non_utc_and_unsafe_codes() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        candidate(generated_at=datetime(2026, 7, 10, 5, 30))
    with pytest.raises(ValidationError, match="safe code characters"):
        candidate(evidence_codes=["https://private.example/evidence"])


def test_contract_rejects_duplicate_artifact_ids() -> None:
    duplicated = [artifacts()[0], artifacts()[0]]
    with pytest.raises(ValidationError, match="artifact IDs must be unique"):
        candidate(artifacts=duplicated)


def test_m16_3_has_no_mutation_authority() -> None:
    M16PromotionContainmentAuthority()
    with pytest.raises(ValidationError, match="evidence-only"):
        M16PromotionContainmentAuthority(rollback_allowed=True)
    with pytest.raises(ValidationError, match="evidence-only"):
        M16PromotionContainmentAuthority(pointer_repair_allowed=True)
    with pytest.raises(ValidationError, match="evidence-only"):
        M16PromotionContainmentAuthority(permanent_ledger_append_allowed=True)
