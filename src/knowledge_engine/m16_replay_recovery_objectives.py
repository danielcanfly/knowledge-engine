from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_engine.m16_security_contracts import M16Identity

M16_REPLAY_RECOVERY_SCHEMA = "knowledge-engine-m16-replay-recovery-objectives/v1"
MAX_ATTEMPTS = 512


class OperationKind(StrEnum):
    PROMOTION = "promotion"
    ROLLBACK = "rollback"
    OBJECT_RESTORE = "object_restore"
    SOURCE_RESTORE = "source_restore"
    CONTROL_PLANE_RECONSTRUCTION = "control_plane_reconstruction"


class OperationTerminalState(StrEnum):
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"
    VERIFIED_NOOP = "verified_noop"


class ReplayOutcome(StrEnum):
    ACCEPTED = "accepted"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class RecoveryObjectiveName(StrEnum):
    RTO = "rto"
    RPO = "rpo"
    RELEASE_UNAVAILABILITY = "release_unavailability"
    ROLLBACK_TIME = "rollback_time"
    EVIDENCE_RECOVERY = "evidence_recovery"


class ObjectiveState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ReplayRecoveryDecision(StrEnum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    UNKNOWN = "unknown"


class ReplayRecoveryReason(StrEnum):
    NONE = "none"
    ENGINE_IDENTITY_DRIFT = "engine_identity_drift"
    SOURCE_IDENTITY_DRIFT = "source_identity_drift"
    RELEASE_IDENTITY_DRIFT = "release_identity_drift"
    MANIFEST_IDENTITY_DRIFT = "manifest_identity_drift"
    POINTER_IDENTITY_DRIFT = "pointer_identity_drift"
    EXPECTED_PREVIOUS_POINTER_STALE = "expected_previous_pointer_stale"
    OPERATION_ID_PAYLOAD_MISMATCH = "operation_id_payload_mismatch"
    ROLLED_BACK_OPERATION_RESURRECTION = "rolled_back_operation_resurrection"
    DUPLICATE_MUTATION_CLAIM = "duplicate_mutation_claim"
    OUT_OF_ORDER_SEQUENCE = "out_of_order_sequence"
    RESULTING_POINTER_MISSING = "resulting_pointer_missing"
    RESULTING_POINTER_MISMATCH = "resulting_pointer_mismatch"
    TIMING_EVIDENCE_MISSING = "timing_evidence_missing"
    NON_MONOTONIC_TIMING = "non_monotonic_timing"
    RTO_EXCEEDED = "rto_exceeded"
    RPO_EXCEEDED = "rpo_exceeded"
    UNAVAILABILITY_EXCEEDED = "unavailability_exceeded"
    ROLLBACK_TIME_EXCEEDED = "rollback_time_exceeded"
    EVIDENCE_RECOVERY_EXCEEDED = "evidence_recovery_exceeded"
    EVIDENCE_MISSING = "evidence_missing"


class ReplayRecoveryGateName(StrEnum):
    IDENTITY = "identity"
    REPLAY_SAFETY = "replay_safety"
    IDEMPOTENCY = "idempotency"
    EXPECTED_PREVIOUS = "expected_previous"
    RTO = "rto"
    RPO = "rpo"
    RELEASE_UNAVAILABILITY = "release_unavailability"
    ROLLBACK_TIME = "rollback_time"
    EVIDENCE_RECOVERY = "evidence_recovery"
    EVIDENCE_COMPLETE = "evidence_complete"
    NO_WRITE_AUTHORITY = "no_write_authority"


class GateState(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


_FORBIDDEN_FRAGMENTS = (
    "bearer ",
    "authorization:",
    "cookie:",
    "jwt",
    "raw_query",
    "raw_answer",
    "private excerpt",
    "client_ip",
    "ip_address",
    "hostname",
    "traceback",
    "exception_text",
    "secret_value",
    "access_key",
    "s3://",
    "r2://",
    "file://",
    "http://",
    "https://",
)


class RecoveryObjectivePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_rto_seconds: int = Field(ge=1, le=604800)
    max_rpo_events: int = Field(ge=0, le=1_000_000)
    max_release_unavailability_seconds: int = Field(ge=1, le=604800)
    max_rollback_seconds: int = Field(ge=1, le=604800)
    max_evidence_recovery_seconds: int = Field(ge=1, le=604800)


class OperationAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    operation_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    operation_kind: OperationKind
    sequence: int = Field(ge=1, le=1_000_000_000)
    recorded_at: datetime
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_previous_pointer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resulting_pointer_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    terminal_state: OperationTerminalState
    mutation_claimed: bool
    evidence_codes: list[str] = Field(min_length=1, max_length=32)

    @field_validator("recorded_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        _require_utc(value, "operation recorded_at")
        return value

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        _validate_codes(values, "operation evidence codes")
        return values

    @model_validator(mode="after")
    def validate_pointer_claim(self) -> Self:
        if self.terminal_state == OperationTerminalState.APPLIED:
            if self.resulting_pointer_sha256 is None:
                raise ValueError("applied operation requires resulting pointer")
            if not self.mutation_claimed:
                raise ValueError("applied operation must claim its governed mutation")
        if self.terminal_state in {
            OperationTerminalState.REJECTED,
            OperationTerminalState.VERIFIED_NOOP,
        } and self.mutation_claimed:
            raise ValueError("rejected or no-op operation cannot claim mutation")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class IncidentTimingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unavailable_at: datetime | None = None
    detected_at: datetime | None = None
    decision_at: datetime | None = None
    recovery_started_at: datetime | None = None
    service_restored_at: datetime | None = None
    verification_completed_at: datetime | None = None
    rollback_started_at: datetime | None = None
    rollback_completed_at: datetime | None = None
    evidence_recovered_at: datetime | None = None
    lost_events: int | None = Field(default=None, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def validate_timeline(self) -> Self:
        values = [
            self.unavailable_at,
            self.detected_at,
            self.decision_at,
            self.recovery_started_at,
            self.service_restored_at,
            self.verification_completed_at,
            self.evidence_recovered_at,
        ]
        for value in values:
            if value is not None:
                _require_utc(value, "incident timing")
        ordered = [
            value
            for value in (
                self.unavailable_at,
                self.detected_at,
                self.decision_at,
                self.recovery_started_at,
                self.service_restored_at,
                self.verification_completed_at,
                self.evidence_recovered_at,
            )
            if value is not None
        ]
        if any(later < earlier for earlier, later in zip(ordered, ordered[1:])):
            raise ValueError("incident timing must be monotonic")
        if (self.rollback_started_at is None) != (self.rollback_completed_at is None):
            raise ValueError("rollback timing requires both start and completion")
        if self.rollback_started_at is not None and self.rollback_completed_at is not None:
            _require_utc(self.rollback_started_at, "rollback started_at")
            _require_utc(self.rollback_completed_at, "rollback completed_at")
            if self.rollback_completed_at < self.rollback_started_at:
                raise ValueError("rollback timing must be monotonic")
        return self


class ReplayRecoveryObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drill_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    generated_at: datetime
    identity: M16Identity
    initial_pointer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_pointer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempts: list[OperationAttempt] = Field(min_length=1, max_length=MAX_ATTEMPTS)
    timing: IncidentTimingEvidence
    policy: RecoveryObjectivePolicy
    evidence_codes: list[str] = Field(min_length=1, max_length=64)

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        _require_utc(value, "observation generated_at")
        return value

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        _validate_codes(values, "observation evidence codes")
        return values

    @model_validator(mode="after")
    def validate_attempts(self) -> Self:
        attempt_ids = [item.attempt_id for item in self.attempts]
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("attempt IDs must be unique")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class ReplayAttemptResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    operation_id: str
    outcome: ReplayOutcome
    reasons: list[ReplayRecoveryReason]


class RecoveryObjectiveResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RecoveryObjectiveName
    state: ObjectiveState
    measured_value: int | None = None
    threshold: int
    unit: str = Field(pattern=r"^(seconds|events)$")
    reasons: list[ReplayRecoveryReason]


class ReplayRecoveryGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ReplayRecoveryGateName
    state: GateState
    reasons: list[ReplayRecoveryReason]


class ReplayRecoveryReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = M16_REPLAY_RECOVERY_SCHEMA
    drill_id: str
    generated_at: datetime
    identity: M16Identity
    attempt_results: list[ReplayAttemptResult]
    objective_results: list[RecoveryObjectiveResult]
    gates: list[ReplayRecoveryGate]
    decision: ReplayRecoveryDecision
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class M16ReplayRecoveryAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    promotion_allowed: bool = False
    rollback_allowed: bool = False
    pointer_mutation_allowed: bool = False
    cache_purge_allowed: bool = False
    r2_write_allowed: bool = False
    source_write_allowed: bool = False
    source_pr_allowed: bool = False
    credential_rotation_allowed: bool = False
    physical_delete_allowed: bool = False
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def reject_authority(self) -> Self:
        if any(self.model_dump().values()):
            raise ValueError("M16.6 is evidence-only and grants no mutation authority")
        return self


def evaluate_replay_recovery(
    observation: ReplayRecoveryObservation,
    *,
    expected_identity: M16Identity,
) -> ReplayRecoveryReport:
    identity_reasons = _identity_reasons(observation.identity, expected_identity)
    attempt_results = _evaluate_attempts(observation, identity_reasons)
    objective_results = _evaluate_objectives(observation.timing, observation.policy)
    gates = _build_gates(identity_reasons, attempt_results, objective_results)

    if any(gate.state == GateState.BLOCKED for gate in gates):
        decision = ReplayRecoveryDecision.NON_COMPLIANT
    elif any(gate.state == GateState.UNKNOWN for gate in gates):
        decision = ReplayRecoveryDecision.UNKNOWN
    else:
        decision = ReplayRecoveryDecision.COMPLIANT

    report = ReplayRecoveryReport(
        drill_id=observation.drill_id,
        generated_at=observation.generated_at,
        identity=observation.identity,
        attempt_results=sorted(attempt_results, key=lambda item: item.attempt_id),
        objective_results=sorted(objective_results, key=lambda item: item.name.value),
        gates=sorted(gates, key=lambda item: item.name.value),
        decision=decision,
    )
    return finalize_replay_recovery_report(report)


def finalize_replay_recovery_report(report: ReplayRecoveryReport) -> ReplayRecoveryReport:
    payload = report.model_dump(mode="json", exclude={"artifact_sha256"})
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    if report.artifact_sha256 is not None and report.artifact_sha256 != digest:
        raise ValueError("replay recovery report digest mismatch")
    return report.model_copy(update={"artifact_sha256": digest})


def _evaluate_attempts(
    observation: ReplayRecoveryObservation,
    identity_reasons: list[ReplayRecoveryReason],
) -> list[ReplayAttemptResult]:
    attempts = sorted(
        observation.attempts,
        key=lambda item: (item.sequence, item.recorded_at, item.attempt_id),
    )
    current_pointer = observation.initial_pointer_sha256
    previous_sequence = 0
    seen: dict[str, OperationAttempt] = {}
    results: list[ReplayAttemptResult] = []

    for attempt in attempts:
        reasons = list(identity_reasons)
        prior = seen.get(attempt.operation_id)
        outcome = ReplayOutcome.ACCEPTED

        if attempt.sequence <= previous_sequence:
            reasons.append(ReplayRecoveryReason.OUT_OF_ORDER_SEQUENCE)
        previous_sequence = max(previous_sequence, attempt.sequence)

        if prior is not None:
            if prior.payload_sha256 != attempt.payload_sha256:
                reasons.append(ReplayRecoveryReason.OPERATION_ID_PAYLOAD_MISMATCH)
            elif prior.terminal_state == OperationTerminalState.ROLLED_BACK:
                reasons.append(ReplayRecoveryReason.ROLLED_BACK_OPERATION_RESURRECTION)
            elif attempt.mutation_claimed:
                reasons.append(ReplayRecoveryReason.DUPLICATE_MUTATION_CLAIM)
            elif _same_replay(prior, attempt):
                outcome = ReplayOutcome.IDEMPOTENT_REPLAY
            else:
                reasons.append(ReplayRecoveryReason.EVIDENCE_MISSING)
        else:
            if attempt.expected_previous_pointer_sha256 != current_pointer:
                reasons.append(ReplayRecoveryReason.EXPECTED_PREVIOUS_POINTER_STALE)
            elif attempt.terminal_state == OperationTerminalState.APPLIED:
                if attempt.resulting_pointer_sha256 is None:
                    reasons.append(ReplayRecoveryReason.RESULTING_POINTER_MISSING)
                else:
                    current_pointer = attempt.resulting_pointer_sha256
            elif attempt.terminal_state == OperationTerminalState.ROLLED_BACK:
                if attempt.resulting_pointer_sha256 != current_pointer:
                    reasons.append(ReplayRecoveryReason.RESULTING_POINTER_MISMATCH)

        if reasons:
            outcome = ReplayOutcome.BLOCKED
        results.append(
            ReplayAttemptResult(
                attempt_id=attempt.attempt_id,
                operation_id=attempt.operation_id,
                outcome=outcome,
                reasons=sorted(set(reasons), key=lambda item: item.value),
            )
        )
        if prior is None:
            seen[attempt.operation_id] = attempt

    if current_pointer != observation.current_pointer_sha256:
        results.append(
            ReplayAttemptResult(
                attempt_id="pointer-final-verification",
                operation_id="pointer-final-verification",
                outcome=ReplayOutcome.BLOCKED,
                reasons=[ReplayRecoveryReason.RESULTING_POINTER_MISMATCH],
            )
        )
    return results


def _same_replay(first: OperationAttempt, second: OperationAttempt) -> bool:
    return (
        first.operation_kind == second.operation_kind
        and first.payload_sha256 == second.payload_sha256
        and first.expected_previous_pointer_sha256
        == second.expected_previous_pointer_sha256
        and first.resulting_pointer_sha256 == second.resulting_pointer_sha256
        and first.terminal_state == second.terminal_state
    )


def _evaluate_objectives(
    timing: IncidentTimingEvidence,
    policy: RecoveryObjectivePolicy,
) -> list[RecoveryObjectiveResult]:
    return [
        _duration_objective(
            RecoveryObjectiveName.RTO,
            timing.detected_at,
            timing.service_restored_at,
            policy.max_rto_seconds,
            ReplayRecoveryReason.RTO_EXCEEDED,
        ),
        _count_objective(
            RecoveryObjectiveName.RPO,
            timing.lost_events,
            policy.max_rpo_events,
            ReplayRecoveryReason.RPO_EXCEEDED,
        ),
        _duration_objective(
            RecoveryObjectiveName.RELEASE_UNAVAILABILITY,
            timing.unavailable_at,
            timing.service_restored_at,
            policy.max_release_unavailability_seconds,
            ReplayRecoveryReason.UNAVAILABILITY_EXCEEDED,
        ),
        _duration_objective(
            RecoveryObjectiveName.ROLLBACK_TIME,
            timing.rollback_started_at,
            timing.rollback_completed_at,
            policy.max_rollback_seconds,
            ReplayRecoveryReason.ROLLBACK_TIME_EXCEEDED,
            optional=True,
        ),
        _duration_objective(
            RecoveryObjectiveName.EVIDENCE_RECOVERY,
            timing.detected_at,
            timing.evidence_recovered_at,
            policy.max_evidence_recovery_seconds,
            ReplayRecoveryReason.EVIDENCE_RECOVERY_EXCEEDED,
        ),
    ]


def _duration_objective(
    name: RecoveryObjectiveName,
    start: datetime | None,
    end: datetime | None,
    threshold: int,
    exceeded_reason: ReplayRecoveryReason,
    *,
    optional: bool = False,
) -> RecoveryObjectiveResult:
    if start is None and end is None and optional:
        return RecoveryObjectiveResult(
            name=name,
            state=ObjectiveState.NOT_APPLICABLE,
            threshold=threshold,
            unit="seconds",
            reasons=[],
        )
    if start is None or end is None:
        return RecoveryObjectiveResult(
            name=name,
            state=ObjectiveState.UNKNOWN,
            threshold=threshold,
            unit="seconds",
            reasons=[ReplayRecoveryReason.TIMING_EVIDENCE_MISSING],
        )
    measured = int((end - start).total_seconds())
    if measured < 0:
        return RecoveryObjectiveResult(
            name=name,
            state=ObjectiveState.UNKNOWN,
            measured_value=measured,
            threshold=threshold,
            unit="seconds",
            reasons=[ReplayRecoveryReason.NON_MONOTONIC_TIMING],
        )
    state = ObjectiveState.PASSED if measured <= threshold else ObjectiveState.FAILED
    reasons = [] if state == ObjectiveState.PASSED else [exceeded_reason]
    return RecoveryObjectiveResult(
        name=name,
        state=state,
        measured_value=measured,
        threshold=threshold,
        unit="seconds",
        reasons=reasons,
    )


def _count_objective(
    name: RecoveryObjectiveName,
    measured: int | None,
    threshold: int,
    exceeded_reason: ReplayRecoveryReason,
) -> RecoveryObjectiveResult:
    if measured is None:
        return RecoveryObjectiveResult(
            name=name,
            state=ObjectiveState.UNKNOWN,
            threshold=threshold,
            unit="events",
            reasons=[ReplayRecoveryReason.EVIDENCE_MISSING],
        )
    state = ObjectiveState.PASSED if measured <= threshold else ObjectiveState.FAILED
    reasons = [] if state == ObjectiveState.PASSED else [exceeded_reason]
    return RecoveryObjectiveResult(
        name=name,
        state=state,
        measured_value=measured,
        threshold=threshold,
        unit="events",
        reasons=reasons,
    )


def _build_gates(
    identity_reasons: list[ReplayRecoveryReason],
    attempts: list[ReplayAttemptResult],
    objectives: list[RecoveryObjectiveResult],
) -> list[ReplayRecoveryGate]:
    objective_by_name = {item.name: item for item in objectives}
    blocked_attempts = [item for item in attempts if item.outcome == ReplayOutcome.BLOCKED]
    unknown_attempts = [item for item in attempts if item.outcome == ReplayOutcome.UNKNOWN]
    replay_reasons = [reason for item in blocked_attempts for reason in item.reasons]

    gates = [
        _gate(
            ReplayRecoveryGateName.IDENTITY,
            GateState.BLOCKED if identity_reasons else GateState.PASSED,
            identity_reasons,
        ),
        _gate(
            ReplayRecoveryGateName.REPLAY_SAFETY,
            GateState.BLOCKED if blocked_attempts else GateState.PASSED,
            replay_reasons,
        ),
        _gate(
            ReplayRecoveryGateName.IDEMPOTENCY,
            GateState.BLOCKED
            if ReplayRecoveryReason.DUPLICATE_MUTATION_CLAIM in replay_reasons
            else GateState.PASSED,
            [
                reason
                for reason in replay_reasons
                if reason == ReplayRecoveryReason.DUPLICATE_MUTATION_CLAIM
            ],
        ),
        _gate(
            ReplayRecoveryGateName.EXPECTED_PREVIOUS,
            GateState.BLOCKED
            if ReplayRecoveryReason.EXPECTED_PREVIOUS_POINTER_STALE in replay_reasons
            else GateState.PASSED,
            [
                reason
                for reason in replay_reasons
                if reason == ReplayRecoveryReason.EXPECTED_PREVIOUS_POINTER_STALE
            ],
        ),
    ]
    objective_gate_names = {
        RecoveryObjectiveName.RTO: ReplayRecoveryGateName.RTO,
        RecoveryObjectiveName.RPO: ReplayRecoveryGateName.RPO,
        RecoveryObjectiveName.RELEASE_UNAVAILABILITY:
            ReplayRecoveryGateName.RELEASE_UNAVAILABILITY,
        RecoveryObjectiveName.ROLLBACK_TIME: ReplayRecoveryGateName.ROLLBACK_TIME,
        RecoveryObjectiveName.EVIDENCE_RECOVERY:
            ReplayRecoveryGateName.EVIDENCE_RECOVERY,
    }
    for objective_name, gate_name in objective_gate_names.items():
        objective = objective_by_name[objective_name]
        state = {
            ObjectiveState.PASSED: GateState.PASSED,
            ObjectiveState.FAILED: GateState.BLOCKED,
            ObjectiveState.UNKNOWN: GateState.UNKNOWN,
            ObjectiveState.NOT_APPLICABLE: GateState.NOT_APPLICABLE,
        }[objective.state]
        gates.append(_gate(gate_name, state, objective.reasons))

    evidence_state = GateState.UNKNOWN if unknown_attempts else GateState.PASSED
    if any(item.state == ObjectiveState.UNKNOWN for item in objectives):
        evidence_state = GateState.UNKNOWN
    gates.extend(
        [
            _gate(
                ReplayRecoveryGateName.EVIDENCE_COMPLETE,
                evidence_state,
                [ReplayRecoveryReason.EVIDENCE_MISSING]
                if evidence_state == GateState.UNKNOWN
                else [],
            ),
            _gate(ReplayRecoveryGateName.NO_WRITE_AUTHORITY, GateState.PASSED, []),
        ]
    )
    return gates


def _gate(
    name: ReplayRecoveryGateName,
    state: GateState,
    reasons: list[ReplayRecoveryReason],
) -> ReplayRecoveryGate:
    return ReplayRecoveryGate(
        name=name,
        state=state,
        reasons=sorted(set(reasons), key=lambda item: item.value),
    )


def _identity_reasons(
    actual: M16Identity,
    expected: M16Identity,
) -> list[ReplayRecoveryReason]:
    checks = (
        (actual.engine_sha, expected.engine_sha, ReplayRecoveryReason.ENGINE_IDENTITY_DRIFT),
        (actual.source_sha, expected.source_sha, ReplayRecoveryReason.SOURCE_IDENTITY_DRIFT),
        (actual.release_id, expected.release_id, ReplayRecoveryReason.RELEASE_IDENTITY_DRIFT),
        (
            actual.manifest_sha256,
            expected.manifest_sha256,
            ReplayRecoveryReason.MANIFEST_IDENTITY_DRIFT,
        ),
        (
            actual.pointer_sha256,
            expected.pointer_sha256,
            ReplayRecoveryReason.POINTER_IDENTITY_DRIFT,
        ),
    )
    return [reason for left, right, reason in checks if left != right]


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _validate_codes(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if not 3 <= len(value) <= 96:
            raise ValueError(f"{label} must be bounded")
        if not all(character.isalnum() or character in "._:-" for character in value):
            raise ValueError(f"{label} must use closed-format codes")
    _reject_forbidden(values)


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware UTC")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{label} must use UTC")


def _reject_forbidden(payload: object) -> None:
    text = json.dumps(payload, sort_keys=True, default=str).lower()
    if any(fragment in text for fragment in _FORBIDDEN_FRAGMENTS):
        raise ValueError("private or unsafe evidence is forbidden")
