from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from knowledge_engine.m16_replay_recovery_objectives import (
    GateState,
    IncidentTimingEvidence,
    M16ReplayRecoveryAuthority,
    ObjectiveState,
    OperationAttempt,
    OperationKind,
    OperationTerminalState,
    RecoveryObjectiveName,
    RecoveryObjectivePolicy,
    ReplayOutcome,
    ReplayRecoveryDecision,
    ReplayRecoveryObservation,
    ReplayRecoveryReason,
    evaluate_replay_recovery,
    finalize_replay_recovery_report,
)
from knowledge_engine.m16_security_contracts import M16Identity

ENGINE = "139ec0cdd79ca2644a57ebe3a60e2c42c9aa0d9d"
SOURCE = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
RELEASE = "20260708T040116Z-69a9f445699a"
MANIFEST = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
NEW_POINTER = "a" * 64
PAYLOAD_A = "b" * 64
PAYLOAD_B = "c" * 64
NOW = datetime(2026, 7, 10, 8, 45, tzinfo=UTC)


def identity(*, engine_sha: str = ENGINE) -> M16Identity:
    return M16Identity(
        engine_sha=engine_sha,
        source_sha=SOURCE,
        release_id=RELEASE,
        manifest_sha256=MANIFEST,
        pointer_sha256=POINTER,
    )


def policy(**updates: int) -> RecoveryObjectivePolicy:
    payload = {
        "max_rto_seconds": 900,
        "max_rpo_events": 1,
        "max_release_unavailability_seconds": 600,
        "max_rollback_seconds": 300,
        "max_evidence_recovery_seconds": 1200,
    }
    payload.update(updates)
    return RecoveryObjectivePolicy(**payload)


def timing(**updates: object) -> IncidentTimingEvidence:
    payload: dict[str, object] = {
        "unavailable_at": NOW,
        "detected_at": NOW + timedelta(seconds=30),
        "decision_at": NOW + timedelta(seconds=60),
        "recovery_started_at": NOW + timedelta(seconds=90),
        "service_restored_at": NOW + timedelta(seconds=300),
        "verification_completed_at": NOW + timedelta(seconds=360),
        "evidence_recovered_at": NOW + timedelta(seconds=420),
        "lost_events": 0,
    }
    payload.update(updates)
    return IncidentTimingEvidence(**payload)


def attempt(
    *,
    attempt_id: str,
    operation_id: str,
    sequence: int,
    payload_sha256: str = PAYLOAD_A,
    expected_previous: str = POINTER,
    resulting_pointer: str | None = None,
    terminal_state: OperationTerminalState = OperationTerminalState.REJECTED,
    mutation_claimed: bool = False,
    operation_kind: OperationKind = OperationKind.PROMOTION,
) -> OperationAttempt:
    return OperationAttempt(
        attempt_id=attempt_id,
        operation_id=operation_id,
        operation_kind=operation_kind,
        sequence=sequence,
        recorded_at=NOW + timedelta(seconds=sequence),
        payload_sha256=payload_sha256,
        expected_previous_pointer_sha256=expected_previous,
        resulting_pointer_sha256=resulting_pointer,
        terminal_state=terminal_state,
        mutation_claimed=mutation_claimed,
        evidence_codes=[f"attempt.{attempt_id}.verified"],
    )


def observation(
    *,
    attempts: list[OperationAttempt] | None = None,
    current_pointer: str = NEW_POINTER,
    incident_timing: IncidentTimingEvidence | None = None,
    expected_identity: M16Identity | None = None,
    objective_policy: RecoveryObjectivePolicy | None = None,
    evidence_codes: list[str] | None = None,
) -> ReplayRecoveryObservation:
    if attempts is None:
        attempts = [
            attempt(
                attempt_id="attempt-1",
                operation_id="operation-apply",
                sequence=1,
                resulting_pointer=NEW_POINTER,
                terminal_state=OperationTerminalState.APPLIED,
                mutation_claimed=True,
            ),
            attempt(
                attempt_id="attempt-2",
                operation_id="operation-rejected",
                sequence=2,
                expected_previous=NEW_POINTER,
            ),
            attempt(
                attempt_id="attempt-3",
                operation_id="operation-rejected",
                sequence=3,
                expected_previous=NEW_POINTER,
            ),
        ]
    return ReplayRecoveryObservation(
        drill_id="drill-m16-6-replay",
        generated_at=NOW + timedelta(minutes=10),
        identity=expected_identity or identity(),
        initial_pointer_sha256=POINTER,
        current_pointer_sha256=current_pointer,
        attempts=attempts,
        timing=incident_timing or timing(),
        policy=objective_policy or policy(),
        evidence_codes=evidence_codes or ["replay.audit.verified", "recovery.timing.verified"],
    )


def test_safe_sequence_exact_replay_and_objectives_are_compliant() -> None:
    report = evaluate_replay_recovery(observation(), expected_identity=identity())

    assert report.decision == ReplayRecoveryDecision.COMPLIANT
    outcomes = {item.attempt_id: item.outcome for item in report.attempt_results}
    assert outcomes["attempt-1"] == ReplayOutcome.ACCEPTED
    assert outcomes["attempt-2"] == ReplayOutcome.ACCEPTED
    assert outcomes["attempt-3"] == ReplayOutcome.IDEMPOTENT_REPLAY
    assert all(
        item.state in {ObjectiveState.PASSED, ObjectiveState.NOT_APPLICABLE}
        for item in report.objective_results
    )


def test_stale_expected_previous_pointer_is_blocked() -> None:
    attempts = [
        attempt(
            attempt_id="attempt-stale",
            operation_id="operation-stale",
            sequence=1,
            expected_previous=NEW_POINTER,
        )
    ]
    report = evaluate_replay_recovery(
        observation(attempts=attempts, current_pointer=POINTER),
        expected_identity=identity(),
    )

    assert report.decision == ReplayRecoveryDecision.NON_COMPLIANT
    assert ReplayRecoveryReason.EXPECTED_PREVIOUS_POINTER_STALE in (
        report.attempt_results[0].reasons
    )


def test_reused_operation_id_with_different_payload_is_blocked() -> None:
    attempts = [
        attempt(attempt_id="attempt-a", operation_id="operation-same", sequence=1),
        attempt(
            attempt_id="attempt-b",
            operation_id="operation-same",
            sequence=2,
            payload_sha256=PAYLOAD_B,
        ),
    ]
    report = evaluate_replay_recovery(
        observation(attempts=attempts, current_pointer=POINTER),
        expected_identity=identity(),
    )

    second = next(item for item in report.attempt_results if item.attempt_id == "attempt-b")
    assert second.outcome == ReplayOutcome.BLOCKED
    assert ReplayRecoveryReason.OPERATION_ID_PAYLOAD_MISMATCH in second.reasons


def test_rolled_back_operation_cannot_be_resurrected() -> None:
    attempts = [
        attempt(
            attempt_id="attempt-rollback",
            operation_id="operation-old",
            sequence=1,
            resulting_pointer=POINTER,
            terminal_state=OperationTerminalState.ROLLED_BACK,
            mutation_claimed=True,
            operation_kind=OperationKind.ROLLBACK,
        ),
        attempt(
            attempt_id="attempt-resurrection",
            operation_id="operation-old",
            sequence=2,
            resulting_pointer=POINTER,
            terminal_state=OperationTerminalState.ROLLED_BACK,
            mutation_claimed=False,
            operation_kind=OperationKind.ROLLBACK,
        ),
    ]
    report = evaluate_replay_recovery(
        observation(attempts=attempts, current_pointer=POINTER),
        expected_identity=identity(),
    )

    resurrection = next(
        item for item in report.attempt_results if item.attempt_id == "attempt-resurrection"
    )
    assert ReplayRecoveryReason.ROLLED_BACK_OPERATION_RESURRECTION in resurrection.reasons


def test_duplicate_mutation_claim_is_blocked() -> None:
    attempts = [
        attempt(
            attempt_id="attempt-first",
            operation_id="operation-duplicate",
            sequence=1,
            resulting_pointer=NEW_POINTER,
            terminal_state=OperationTerminalState.APPLIED,
            mutation_claimed=True,
        ),
        attempt(
            attempt_id="attempt-second",
            operation_id="operation-duplicate",
            sequence=2,
            resulting_pointer=NEW_POINTER,
            terminal_state=OperationTerminalState.APPLIED,
            mutation_claimed=True,
        ),
    ]
    report = evaluate_replay_recovery(
        observation(attempts=attempts),
        expected_identity=identity(),
    )

    duplicate = next(
        item for item in report.attempt_results if item.attempt_id == "attempt-second"
    )
    assert ReplayRecoveryReason.DUPLICATE_MUTATION_CLAIM in duplicate.reasons


def test_new_operation_after_rollback_is_allowed_with_current_pointer() -> None:
    attempts = [
        attempt(
            attempt_id="attempt-rollback",
            operation_id="operation-rollback",
            sequence=1,
            resulting_pointer=POINTER,
            terminal_state=OperationTerminalState.ROLLED_BACK,
            mutation_claimed=True,
            operation_kind=OperationKind.ROLLBACK,
        ),
        attempt(
            attempt_id="attempt-new",
            operation_id="operation-new",
            sequence=2,
            resulting_pointer=NEW_POINTER,
            terminal_state=OperationTerminalState.APPLIED,
            mutation_claimed=True,
        ),
    ]
    report = evaluate_replay_recovery(
        observation(attempts=attempts),
        expected_identity=identity(),
    )

    assert report.decision == ReplayRecoveryDecision.COMPLIANT
    new_result = next(
        item for item in report.attempt_results if item.attempt_id == "attempt-new"
    )
    assert new_result.outcome == ReplayOutcome.ACCEPTED


def test_duplicate_sequence_claim_is_blocked() -> None:
    attempts = [
        attempt(attempt_id="attempt-one", operation_id="operation-one", sequence=1),
        attempt(attempt_id="attempt-two", operation_id="operation-two", sequence=1),
    ]
    report = evaluate_replay_recovery(
        observation(attempts=attempts, current_pointer=POINTER),
        expected_identity=identity(),
    )

    assert any(
        ReplayRecoveryReason.OUT_OF_ORDER_SEQUENCE in item.reasons
        for item in report.attempt_results
    )


def test_recovery_objective_breach_is_non_compliant() -> None:
    slow_timing = timing(
        service_restored_at=NOW + timedelta(seconds=1200),
        verification_completed_at=NOW + timedelta(seconds=1260),
        evidence_recovered_at=NOW + timedelta(seconds=1500),
        lost_events=4,
    )
    report = evaluate_replay_recovery(
        observation(
            incident_timing=slow_timing,
            objective_policy=policy(
                max_rto_seconds=300,
                max_rpo_events=1,
                max_release_unavailability_seconds=300,
                max_evidence_recovery_seconds=600,
            ),
        ),
        expected_identity=identity(),
    )

    assert report.decision == ReplayRecoveryDecision.NON_COMPLIANT
    by_name = {item.name: item for item in report.objective_results}
    assert by_name[RecoveryObjectiveName.RTO].state == ObjectiveState.FAILED
    assert by_name[RecoveryObjectiveName.RPO].state == ObjectiveState.FAILED


def test_missing_timing_evidence_is_unknown() -> None:
    missing = IncidentTimingEvidence(lost_events=None)
    report = evaluate_replay_recovery(
        observation(incident_timing=missing),
        expected_identity=identity(),
    )

    assert report.decision == ReplayRecoveryDecision.UNKNOWN
    assert any(gate.state == GateState.UNKNOWN for gate in report.gates)


def test_non_monotonic_timing_is_rejected() -> None:
    with pytest.raises(ValidationError, match="monotonic"):
        timing(
            decision_at=NOW + timedelta(seconds=20),
            detected_at=NOW + timedelta(seconds=30),
        )


def test_identity_drift_blocks_replay_acceptance() -> None:
    report = evaluate_replay_recovery(
        observation(),
        expected_identity=identity(engine_sha="f" * 40),
    )

    assert report.decision == ReplayRecoveryDecision.NON_COMPLIANT
    assert any(
        ReplayRecoveryReason.ENGINE_IDENTITY_DRIFT in item.reasons
        for item in report.attempt_results
    )


def test_report_is_deterministic_and_tamper_evident() -> None:
    first_observation = observation()
    second_observation = observation(
        attempts=list(reversed(first_observation.attempts)),
        evidence_codes=list(reversed(first_observation.evidence_codes)),
    )
    first = evaluate_replay_recovery(first_observation, expected_identity=identity())
    second = evaluate_replay_recovery(second_observation, expected_identity=identity())

    assert first.artifact_sha256 == second.artifact_sha256
    tampered = first.model_copy(update={"decision": ReplayRecoveryDecision.NON_COMPLIANT})
    with pytest.raises(ValueError, match="digest mismatch"):
        finalize_replay_recovery_report(tampered)


def test_private_payload_and_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ReplayRecoveryObservation(
            **observation().model_dump(),
            raw_query="private data",
        )
    with pytest.raises(ValidationError):
        observation(evidence_codes=["https://private.example"])


def test_authority_model_rejects_every_mutation_permission() -> None:
    authority = M16ReplayRecoveryAuthority()
    assert not any(authority.model_dump().values())

    for field_name in authority.model_fields:
        with pytest.raises(ValidationError, match="evidence-only"):
            M16ReplayRecoveryAuthority(**{field_name: True})
