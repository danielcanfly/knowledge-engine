from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_engine.m16_security_contracts import M16Identity

M16_PROMOTION_CONTAINMENT_SCHEMA = "knowledge-engine-m16-promotion-containment/v1"


class CandidateValidationState(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class CandidateFailureReason(StrEnum):
    NONE = "none"
    ENGINE_IDENTITY_DRIFT = "engine_identity_drift"
    SOURCE_DRIFT = "source_drift"
    RELEASE_ID_DRIFT = "release_id_drift"
    MANIFEST_MISMATCH = "manifest_mismatch"
    MISSING_ARTIFACT = "missing_artifact"
    CHECKSUM_FAILURE = "checksum_failure"
    APPROVAL_MISSING = "approval_missing"
    STALE_EXPECTED_PREVIOUS = "stale_expected_previous"
    DUPLICATE_OPERATION = "duplicate_operation"
    UNSAFE_SCOPE = "unsafe_scope"
    EVIDENCE_MISSING = "evidence_missing"


class PromotionPhase(StrEnum):
    PREVALIDATION = "prevalidation"
    ACTIVATING = "activating"
    RUNTIME_ACCEPTANCE = "runtime_acceptance"
    COMPENSATING = "compensating"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    FAILED = "failed"


class CompensationState(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ContainmentDecision(StrEnum):
    CONTAINED = "contained"
    COMPENSATION_REQUIRED = "compensation_required"
    UNCOMPENSATED = "uncompensated"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class VerificationGateName(StrEnum):
    CANDIDATE_VALIDATION = "candidate_validation"
    POINTER_RESTORED = "pointer_restored"
    RUNTIME_RESTORED = "runtime_restored"
    QUERY_VERIFIED = "query_verified"
    CITATION_VERIFIED = "citation_verified"
    ACL_NEGATIVE_VERIFIED = "acl_negative_verified"
    NO_UNAUTHORIZED_MUTATION = "no_unauthorized_mutation"
    EVIDENCE_COMPLETE = "evidence_complete"
    NO_WRITE_AUTHORITY = "no_write_authority"


class VerificationGateState(StrEnum):
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
    "s3://",
    "r2://",
    "file://",
    "http://",
    "https://",
)


class PromotionIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    candidate_release_id: str = Field(min_length=8, max_length=128)
    candidate_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_release_id: str = Field(min_length=8, max_length=128)
    previous_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_pointer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def as_m16_identity(self) -> M16Identity:
        return M16Identity(
            engine_sha=self.engine_sha,
            source_sha=self.source_sha,
            release_id=self.previous_release_id,
            manifest_sha256=self.previous_manifest_sha256,
            pointer_sha256=self.previous_pointer_sha256,
        )


class CandidateArtifactEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-z0-9._:-]+$")
    present: bool
    checksum_valid: bool


class CandidateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    operation_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    generated_at: datetime
    identity: PromotionIdentity
    observed_engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    observed_source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    observed_release_id: str = Field(min_length=8, max_length=128)
    observed_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_previous_pointer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_present: bool
    operation_seen_before: bool = False
    production_scope: bool = False
    production_mutated: bool = False
    artifacts: list[CandidateArtifactEvidence] = Field(min_length=1, max_length=64)
    evidence_codes: list[str] = Field(min_length=1, max_length=32)

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        _require_utc(value, "candidate generated_at")
        return value

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        _validate_codes(values, "candidate evidence codes")
        return values

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        artifact_ids = [artifact.artifact_id for artifact in self.artifacts]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("candidate artifact IDs must be unique")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class CandidateContainmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    operation_id: str
    state: CandidateValidationState
    reasons: list[CandidateFailureReason]
    production_mutated: bool
    decision: ContainmentDecision


class PromotionAttemptObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    operation_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    generated_at: datetime
    identity: PromotionIdentity
    phase: PromotionPhase
    exact_identity_verified: bool
    approval_verified: bool
    operation_seen_before: bool = False
    activation_occurred: bool
    runtime_acceptance_passed: bool | None = None
    compensation_state: CompensationState
    observed_pointer_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    observed_runtime_release_id: str | None = Field(default=None, min_length=8, max_length=128)
    observed_cache_release_id: str | None = Field(default=None, min_length=8, max_length=128)
    query_verified: bool | None = None
    citation_verified: bool | None = None
    acl_negative_verified: bool | None = None
    evidence_codes: list[str] = Field(min_length=1, max_length=32)

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        _require_utc(value, "promotion attempt generated_at")
        return value

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        _validate_codes(values, "promotion evidence codes")
        return values

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        if not self.activation_occurred and self.compensation_state not in {
            CompensationState.NOT_REQUIRED,
            CompensationState.UNKNOWN,
        }:
            raise ValueError("non-activated attempt cannot claim compensation execution")
        if self.runtime_acceptance_passed is True and self.compensation_state != CompensationState.NOT_REQUIRED:
            raise ValueError("successful runtime acceptance must not claim compensation")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class PromotionContainmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    operation_id: str
    phase: PromotionPhase
    compensation_state: CompensationState
    decision: ContainmentDecision
    failed_checks: list[VerificationGateName]


class VerificationGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: VerificationGateName
    state: VerificationGateState
    failed_ids: list[str] = Field(default_factory=list, max_length=128)


class M16PromotionContainmentReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = M16_PROMOTION_CONTAINMENT_SCHEMA
    generated_at: datetime
    baseline_identity: M16Identity
    candidates: list[CandidateContainmentResult] = Field(default_factory=list, max_length=128)
    attempts: list[PromotionContainmentResult] = Field(default_factory=list, max_length=128)
    gates: list[VerificationGate]
    decision: ContainmentDecision
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        _require_utc(value, "containment report generated_at")
        return value


class M16PromotionContainmentAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_write_allowed: bool = False
    source_pr_allowed: bool = False
    candidate_dispatch_allowed: bool = False
    promotion_allowed: bool = False
    rollback_allowed: bool = False
    pointer_repair_allowed: bool = False
    cache_purge_allowed: bool = False
    r2_mutation_allowed: bool = False
    credential_rotation_allowed: bool = False
    physical_deletion_allowed: bool = False
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def reject_authority(self) -> Self:
        enabled = sorted(name for name, value in self.model_dump().items() if value)
        if enabled:
            raise ValueError(f"M16.3 is evidence-only; authority enabled: {enabled}")
        return self


def evaluate_candidate(observation: CandidateObservation) -> CandidateContainmentResult:
    reasons: list[CandidateFailureReason] = []
    identity = observation.identity
    if observation.observed_engine_sha != identity.engine_sha:
        reasons.append(CandidateFailureReason.ENGINE_IDENTITY_DRIFT)
    if observation.observed_source_sha != identity.source_sha:
        reasons.append(CandidateFailureReason.SOURCE_DRIFT)
    if observation.observed_release_id != identity.candidate_release_id:
        reasons.append(CandidateFailureReason.RELEASE_ID_DRIFT)
    if observation.observed_manifest_sha256 != identity.candidate_manifest_sha256:
        reasons.append(CandidateFailureReason.MANIFEST_MISMATCH)
    if observation.observed_previous_pointer_sha256 != identity.previous_pointer_sha256:
        reasons.append(CandidateFailureReason.STALE_EXPECTED_PREVIOUS)
    if not observation.approval_present:
        reasons.append(CandidateFailureReason.APPROVAL_MISSING)
    if observation.operation_seen_before:
        reasons.append(CandidateFailureReason.DUPLICATE_OPERATION)
    if observation.production_scope:
        reasons.append(CandidateFailureReason.UNSAFE_SCOPE)
    if not observation.evidence_codes:
        reasons.append(CandidateFailureReason.EVIDENCE_MISSING)
    if any(not artifact.present for artifact in observation.artifacts):
        reasons.append(CandidateFailureReason.MISSING_ARTIFACT)
    if any(artifact.present and not artifact.checksum_valid for artifact in observation.artifacts):
        reasons.append(CandidateFailureReason.CHECKSUM_FAILURE)

    reasons = sorted(set(reasons), key=lambda item: item.value)
    state = CandidateValidationState.INVALID if reasons else CandidateValidationState.VALID
    if state == CandidateValidationState.INVALID:
        decision = (
            ContainmentDecision.UNCOMPENSATED
            if observation.production_mutated
            else ContainmentDecision.CONTAINED
        )
    else:
        decision = ContainmentDecision.NOT_APPLICABLE
    return CandidateContainmentResult(
        candidate_id=observation.candidate_id,
        operation_id=observation.operation_id,
        state=state,
        reasons=reasons,
        production_mutated=observation.production_mutated,
        decision=decision,
    )


def evaluate_promotion_attempt(
    observation: PromotionAttemptObservation,
    *,
    expected_baseline: M16Identity,
) -> PromotionContainmentResult:
    failed: list[VerificationGateName] = []
    if observation.identity.as_m16_identity() != expected_baseline:
        failed.append(VerificationGateName.EVIDENCE_COMPLETE)
    if not observation.exact_identity_verified or not observation.approval_verified:
        failed.append(VerificationGateName.EVIDENCE_COMPLETE)
    if observation.operation_seen_before:
        failed.append(VerificationGateName.EVIDENCE_COMPLETE)

    if not observation.activation_occurred:
        decision = (
            ContainmentDecision.UNKNOWN
            if failed
            else ContainmentDecision.NOT_APPLICABLE
        )
        return PromotionContainmentResult(
            attempt_id=observation.attempt_id,
            operation_id=observation.operation_id,
            phase=observation.phase,
            compensation_state=observation.compensation_state,
            decision=decision,
            failed_checks=sorted(set(failed), key=lambda item: item.value),
        )

    if observation.runtime_acceptance_passed is True:
        decision = ContainmentDecision.UNKNOWN if failed else ContainmentDecision.NOT_APPLICABLE
        return PromotionContainmentResult(
            attempt_id=observation.attempt_id,
            operation_id=observation.operation_id,
            phase=observation.phase,
            compensation_state=observation.compensation_state,
            decision=decision,
            failed_checks=sorted(set(failed), key=lambda item: item.value),
        )

    if observation.runtime_acceptance_passed is None:
        failed.append(VerificationGateName.EVIDENCE_COMPLETE)
    if observation.observed_pointer_sha256 != observation.identity.previous_pointer_sha256:
        failed.append(VerificationGateName.POINTER_RESTORED)
    if (
        observation.observed_runtime_release_id != observation.identity.previous_release_id
        or observation.observed_cache_release_id != observation.identity.previous_release_id
    ):
        failed.append(VerificationGateName.RUNTIME_RESTORED)
    if observation.query_verified is not True:
        failed.append(VerificationGateName.QUERY_VERIFIED)
    if observation.citation_verified is not True:
        failed.append(VerificationGateName.CITATION_VERIFIED)
    if observation.acl_negative_verified is not True:
        failed.append(VerificationGateName.ACL_NEGATIVE_VERIFIED)

    failed = sorted(set(failed), key=lambda item: item.value)
    if observation.compensation_state in {CompensationState.REQUIRED, CompensationState.UNKNOWN}:
        decision = ContainmentDecision.COMPENSATION_REQUIRED
    elif observation.compensation_state == CompensationState.COMPLETED and not failed:
        decision = ContainmentDecision.CONTAINED
    else:
        decision = ContainmentDecision.UNCOMPENSATED

    return PromotionContainmentResult(
        attempt_id=observation.attempt_id,
        operation_id=observation.operation_id,
        phase=observation.phase,
        compensation_state=observation.compensation_state,
        decision=decision,
        failed_checks=failed,
    )


def evaluate_containment_report(
    candidate_observations: list[CandidateObservation],
    promotion_observations: list[PromotionAttemptObservation],
    *,
    generated_at: datetime,
    baseline_identity: M16Identity,
) -> M16PromotionContainmentReport:
    _require_utc(generated_at, "report generated_at")
    if len(candidate_observations) > 128 or len(promotion_observations) > 128:
        raise ValueError("containment report inputs exceed bounded size")
    candidate_ids = [item.candidate_id for item in candidate_observations]
    attempt_ids = [item.attempt_id for item in promotion_observations]
    operation_ids = [item.operation_id for item in candidate_observations + promotion_observations]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("candidate IDs must be unique")
    if len(set(attempt_ids)) != len(attempt_ids):
        raise ValueError("promotion attempt IDs must be unique")
    if len(set(operation_ids)) != len(operation_ids):
        raise ValueError("operation IDs must be unique across containment report")

    candidates = sorted(
        (evaluate_candidate(item) for item in candidate_observations),
        key=lambda item: item.candidate_id,
    )
    attempts = sorted(
        (
            evaluate_promotion_attempt(item, expected_baseline=baseline_identity)
            for item in promotion_observations
        ),
        key=lambda item: item.attempt_id,
    )
    gates = _build_gates(candidates, attempts)
    decisions = [item.decision for item in candidates] + [item.decision for item in attempts]
    decision = _aggregate_decision(decisions)
    report = M16PromotionContainmentReport(
        generated_at=generated_at,
        baseline_identity=baseline_identity,
        candidates=candidates,
        attempts=attempts,
        gates=gates,
        decision=decision,
    )
    return finalize_containment_report(report)


def containment_report_sha256(report: M16PromotionContainmentReport) -> str:
    normalized = _normalized_report(report)
    payload = normalized.model_dump(mode="json")
    payload["artifact_sha256"] = None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((encoded + "\n").encode("utf-8")).hexdigest()


def finalize_containment_report(
    report: M16PromotionContainmentReport,
) -> M16PromotionContainmentReport:
    normalized = _normalized_report(report)
    digest = containment_report_sha256(normalized)
    if report.artifact_sha256 not in {None, digest}:
        raise ValueError("M16 promotion containment report digest mismatch")
    return normalized.model_copy(update={"artifact_sha256": digest})


def _normalized_report(
    report: M16PromotionContainmentReport,
) -> M16PromotionContainmentReport:
    return report.model_copy(
        update={
            "candidates": sorted(report.candidates, key=lambda item: item.candidate_id),
            "attempts": sorted(report.attempts, key=lambda item: item.attempt_id),
            "gates": sorted(report.gates, key=lambda item: item.name.value),
        }
    )


def _build_gates(
    candidates: list[CandidateContainmentResult],
    attempts: list[PromotionContainmentResult],
) -> list[VerificationGate]:
    failures: dict[VerificationGateName, list[str]] = {
        gate: [] for gate in VerificationGateName
    }
    for candidate in candidates:
        if candidate.state == CandidateValidationState.INVALID and candidate.production_mutated:
            failures[VerificationGateName.NO_UNAUTHORIZED_MUTATION].append(candidate.candidate_id)
        if candidate.decision == ContainmentDecision.UNKNOWN:
            failures[VerificationGateName.EVIDENCE_COMPLETE].append(candidate.candidate_id)
    for attempt in attempts:
        for gate in attempt.failed_checks:
            failures[gate].append(attempt.attempt_id)
        if attempt.decision in {
            ContainmentDecision.UNCOMPENSATED,
            ContainmentDecision.COMPENSATION_REQUIRED,
            ContainmentDecision.UNKNOWN,
        }:
            failures[VerificationGateName.CANDIDATE_VALIDATION].append(attempt.attempt_id)
    return [
        VerificationGate(
            name=gate,
            state=(
                VerificationGateState.BLOCKED
                if failures[gate]
                else VerificationGateState.PASSED
            ),
            failed_ids=sorted(set(failures[gate])),
        )
        for gate in sorted(VerificationGateName, key=lambda item: item.value)
    ]


def _aggregate_decision(decisions: list[ContainmentDecision]) -> ContainmentDecision:
    if not decisions:
        return ContainmentDecision.NOT_APPLICABLE
    precedence = (
        ContainmentDecision.UNCOMPENSATED,
        ContainmentDecision.COMPENSATION_REQUIRED,
        ContainmentDecision.UNKNOWN,
        ContainmentDecision.CONTAINED,
        ContainmentDecision.NOT_APPLICABLE,
    )
    return next(decision for decision in precedence if decision in decisions)


def _require_utc(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be timezone-aware UTC")


def _validate_codes(values: list[str], label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if not 3 <= len(value) <= 96:
            raise ValueError(f"{label} must be bounded")
        if not all(character.islower() or character.isdigit() or character in "._-:" for character in value):
            raise ValueError(f"{label} must contain only safe code characters")


def _reject_forbidden(payload: object) -> None:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).lower()
    if any(fragment in encoded for fragment in _FORBIDDEN_FRAGMENTS):
        raise ValueError("promotion containment evidence contains forbidden private material")
