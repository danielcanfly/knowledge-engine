from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_engine.m16_security_contracts import M16Identity

M16_RESTORE_DRILL_SCHEMA = "knowledge-engine-m16-end-to-end-restore-drill/v1"
MAX_STAGES = 32


class DrillStage(StrEnum):
    DETECTION = "detection"
    CONTAINMENT = "containment"
    AUTHORIZATION = "authorization"
    RESTORATION = "restoration"
    CHECKSUM_VERIFICATION = "checksum_verification"
    RUNTIME_VERIFICATION = "runtime_verification"
    REPLAY_VERIFICATION = "replay_verification"
    RECOVERY_OBJECTIVES = "recovery_objectives"
    AUDIT_CONTINUITY = "audit_continuity"
    CLOSEOUT = "closeout"


class StageState(StrEnum):
    VERIFIED = "verified"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class ObjectiveState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class DrillGateName(StrEnum):
    IDENTITY = "identity"
    ORDERED_STAGES = "ordered_stages"
    DETECTION = "detection"
    CONTAINMENT = "containment"
    AUTHORIZATION = "authorization"
    RESTORATION = "restoration"
    CHECKSUM_VERIFICATION = "checksum_verification"
    RUNTIME_VERIFICATION = "runtime_verification"
    REPLAY_VERIFICATION = "replay_verification"
    RECOVERY_OBJECTIVES = "recovery_objectives"
    AUDIT_CONTINUITY = "audit_continuity"
    CLOSEOUT = "closeout"
    EVIDENCE_COMPLETE = "evidence_complete"
    NO_WRITE_AUTHORITY = "no_write_authority"


class GateState(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class CloseoutDecision(StrEnum):
    READY_TO_CLOSE = "ready_to_close"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class DrillReason(StrEnum):
    NONE = "none"
    IDENTITY_DRIFT = "identity_drift"
    STAGE_MISSING = "stage_missing"
    STAGE_BLOCKED = "stage_blocked"
    STAGE_UNKNOWN = "stage_unknown"
    STAGE_OUT_OF_ORDER = "stage_out_of_order"
    EVIDENCE_STALE = "evidence_stale"
    EVIDENCE_FUTURE_DATED = "evidence_future_dated"
    DETECTION_INCOMPLETE = "detection_incomplete"
    CONTAINMENT_INCOMPLETE = "containment_incomplete"
    AUTHORIZATION_MISSING = "authorization_missing"
    RESTORE_NOT_EXECUTED = "restore_not_executed"
    OBJECT_DIGEST_MISMATCH = "object_digest_mismatch"
    MANIFEST_MISMATCH = "manifest_mismatch"
    RELEASE_IDENTITY_MISMATCH = "release_identity_mismatch"
    POINTER_IDENTITY_MISMATCH = "pointer_identity_mismatch"
    CACHE_IDENTITY_MISMATCH = "cache_identity_mismatch"
    QUERY_VERIFICATION_FAILED = "query_verification_failed"
    CITATION_VERIFICATION_FAILED = "citation_verification_failed"
    ACL_VERIFICATION_FAILED = "acl_verification_failed"
    REPLAY_SAFETY_FAILED = "replay_safety_failed"
    IDEMPOTENCY_FAILED = "idempotency_failed"
    EXPECTED_PREVIOUS_FAILED = "expected_previous_failed"
    RECOVERY_OBJECTIVE_FAILED = "recovery_objective_failed"
    RECOVERY_OBJECTIVE_UNKNOWN = "recovery_objective_unknown"
    AUDIT_CONTINUITY_FAILED = "audit_continuity_failed"
    LEDGER_INVARIANT_FAILED = "ledger_invariant_failed"
    CLOSEOUT_NOT_APPROVED = "closeout_not_approved"
    EVIDENCE_MISSING = "evidence_missing"


_STAGE_ORDER = {stage: index for index, stage in enumerate(DrillStage)}
_GATE_ORDER = {gate: index for index, gate in enumerate(DrillGateName)}
_REQUIRED_STAGES = tuple(DrillStage)

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


class DrillStageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: DrillStage
    occurred_at: datetime
    state: StageState
    evidence_codes: list[str] = Field(min_length=1, max_length=32)

    @field_validator("occurred_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        _require_utc(value, "stage occurred_at")
        return value

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        _validate_codes(values, "stage evidence codes")
        return values

    @model_validator(mode="after")
    def reject_private_evidence(self) -> Self:
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class M16RestoreDrillAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    production_write_allowed: bool = False
    pointer_repair_allowed: bool = False
    cache_purge_allowed: bool = False
    r2_write_allowed: bool = False
    r2_copy_allowed: bool = False
    r2_delete_allowed: bool = False
    source_write_allowed: bool = False
    source_pr_allowed: bool = False
    promotion_allowed: bool = False
    rollback_allowed: bool = False
    credential_rotation_allowed: bool = False
    physical_deletion_allowed: bool = False
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def reject_mutation_authority(self) -> Self:
        if any(self.model_dump().values()):
            raise ValueError("M16.7 is evidence-only and cannot grant mutation authority")
        return self


class RestoreDrillObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drill_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    incident_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    operation_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    generated_at: datetime
    identity: M16Identity
    expected_previous_pointer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    affected_object_id: str = Field(min_length=3, max_length=160, pattern=r"^[a-zA-Z0-9._:/-]+$")
    stages: list[DrillStageEvidence] = Field(min_length=1, max_length=MAX_STAGES)

    incident_detected: bool
    blast_radius_bounded: bool
    production_writes_disabled: bool
    production_pointer_unchanged: bool

    authorization_approved: bool
    authorization_id: str | None = Field(default=None, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    authorization_scope_verified: bool

    restore_executed: bool
    expected_object_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    restored_object_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    restored_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    restored_release_id: str | None = Field(default=None, min_length=3, max_length=128)
    restored_pointer_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    runtime_release_id: str | None = Field(default=None, min_length=3, max_length=128)
    runtime_pointer_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    cache_release_id: str | None = Field(default=None, min_length=3, max_length=128)
    public_query_verified: bool
    citation_verified: bool
    acl_negative_denied: bool

    replay_compliant: bool
    idempotency_verified: bool
    expected_previous_verified: bool

    rto_state: ObjectiveState
    rpo_state: ObjectiveState
    release_unavailability_state: ObjectiveState
    rollback_state: ObjectiveState
    evidence_recovery_state: ObjectiveState

    audit_continuity_verified: bool
    permanent_ledger_open: bool
    expected_permanent_ledger_comments: int = Field(ge=0, le=1_000_000)
    observed_permanent_ledger_comments: int = Field(ge=0, le=1_000_000)
    permanent_ledger_appended: bool

    closeout_approved: bool
    max_evidence_age_seconds: int = Field(default=86_400, ge=1, le=604_800)
    evidence_codes: list[str] = Field(min_length=1, max_length=64)
    authority: M16RestoreDrillAuthority = Field(default_factory=M16RestoreDrillAuthority)

    @field_validator("generated_at")
    @classmethod
    def require_generated_at_utc(cls, value: datetime) -> datetime:
        _require_utc(value, "generated_at")
        return value

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        _validate_codes(values, "drill evidence codes")
        return values

    @model_validator(mode="after")
    def validate_stage_uniqueness_and_restore_shape(self) -> Self:
        stage_values = [item.stage for item in self.stages]
        if len(stage_values) != len(set(stage_values)):
            raise ValueError("drill stage evidence must be unique")
        if self.restore_executed and not self.authorization_approved:
            raise ValueError("represented restoration requires approved authorization")
        if self.authorization_approved and not self.authorization_id:
            raise ValueError("approved authorization requires authorization_id")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class DrillGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DrillGateName
    state: GateState
    reasons: list[DrillReason] = Field(min_length=1, max_length=32)


class RestoreDrillReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema: str = M16_RESTORE_DRILL_SCHEMA
    generated_at: datetime
    identity: M16Identity
    drill_id: str
    incident_id: str
    operation_id: str
    stages: list[DrillStageEvidence]
    gates: list[DrillGate]
    reasons: list[DrillReason]
    decision: CloseoutDecision
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def evaluate_restore_drill(
    observation: RestoreDrillObservation,
    *,
    expected_identity: M16Identity,
) -> RestoreDrillReport:
    stages = sorted(observation.stages, key=lambda item: _STAGE_ORDER[item.stage])
    stage_map = {item.stage: item for item in stages}
    gates: list[DrillGate] = []

    identity_reasons = (
        []
        if observation.identity.model_dump() == expected_identity.model_dump()
        else [DrillReason.IDENTITY_DRIFT]
    )
    gates.append(_gate(DrillGateName.IDENTITY, identity_reasons))

    stage_reasons: list[DrillReason] = []
    missing = [stage for stage in _REQUIRED_STAGES if stage not in stage_map]
    if missing:
        stage_reasons.append(DrillReason.STAGE_MISSING)
    previous_time: datetime | None = None
    for stage in _REQUIRED_STAGES:
        evidence = stage_map.get(stage)
        if evidence is None:
            continue
        if evidence.occurred_at > observation.generated_at:
            stage_reasons.append(DrillReason.EVIDENCE_FUTURE_DATED)
        if observation.generated_at - evidence.occurred_at > timedelta(
            seconds=observation.max_evidence_age_seconds
        ):
            stage_reasons.append(DrillReason.EVIDENCE_STALE)
        if previous_time is not None and evidence.occurred_at < previous_time:
            stage_reasons.append(DrillReason.STAGE_OUT_OF_ORDER)
        previous_time = evidence.occurred_at
    gates.append(_gate(DrillGateName.ORDERED_STAGES, stage_reasons))

    gates.append(
        _stage_gate(
            DrillGateName.DETECTION,
            DrillStage.DETECTION,
            stage_map,
            [] if observation.incident_detected else [DrillReason.DETECTION_INCOMPLETE],
        )
    )
    containment_reasons: list[DrillReason] = []
    if not (
        observation.blast_radius_bounded
        and observation.production_writes_disabled
        and observation.production_pointer_unchanged
    ):
        containment_reasons.append(DrillReason.CONTAINMENT_INCOMPLETE)
    gates.append(
        _stage_gate(
            DrillGateName.CONTAINMENT,
            DrillStage.CONTAINMENT,
            stage_map,
            containment_reasons,
        )
    )

    authorization_reasons: list[DrillReason] = []
    if not (
        observation.authorization_approved
        and observation.authorization_id
        and observation.authorization_scope_verified
    ):
        authorization_reasons.append(DrillReason.AUTHORIZATION_MISSING)
    gates.append(
        _stage_gate(
            DrillGateName.AUTHORIZATION,
            DrillStage.AUTHORIZATION,
            stage_map,
            authorization_reasons,
        )
    )

    restoration_reasons: list[DrillReason] = []
    if not observation.restore_executed:
        restoration_reasons.append(DrillReason.RESTORE_NOT_EXECUTED)
    if not observation.authorization_approved:
        restoration_reasons.append(DrillReason.AUTHORIZATION_MISSING)
    gates.append(
        _stage_gate(
            DrillGateName.RESTORATION,
            DrillStage.RESTORATION,
            stage_map,
            restoration_reasons,
        )
    )

    checksum_reasons: list[DrillReason] = []
    if observation.restored_object_sha256 != observation.expected_object_sha256:
        checksum_reasons.append(DrillReason.OBJECT_DIGEST_MISMATCH)
    if observation.restored_manifest_sha256 != expected_identity.manifest_sha256:
        checksum_reasons.append(DrillReason.MANIFEST_MISMATCH)
    if observation.restored_release_id != expected_identity.release_id:
        checksum_reasons.append(DrillReason.RELEASE_IDENTITY_MISMATCH)
    if observation.restored_pointer_sha256 != expected_identity.pointer_sha256:
        checksum_reasons.append(DrillReason.POINTER_IDENTITY_MISMATCH)
    gates.append(
        _stage_gate(
            DrillGateName.CHECKSUM_VERIFICATION,
            DrillStage.CHECKSUM_VERIFICATION,
            stage_map,
            checksum_reasons,
        )
    )

    runtime_reasons: list[DrillReason] = []
    if observation.runtime_release_id != expected_identity.release_id:
        runtime_reasons.append(DrillReason.RELEASE_IDENTITY_MISMATCH)
    if observation.runtime_pointer_sha256 != expected_identity.pointer_sha256:
        runtime_reasons.append(DrillReason.POINTER_IDENTITY_MISMATCH)
    if observation.cache_release_id != expected_identity.release_id:
        runtime_reasons.append(DrillReason.CACHE_IDENTITY_MISMATCH)
    if not observation.public_query_verified:
        runtime_reasons.append(DrillReason.QUERY_VERIFICATION_FAILED)
    if not observation.citation_verified:
        runtime_reasons.append(DrillReason.CITATION_VERIFICATION_FAILED)
    if not observation.acl_negative_denied:
        runtime_reasons.append(DrillReason.ACL_VERIFICATION_FAILED)
    gates.append(
        _stage_gate(
            DrillGateName.RUNTIME_VERIFICATION,
            DrillStage.RUNTIME_VERIFICATION,
            stage_map,
            runtime_reasons,
        )
    )

    replay_reasons: list[DrillReason] = []
    if not observation.replay_compliant:
        replay_reasons.append(DrillReason.REPLAY_SAFETY_FAILED)
    if not observation.idempotency_verified:
        replay_reasons.append(DrillReason.IDEMPOTENCY_FAILED)
    if not (
        observation.expected_previous_verified
        and observation.expected_previous_pointer_sha256 == expected_identity.pointer_sha256
    ):
        replay_reasons.append(DrillReason.EXPECTED_PREVIOUS_FAILED)
    gates.append(
        _stage_gate(
            DrillGateName.REPLAY_VERIFICATION,
            DrillStage.REPLAY_VERIFICATION,
            stage_map,
            replay_reasons,
        )
    )

    objective_values = (
        observation.rto_state,
        observation.rpo_state,
        observation.release_unavailability_state,
        observation.rollback_state,
        observation.evidence_recovery_state,
    )
    objective_reasons: list[DrillReason] = []
    if any(value == ObjectiveState.FAILED for value in objective_values):
        objective_reasons.append(DrillReason.RECOVERY_OBJECTIVE_FAILED)
    if any(value == ObjectiveState.UNKNOWN for value in objective_values):
        objective_reasons.append(DrillReason.RECOVERY_OBJECTIVE_UNKNOWN)
    gates.append(
        _stage_gate(
            DrillGateName.RECOVERY_OBJECTIVES,
            DrillStage.RECOVERY_OBJECTIVES,
            stage_map,
            objective_reasons,
        )
    )

    audit_reasons: list[DrillReason] = []
    if not observation.audit_continuity_verified:
        audit_reasons.append(DrillReason.AUDIT_CONTINUITY_FAILED)
    if not (
        observation.permanent_ledger_open
        and not observation.permanent_ledger_appended
        and observation.observed_permanent_ledger_comments
        == observation.expected_permanent_ledger_comments
    ):
        audit_reasons.append(DrillReason.LEDGER_INVARIANT_FAILED)
    gates.append(
        _stage_gate(
            DrillGateName.AUDIT_CONTINUITY,
            DrillStage.AUDIT_CONTINUITY,
            stage_map,
            audit_reasons,
        )
    )

    closeout_reasons = (
        [] if observation.closeout_approved else [DrillReason.CLOSEOUT_NOT_APPROVED]
    )
    gates.append(
        _stage_gate(
            DrillGateName.CLOSEOUT,
            DrillStage.CLOSEOUT,
            stage_map,
            closeout_reasons,
        )
    )

    evidence_reasons = [] if observation.evidence_codes else [DrillReason.EVIDENCE_MISSING]
    gates.append(_gate(DrillGateName.EVIDENCE_COMPLETE, evidence_reasons))
    gates.append(_gate(DrillGateName.NO_WRITE_AUTHORITY, []))

    gates = sorted(gates, key=lambda item: _GATE_ORDER[item.name])
    all_reasons = sorted(
        {reason for gate in gates for reason in gate.reasons if reason != DrillReason.NONE},
        key=lambda item: item.value,
    )

    unknown = any(gate.state == GateState.UNKNOWN for gate in gates)
    blocked = any(gate.state == GateState.BLOCKED for gate in gates)
    if blocked:
        decision = CloseoutDecision.BLOCKED
    elif unknown:
        decision = CloseoutDecision.UNKNOWN
    else:
        decision = CloseoutDecision.READY_TO_CLOSE

    report = RestoreDrillReport(
        generated_at=observation.generated_at,
        identity=observation.identity,
        drill_id=observation.drill_id,
        incident_id=observation.incident_id,
        operation_id=observation.operation_id,
        stages=stages,
        gates=gates,
        reasons=all_reasons or [DrillReason.NONE],
        decision=decision,
    )
    digest = _report_digest(report)
    return report.model_copy(update={"artifact_sha256": digest})


def finalize_restore_drill_report(report: RestoreDrillReport) -> RestoreDrillReport:
    if report.artifact_sha256 is None:
        raise ValueError("restore drill report is missing artifact digest")
    expected = _report_digest(report)
    if report.artifact_sha256 != expected:
        raise ValueError("restore drill report digest mismatch")
    return report


def _stage_gate(
    gate_name: DrillGateName,
    stage: DrillStage,
    stage_map: dict[DrillStage, DrillStageEvidence],
    extra_reasons: list[DrillReason],
) -> DrillGate:
    evidence = stage_map.get(stage)
    reasons = list(extra_reasons)
    if evidence is None:
        reasons.append(DrillReason.STAGE_MISSING)
        return _gate(gate_name, reasons)
    if evidence.state == StageState.BLOCKED:
        reasons.append(DrillReason.STAGE_BLOCKED)
    elif evidence.state == StageState.UNKNOWN:
        reasons.append(DrillReason.STAGE_UNKNOWN)
    return _gate(gate_name, reasons)


def _gate(name: DrillGateName, reasons: list[DrillReason]) -> DrillGate:
    unique = sorted(set(reasons), key=lambda item: item.value)
    if DrillReason.STAGE_UNKNOWN in unique or DrillReason.RECOVERY_OBJECTIVE_UNKNOWN in unique:
        state = GateState.UNKNOWN
    elif unique:
        state = GateState.BLOCKED
    else:
        state = GateState.PASSED
    return DrillGate(name=name, state=state, reasons=unique or [DrillReason.NONE])


def _report_digest(report: RestoreDrillReport) -> str:
    payload = report.model_dump(mode="json", exclude={"artifact_sha256"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must use UTC")


def _validate_codes(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if not 1 <= len(value) <= 96:
            raise ValueError(f"{label} must be bounded")
        if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789._:-" for character in value):
            raise ValueError(f"{label} must use bounded public codes")
    _reject_forbidden(values)


def _reject_forbidden(value: object) -> None:
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=True).lower()
    if any(fragment in serialized for fragment in _FORBIDDEN_FRAGMENTS):
        raise ValueError("private or unsafe evidence is forbidden")
