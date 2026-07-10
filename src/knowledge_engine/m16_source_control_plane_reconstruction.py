from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_engine.m16_security_contracts import M16Identity

M16_SOURCE_RECONSTRUCTION_SCHEMA = "knowledge-engine-m16-source-control-plane-reconstruction/v1"
MAX_COMPONENTS = 32


class SourceIntegrityState(StrEnum):
    HEALTHY = "healthy"
    DRIFTED = "drifted"
    CORRUPTED = "corrupted"
    UNKNOWN = "unknown"


class TrustedGitState(StrEnum):
    TRUSTED = "trusted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class ReconstructionComponentKind(StrEnum):
    BATCH_REGISTRY = "batch_registry"
    APPROVALS = "approvals"
    LIFECYCLE_STATE = "lifecycle_state"
    PRODUCTION_IDENTITY = "production_identity"
    POINTER_IDENTITY = "pointer_identity"
    ARTIFACT_INVENTORY = "artifact_inventory"
    LEDGER_CONTINUITY = "ledger_continuity"
    EPHEMERAL_STATE = "ephemeral_state"


class ReconstructionComponentState(StrEnum):
    VERIFIED = "verified"
    RECONSTRUCTABLE = "reconstructable"
    PARTIAL = "partial"
    MISSING = "missing"
    UNRECOVERABLE = "unrecoverable"
    UNKNOWN = "unknown"


class ReconstructionDecision(StrEnum):
    HEALTHY = "healthy"
    READY_FOR_GOVERNED_RESTORE = "ready_for_governed_restore"
    RECONSTRUCTED_AND_VERIFIED = "reconstructed_and_verified"
    PARTIALLY_RECONSTRUCTED = "partially_reconstructed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class ReconstructionReason(StrEnum):
    NONE = "none"
    ENGINE_IDENTITY_DRIFT = "engine_identity_drift"
    SOURCE_HEAD_DRIFT = "source_head_drift"
    SOURCE_HISTORY_DIVERGED = "source_history_diverged"
    TRUSTED_COMMIT_UNREACHABLE = "trusted_commit_unreachable"
    REVIEW_EVIDENCE_MISSING = "review_evidence_missing"
    COMMIT_SIGNATURE_UNVERIFIED = "commit_signature_unverified"
    TRUSTED_SOURCE_SHA_MISMATCH = "trusted_source_sha_mismatch"
    RESTORE_NOT_AUTHORIZED = "restore_not_authorized"
    RESTORE_NOT_EXECUTED = "restore_not_executed"
    RESTORED_SOURCE_MISMATCH = "restored_source_mismatch"
    REBUILD_EVIDENCE_MISSING = "rebuild_evidence_missing"
    REBUILD_SOURCE_MISMATCH = "rebuild_source_mismatch"
    REBUILD_MANIFEST_MISMATCH = "rebuild_manifest_mismatch"
    COMPONENT_EVIDENCE_MISSING = "component_evidence_missing"
    COMPONENT_IDENTITY_MISMATCH = "component_identity_mismatch"
    COMPONENT_INCOMPLETE = "component_incomplete"
    EPHEMERAL_STATE_UNRECOVERABLE = "ephemeral_state_unrecoverable"
    LEDGER_CONTINUITY_FAILED = "ledger_continuity_failed"
    EVIDENCE_MISSING = "evidence_missing"


class ReconstructionGateName(StrEnum):
    IDENTITY = "identity"
    SOURCE_INTEGRITY = "source_integrity"
    TRUSTED_GIT = "trusted_git"
    RESTORE_AUTHORIZATION = "restore_authorization"
    RESTORED_SOURCE = "restored_source"
    DETERMINISTIC_REBUILD = "deterministic_rebuild"
    BATCH_REGISTRY = "batch_registry"
    APPROVALS = "approvals"
    LIFECYCLE_STATE = "lifecycle_state"
    PRODUCTION_IDENTITY = "production_identity"
    POINTER_IDENTITY = "pointer_identity"
    ARTIFACT_INVENTORY = "artifact_inventory"
    LEDGER_CONTINUITY = "ledger_continuity"
    EPHEMERAL_GAPS = "ephemeral_gaps"
    EVIDENCE_COMPLETE = "evidence_complete"
    NO_WRITE_AUTHORITY = "no_write_authority"


class ReconstructionGateState(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"
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
    "git://",
    "ssh://",
    "file://",
    "s3://",
    "r2://",
    "http://",
    "https://",
)

_CRITICAL_COMPONENTS = {
    ReconstructionComponentKind.BATCH_REGISTRY,
    ReconstructionComponentKind.APPROVALS,
    ReconstructionComponentKind.LIFECYCLE_STATE,
    ReconstructionComponentKind.PRODUCTION_IDENTITY,
    ReconstructionComponentKind.POINTER_IDENTITY,
    ReconstructionComponentKind.ARTIFACT_INVENTORY,
    ReconstructionComponentKind.LEDGER_CONTINUITY,
}

_GATE_FOR_COMPONENT = {
    ReconstructionComponentKind.BATCH_REGISTRY: ReconstructionGateName.BATCH_REGISTRY,
    ReconstructionComponentKind.APPROVALS: ReconstructionGateName.APPROVALS,
    ReconstructionComponentKind.LIFECYCLE_STATE: ReconstructionGateName.LIFECYCLE_STATE,
    ReconstructionComponentKind.PRODUCTION_IDENTITY: ReconstructionGateName.PRODUCTION_IDENTITY,
    ReconstructionComponentKind.POINTER_IDENTITY: ReconstructionGateName.POINTER_IDENTITY,
    ReconstructionComponentKind.ARTIFACT_INVENTORY: ReconstructionGateName.ARTIFACT_INVENTORY,
    ReconstructionComponentKind.LEDGER_CONTINUITY: ReconstructionGateName.LEDGER_CONTINUITY,
    ReconstructionComponentKind.EPHEMERAL_STATE: ReconstructionGateName.EPHEMERAL_GAPS,
}


class TrustedGitEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trusted_source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    reachable_from_trusted_history: bool
    review_evidence_complete: bool
    commit_signature_verified: bool
    trusted_history_intact: bool
    evidence_codes: list[str] = Field(min_length=1, max_length=32)

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        _validate_codes(values, "trusted Git evidence codes")
        return values

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class ReconstructionComponentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ReconstructionComponentKind
    evidence_present: bool
    identity_verified: bool
    complete: bool
    reconstructed: bool = False
    declared_ephemeral: bool = False
    evidence_codes: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        _validate_codes(values, "component evidence codes", allow_empty=True)
        return values

    @model_validator(mode="after")
    def validate_component(self) -> Self:
        if self.kind == ReconstructionComponentKind.EPHEMERAL_STATE:
            if not self.declared_ephemeral:
                raise ValueError("ephemeral state component must be declared ephemeral")
        elif self.declared_ephemeral:
            raise ValueError("only ephemeral state may be declared ephemeral")
        if self.reconstructed and not self.evidence_present:
            raise ValueError("reconstructed component requires evidence")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class SourceControlPlaneObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drill_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    operation_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    generated_at: datetime
    identity: M16Identity
    observed_source_head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_history_diverged: bool
    trusted_git: TrustedGitEvidence
    source_restore_authorized: bool = False
    source_restore_executed: bool = False
    restored_source_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    rebuild_executed: bool = False
    rebuilt_source_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    rebuilt_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    components: list[ReconstructionComponentEvidence] = Field(
        min_length=1,
        max_length=MAX_COMPONENTS,
    )
    evidence_codes: list[str] = Field(min_length=1, max_length=64)

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("reconstruction generated_at must be timezone-aware UTC")
        return value

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        _validate_codes(values, "reconstruction evidence codes")
        return values

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        kinds = [component.kind for component in self.components]
        if len(kinds) != len(set(kinds)):
            raise ValueError("reconstruction component kinds must be unique")
        missing_critical = sorted(
            kind.value for kind in _CRITICAL_COMPONENTS.difference(kinds)
        )
        if missing_critical:
            raise ValueError(f"missing critical reconstruction components: {missing_critical}")
        if self.source_restore_executed and not self.source_restore_authorized:
            raise ValueError("Source restoration cannot be claimed without authorization")
        if self.source_restore_executed and self.restored_source_sha is None:
            raise ValueError("Source restoration requires restored Source SHA evidence")
        if not self.source_restore_executed and self.restored_source_sha is not None:
            raise ValueError("restored Source SHA requires restoration execution evidence")
        if self.rebuild_executed:
            if self.rebuilt_source_sha is None or self.rebuilt_manifest_sha256 is None:
                raise ValueError("rebuild execution requires Source and manifest evidence")
        elif self.rebuilt_source_sha is not None or self.rebuilt_manifest_sha256 is not None:
            raise ValueError("rebuild identities require rebuild execution evidence")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class ReconstructionComponentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ReconstructionComponentKind
    state: ReconstructionComponentState
    reasons: list[ReconstructionReason]


class ReconstructionGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ReconstructionGateName
    state: ReconstructionGateState
    reason_codes: list[ReconstructionReason] = Field(default_factory=list, max_length=32)


class M16SourceControlPlaneReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = M16_SOURCE_RECONSTRUCTION_SCHEMA
    generated_at: datetime
    drill_id: str
    operation_id: str
    identity: M16Identity
    source_state: SourceIntegrityState
    trusted_git_state: TrustedGitState
    components: list[ReconstructionComponentResult]
    gates: list[ReconstructionGate]
    decision: ReconstructionDecision
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class M16SourceControlPlaneAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_write_allowed: bool = False
    source_reset_allowed: bool = False
    source_revert_allowed: bool = False
    branch_update_allowed: bool = False
    source_pr_allowed: bool = False
    candidate_promotion_allowed: bool = False
    production_write_allowed: bool = False
    pointer_mutation_allowed: bool = False
    cache_purge_allowed: bool = False
    r2_mutation_allowed: bool = False
    rollback_allowed: bool = False
    credential_rotation_allowed: bool = False
    physical_deletion_allowed: bool = False
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def reject_authority(self) -> Self:
        enabled = sorted(name for name, value in self.model_dump().items() if value)
        if enabled:
            raise ValueError(f"M16.5 is evidence-only; authority enabled: {enabled}")
        return self


def evaluate_source_control_plane_reconstruction(
    observation: SourceControlPlaneObservation,
    *,
    expected_identity: M16Identity,
) -> M16SourceControlPlaneReport:
    identity_ok = observation.identity == expected_identity
    source_state = _source_state(observation, expected_identity)
    trusted_git_state = _trusted_git_state(observation.trusted_git, expected_identity)
    component_results = [
        _evaluate_component(component)
        for component in sorted(observation.components, key=lambda item: item.kind.value)
    ]
    gates = _build_gates(
        observation,
        expected_identity=expected_identity,
        identity_ok=identity_ok,
        source_state=source_state,
        trusted_git_state=trusted_git_state,
        components=component_results,
    )
    decision = _decision(
        observation,
        identity_ok=identity_ok,
        source_state=source_state,
        trusted_git_state=trusted_git_state,
        components=component_results,
        gates=gates,
    )
    report = M16SourceControlPlaneReport(
        generated_at=observation.generated_at,
        drill_id=observation.drill_id,
        operation_id=observation.operation_id,
        identity=observation.identity,
        source_state=source_state,
        trusted_git_state=trusted_git_state,
        components=component_results,
        gates=gates,
        decision=decision,
    )
    return finalize_source_control_plane_report(report)


def source_control_plane_report_sha256(report: M16SourceControlPlaneReport) -> str:
    normalized = _normalized_report(report)
    payload = normalized.model_dump(mode="json")
    payload["artifact_sha256"] = None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((encoded + "\n").encode("utf-8")).hexdigest()


def finalize_source_control_plane_report(
    report: M16SourceControlPlaneReport,
) -> M16SourceControlPlaneReport:
    normalized = _normalized_report(report)
    digest = source_control_plane_report_sha256(normalized)
    if report.artifact_sha256 not in {None, digest}:
        raise ValueError("M16 Source/control-plane report digest mismatch")
    return normalized.model_copy(update={"artifact_sha256": digest})


def _source_state(
    observation: SourceControlPlaneObservation,
    expected_identity: M16Identity,
) -> SourceIntegrityState:
    if observation.source_history_diverged:
        return SourceIntegrityState.CORRUPTED
    if observation.observed_source_head_sha != expected_identity.source_sha:
        return SourceIntegrityState.DRIFTED
    return SourceIntegrityState.HEALTHY


def _trusted_git_state(
    evidence: TrustedGitEvidence,
    expected_identity: M16Identity,
) -> TrustedGitState:
    if not evidence.evidence_codes:
        return TrustedGitState.UNKNOWN
    trusted = all(
        (
            evidence.trusted_source_sha == expected_identity.source_sha,
            evidence.reachable_from_trusted_history,
            evidence.review_evidence_complete,
            evidence.commit_signature_verified,
            evidence.trusted_history_intact,
        )
    )
    return TrustedGitState.TRUSTED if trusted else TrustedGitState.REJECTED


def _evaluate_component(
    component: ReconstructionComponentEvidence,
) -> ReconstructionComponentResult:
    reasons: list[ReconstructionReason] = []
    if component.kind == ReconstructionComponentKind.EPHEMERAL_STATE:
        if component.evidence_present and component.complete:
            state = ReconstructionComponentState.VERIFIED
        else:
            state = ReconstructionComponentState.UNRECOVERABLE
            reasons.append(ReconstructionReason.EPHEMERAL_STATE_UNRECOVERABLE)
    elif not component.evidence_present:
        state = ReconstructionComponentState.MISSING
        reasons.append(ReconstructionReason.COMPONENT_EVIDENCE_MISSING)
    elif not component.identity_verified:
        state = ReconstructionComponentState.PARTIAL
        reasons.append(ReconstructionReason.COMPONENT_IDENTITY_MISMATCH)
    elif not component.complete:
        state = ReconstructionComponentState.PARTIAL
        reasons.append(ReconstructionReason.COMPONENT_INCOMPLETE)
    elif component.reconstructed:
        state = ReconstructionComponentState.VERIFIED
    else:
        state = ReconstructionComponentState.RECONSTRUCTABLE
    if (
        component.kind == ReconstructionComponentKind.LEDGER_CONTINUITY
        and state in {
            ReconstructionComponentState.MISSING,
            ReconstructionComponentState.PARTIAL,
            ReconstructionComponentState.UNKNOWN,
        }
    ):
        reasons.append(ReconstructionReason.LEDGER_CONTINUITY_FAILED)
    return ReconstructionComponentResult(
        kind=component.kind,
        state=state,
        reasons=sorted(set(reasons), key=lambda item: item.value),
    )


def _build_gates(
    observation: SourceControlPlaneObservation,
    *,
    expected_identity: M16Identity,
    identity_ok: bool,
    source_state: SourceIntegrityState,
    trusted_git_state: TrustedGitState,
    components: list[ReconstructionComponentResult],
) -> list[ReconstructionGate]:
    gates: list[ReconstructionGate] = []
    gates.append(
        _gate(
            ReconstructionGateName.IDENTITY,
            identity_ok,
            [ReconstructionReason.ENGINE_IDENTITY_DRIFT],
        )
    )
    source_reasons: list[ReconstructionReason] = []
    if observation.observed_source_head_sha != expected_identity.source_sha:
        source_reasons.append(ReconstructionReason.SOURCE_HEAD_DRIFT)
    if observation.source_history_diverged:
        source_reasons.append(ReconstructionReason.SOURCE_HISTORY_DIVERGED)
    gates.append(
        ReconstructionGate(
            name=ReconstructionGateName.SOURCE_INTEGRITY,
            state=(
                ReconstructionGateState.PASSED
                if source_state == SourceIntegrityState.HEALTHY
                else ReconstructionGateState.BLOCKED
            ),
            reason_codes=sorted(source_reasons, key=lambda item: item.value),
        )
    )
    trusted_reasons = _trusted_git_reasons(observation.trusted_git, expected_identity)
    gates.append(
        ReconstructionGate(
            name=ReconstructionGateName.TRUSTED_GIT,
            state=(
                ReconstructionGateState.PASSED
                if trusted_git_state == TrustedGitState.TRUSTED
                else ReconstructionGateState.BLOCKED
            ),
            reason_codes=trusted_reasons,
        )
    )
    restore_required = source_state != SourceIntegrityState.HEALTHY
    if not restore_required:
        restore_state = ReconstructionGateState.NOT_APPLICABLE
        restore_reasons: list[ReconstructionReason] = []
    elif observation.source_restore_authorized:
        restore_state = ReconstructionGateState.PASSED
        restore_reasons = []
    else:
        restore_state = ReconstructionGateState.BLOCKED
        restore_reasons = [ReconstructionReason.RESTORE_NOT_AUTHORIZED]
    gates.append(
        ReconstructionGate(
            name=ReconstructionGateName.RESTORE_AUTHORIZATION,
            state=restore_state,
            reason_codes=restore_reasons,
        )
    )
    if not observation.source_restore_executed:
        restored_state = (
            ReconstructionGateState.NOT_APPLICABLE
            if not restore_required
            else ReconstructionGateState.BLOCKED
        )
        restored_reasons = (
            [] if not restore_required else [ReconstructionReason.RESTORE_NOT_EXECUTED]
        )
    elif observation.restored_source_sha == expected_identity.source_sha:
        restored_state = ReconstructionGateState.PASSED
        restored_reasons = []
    else:
        restored_state = ReconstructionGateState.BLOCKED
        restored_reasons = [ReconstructionReason.RESTORED_SOURCE_MISMATCH]
    gates.append(
        ReconstructionGate(
            name=ReconstructionGateName.RESTORED_SOURCE,
            state=restored_state,
            reason_codes=restored_reasons,
        )
    )
    rebuild_ok = (
        observation.rebuild_executed
        and observation.rebuilt_source_sha == expected_identity.source_sha
        and observation.rebuilt_manifest_sha256 == expected_identity.manifest_sha256
    )
    rebuild_reasons: list[ReconstructionReason] = []
    if not observation.rebuild_executed:
        rebuild_reasons.append(ReconstructionReason.REBUILD_EVIDENCE_MISSING)
    else:
        if observation.rebuilt_source_sha != expected_identity.source_sha:
            rebuild_reasons.append(ReconstructionReason.REBUILD_SOURCE_MISMATCH)
        if observation.rebuilt_manifest_sha256 != expected_identity.manifest_sha256:
            rebuild_reasons.append(ReconstructionReason.REBUILD_MANIFEST_MISMATCH)
    gates.append(
        ReconstructionGate(
            name=ReconstructionGateName.DETERMINISTIC_REBUILD,
            state=(
                ReconstructionGateState.PASSED
                if rebuild_ok
                else ReconstructionGateState.BLOCKED
            ),
            reason_codes=sorted(rebuild_reasons, key=lambda item: item.value),
        )
    )
    for component in components:
        gate_name = _GATE_FOR_COMPONENT[component.kind]
        if component.kind == ReconstructionComponentKind.EPHEMERAL_STATE:
            state = (
                ReconstructionGateState.PASSED
                if component.state == ReconstructionComponentState.VERIFIED
                else ReconstructionGateState.BLOCKED
            )
        else:
            state = (
                ReconstructionGateState.PASSED
                if component.state
                in {
                    ReconstructionComponentState.VERIFIED,
                    ReconstructionComponentState.RECONSTRUCTABLE,
                }
                else ReconstructionGateState.BLOCKED
            )
        gates.append(
            ReconstructionGate(
                name=gate_name,
                state=state,
                reason_codes=component.reasons,
            )
        )
    evidence_complete = bool(observation.evidence_codes) and bool(
        observation.trusted_git.evidence_codes
    )
    gates.append(
        _gate(
            ReconstructionGateName.EVIDENCE_COMPLETE,
            evidence_complete,
            [ReconstructionReason.EVIDENCE_MISSING],
        )
    )
    gates.append(
        ReconstructionGate(
            name=ReconstructionGateName.NO_WRITE_AUTHORITY,
            state=ReconstructionGateState.PASSED,
            reason_codes=[],
        )
    )
    return sorted(gates, key=lambda item: item.name.value)


def _decision(
    observation: SourceControlPlaneObservation,
    *,
    identity_ok: bool,
    source_state: SourceIntegrityState,
    trusted_git_state: TrustedGitState,
    components: list[ReconstructionComponentResult],
    gates: list[ReconstructionGate],
) -> ReconstructionDecision:
    if not identity_ok or trusted_git_state != TrustedGitState.TRUSTED:
        return ReconstructionDecision.BLOCKED
    critical = [item for item in components if item.kind in _CRITICAL_COMPONENTS]
    critical_ready = all(
        item.state
        in {
            ReconstructionComponentState.VERIFIED,
            ReconstructionComponentState.RECONSTRUCTABLE,
        }
        for item in critical
    )
    if not critical_ready:
        return ReconstructionDecision.BLOCKED
    if source_state == SourceIntegrityState.HEALTHY and not observation.source_restore_executed:
        if all(item.state == ReconstructionComponentState.VERIFIED for item in critical):
            return ReconstructionDecision.HEALTHY
    if not observation.source_restore_executed or not observation.rebuild_executed:
        return ReconstructionDecision.READY_FOR_GOVERNED_RESTORE
    hard_gate_names = {
        ReconstructionGateName.IDENTITY,
        ReconstructionGateName.TRUSTED_GIT,
        ReconstructionGateName.RESTORE_AUTHORIZATION,
        ReconstructionGateName.RESTORED_SOURCE,
        ReconstructionGateName.DETERMINISTIC_REBUILD,
        ReconstructionGateName.BATCH_REGISTRY,
        ReconstructionGateName.APPROVALS,
        ReconstructionGateName.LIFECYCLE_STATE,
        ReconstructionGateName.PRODUCTION_IDENTITY,
        ReconstructionGateName.POINTER_IDENTITY,
        ReconstructionGateName.ARTIFACT_INVENTORY,
        ReconstructionGateName.LEDGER_CONTINUITY,
        ReconstructionGateName.EVIDENCE_COMPLETE,
        ReconstructionGateName.NO_WRITE_AUTHORITY,
    }
    if any(
        gate.state != ReconstructionGateState.PASSED
        for gate in gates
        if gate.name in hard_gate_names
    ):
        return ReconstructionDecision.BLOCKED
    ephemeral_gap = any(
        item.kind == ReconstructionComponentKind.EPHEMERAL_STATE
        and item.state == ReconstructionComponentState.UNRECOVERABLE
        for item in components
    )
    if ephemeral_gap:
        return ReconstructionDecision.PARTIALLY_RECONSTRUCTED
    return ReconstructionDecision.RECONSTRUCTED_AND_VERIFIED


def _trusted_git_reasons(
    evidence: TrustedGitEvidence,
    expected_identity: M16Identity,
) -> list[ReconstructionReason]:
    reasons: list[ReconstructionReason] = []
    if evidence.trusted_source_sha != expected_identity.source_sha:
        reasons.append(ReconstructionReason.TRUSTED_SOURCE_SHA_MISMATCH)
    if not evidence.reachable_from_trusted_history:
        reasons.append(ReconstructionReason.TRUSTED_COMMIT_UNREACHABLE)
    if not evidence.review_evidence_complete:
        reasons.append(ReconstructionReason.REVIEW_EVIDENCE_MISSING)
    if not evidence.commit_signature_verified:
        reasons.append(ReconstructionReason.COMMIT_SIGNATURE_UNVERIFIED)
    if not evidence.trusted_history_intact:
        reasons.append(ReconstructionReason.SOURCE_HISTORY_DIVERGED)
    return sorted(reasons, key=lambda item: item.value)


def _gate(
    name: ReconstructionGateName,
    passed: bool,
    reasons: list[ReconstructionReason],
) -> ReconstructionGate:
    return ReconstructionGate(
        name=name,
        state=(ReconstructionGateState.PASSED if passed else ReconstructionGateState.BLOCKED),
        reason_codes=[] if passed else reasons,
    )


def _normalized_report(
    report: M16SourceControlPlaneReport,
) -> M16SourceControlPlaneReport:
    components = sorted(report.components, key=lambda item: item.kind.value)
    normalized_components = [
        item.model_copy(
            update={"reasons": sorted(set(item.reasons), key=lambda reason: reason.value)}
        )
        for item in components
    ]
    gates = sorted(report.gates, key=lambda item: item.name.value)
    normalized_gates = [
        item.model_copy(
            update={
                "reason_codes": sorted(
                    set(item.reason_codes),
                    key=lambda reason: reason.value,
                )
            }
        )
        for item in gates
    ]
    return report.model_copy(
        update={"components": normalized_components, "gates": normalized_gates}
    )


def _validate_codes(values: list[str], label: str, *, allow_empty: bool = False) -> None:
    if not values and not allow_empty:
        raise ValueError(f"{label} must not be empty")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if not 3 <= len(value) <= 96:
            raise ValueError(f"{label} must be between 3 and 96 characters")
        if not all(character.islower() or character.isdigit() or character in "._:-" for character in value):
            raise ValueError(f"{label} must be a bounded lowercase code")


def _reject_forbidden(payload: object) -> None:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False).lower()
    found = sorted(fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in serialized)
    if found:
        raise ValueError(f"private or unsafe reconstruction evidence rejected: {found}")
