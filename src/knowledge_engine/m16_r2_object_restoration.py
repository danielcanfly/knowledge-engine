from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_engine.m16_security_contracts import M16Identity

M16_R2_RESTORATION_SCHEMA = "knowledge-engine-m16-r2-object-restoration/v1"
MAX_OBJECTS = 512


class ObjectCondition(StrEnum):
    HEALTHY = "healthy"
    MISSING = "missing"
    SIZE_MISMATCH = "size_mismatch"
    DIGEST_MISMATCH = "digest_mismatch"
    ETAG_MISMATCH = "etag_mismatch"
    PROBE_FAILED = "probe_failed"


class RetainedReleaseState(StrEnum):
    TRUSTED = "trusted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class RestoreAction(StrEnum):
    NO_ACTION = "no_action"
    COPY_FROM_RETAINED_RELEASE = "copy_from_retained_release"
    BLOCKED = "blocked"


class RestoreItemState(StrEnum):
    NOT_REQUIRED = "not_required"
    PLANNED = "planned"
    VERIFIED = "verified"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class RestorationDecision(StrEnum):
    HEALTHY = "healthy"
    READY_FOR_GOVERNED_RESTORE = "ready_for_governed_restore"
    RESTORED_AND_VERIFIED = "restored_and_verified"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class RestorationReason(StrEnum):
    NONE = "none"
    ENGINE_IDENTITY_DRIFT = "engine_identity_drift"
    SOURCE_IDENTITY_DRIFT = "source_identity_drift"
    RELEASE_IDENTITY_DRIFT = "release_identity_drift"
    MANIFEST_IDENTITY_DRIFT = "manifest_identity_drift"
    POINTER_IDENTITY_DRIFT = "pointer_identity_drift"
    OBJECT_MISSING = "object_missing"
    OBJECT_SIZE_MISMATCH = "object_size_mismatch"
    OBJECT_DIGEST_MISMATCH = "object_digest_mismatch"
    OBJECT_ETAG_MISMATCH = "object_etag_mismatch"
    PROBE_FAILED = "probe_failed"
    RETAINED_RELEASE_UNTRUSTED = "retained_release_untrusted"
    RETAINED_OBJECT_MISSING = "retained_object_missing"
    RETAINED_OBJECT_MISMATCH = "retained_object_mismatch"
    RESTORE_NOT_AUTHORIZED = "restore_not_authorized"
    RESTORE_NOT_EXECUTED = "restore_not_executed"
    POST_RESTORE_OBJECT_MISMATCH = "post_restore_object_mismatch"
    MANIFEST_RECONCILIATION_FAILED = "manifest_reconciliation_failed"
    POINTER_INVARIANT_FAILED = "pointer_invariant_failed"
    CACHE_REFRESH_FAILED = "cache_refresh_failed"
    QUERY_VERIFICATION_FAILED = "query_verification_failed"
    CITATION_VERIFICATION_FAILED = "citation_verification_failed"
    ACL_NEGATIVE_VERIFICATION_FAILED = "acl_negative_verification_failed"
    EVIDENCE_MISSING = "evidence_missing"
    DUPLICATE_OBJECT = "duplicate_object"


class RestorationGateName(StrEnum):
    IDENTITY = "identity"
    DAMAGE_DETECTED = "damage_detected"
    RETAINED_RELEASE_TRUSTED = "retained_release_trusted"
    RESTORE_PLAN_COMPLETE = "restore_plan_complete"
    OBJECTS_VERIFIED = "objects_verified"
    MANIFEST_RECONCILED = "manifest_reconciled"
    POINTER_INVARIANT = "pointer_invariant"
    CACHE_RUNTIME = "cache_runtime"
    QUERY = "query"
    CITATION = "citation"
    ACL_NEGATIVE = "acl_negative"
    EVIDENCE_COMPLETE = "evidence_complete"
    NO_WRITE_AUTHORITY = "no_write_authority"


class RestorationGateState(StrEnum):
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


class ReleaseObjectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(min_length=3, max_length=160, pattern=r"^[a-z0-9][a-z0-9._/-]+$")
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    etag: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def reject_private_location(self) -> Self:
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class ObservedReleaseObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(min_length=3, max_length=160, pattern=r"^[a-z0-9][a-z0-9._/-]+$")
    present: bool
    probe_succeeded: bool = True
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    etag: str | None = Field(default=None, max_length=128)


class RetainedReleaseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retained_release_id: str = Field(min_length=8, max_length=128)
    retained_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    immutable: bool
    inventory_complete: bool
    manifest_verified: bool
    source_sha_verified: bool
    objects: list[ObservedReleaseObject] = Field(min_length=1, max_length=MAX_OBJECTS)
    evidence_codes: list[str] = Field(min_length=1, max_length=64)

    @field_validator("evidence_codes")
    @classmethod
    def validate_codes(cls, values: list[str]) -> list[str]:
        _validate_codes(values, "retained release evidence codes")
        return values

    @model_validator(mode="after")
    def validate_inventory(self) -> Self:
        _require_unique_object_ids(self.objects, "retained release inventory")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class RestorationObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drill_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    operation_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    generated_at: datetime
    identity: M16Identity
    expected_objects: list[ReleaseObjectSpec] = Field(min_length=1, max_length=MAX_OBJECTS)
    observed_objects: list[ObservedReleaseObject] = Field(min_length=1, max_length=MAX_OBJECTS)
    retained_release: RetainedReleaseEvidence
    restore_authorized: bool = False
    restore_executed: bool = False
    post_restore_objects: list[ObservedReleaseObject] = Field(default_factory=list, max_length=MAX_OBJECTS)
    manifest_reconciled: bool | None = None
    pointer_unchanged: bool | None = None
    cache_refreshed: bool | None = None
    runtime_release_id: str | None = Field(default=None, min_length=8, max_length=128)
    query_verified: bool | None = None
    citation_verified: bool | None = None
    acl_negative_verified: bool | None = None
    evidence_codes: list[str] = Field(min_length=1, max_length=64)

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("restoration generated_at must be timezone-aware UTC")
        return value

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        _validate_codes(values, "restoration evidence codes")
        return values

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        _require_unique_object_ids(self.expected_objects, "expected object inventory")
        _require_unique_object_ids(self.observed_objects, "observed object inventory")
        _require_unique_object_ids(self.post_restore_objects, "post-restore object inventory")
        if self.restore_executed and not self.restore_authorized:
            raise ValueError("restore execution cannot be claimed without authorization")
        if not self.restore_executed and self.post_restore_objects:
            raise ValueError("post-restore objects require restore execution evidence")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class ObjectRestorationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    condition: ObjectCondition
    action: RestoreAction
    state: RestoreItemState
    reasons: list[RestorationReason]


class RestorationGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RestorationGateName
    state: RestorationGateState
    failed_object_ids: list[str] = Field(default_factory=list, max_length=MAX_OBJECTS)


class M16R2RestorationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = M16_R2_RESTORATION_SCHEMA
    generated_at: datetime
    drill_id: str
    operation_id: str
    identity: M16Identity
    retained_release_id: str
    retained_release_state: RetainedReleaseState
    objects: list[ObjectRestorationResult]
    gates: list[RestorationGate]
    decision: RestorationDecision
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class M16R2RestorationAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_write_allowed: bool = False
    source_pr_allowed: bool = False
    production_write_allowed: bool = False
    pointer_mutation_allowed: bool = False
    cache_purge_allowed: bool = False
    r2_write_allowed: bool = False
    r2_copy_allowed: bool = False
    r2_delete_allowed: bool = False
    promotion_allowed: bool = False
    rollback_allowed: bool = False
    credential_rotation_allowed: bool = False
    physical_deletion_allowed: bool = False
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def reject_authority(self) -> Self:
        enabled = sorted(name for name, value in self.model_dump().items() if value)
        if enabled:
            raise ValueError(f"M16.4 is evidence-only; authority enabled: {enabled}")
        return self


def evaluate_r2_restoration(
    observation: RestorationObservation,
    *,
    expected_identity: M16Identity,
) -> M16R2RestorationReport:
    identity_ok = observation.identity == expected_identity
    retained_state = _retained_release_state(observation.retained_release)
    expected_map = {item.object_id: item for item in observation.expected_objects}
    observed_map = {item.object_id: item for item in observation.observed_objects}
    retained_map = {item.object_id: item for item in observation.retained_release.objects}
    post_map = {item.object_id: item for item in observation.post_restore_objects}

    results: list[ObjectRestorationResult] = []
    for object_id in sorted(expected_map):
        expected = expected_map[object_id]
        condition = _object_condition(expected, observed_map.get(object_id))
        reasons = _condition_reasons(condition)
        action = RestoreAction.NO_ACTION
        state = RestoreItemState.NOT_REQUIRED

        if condition != ObjectCondition.HEALTHY:
            retained = retained_map.get(object_id)
            retained_ok = _object_condition(expected, retained) == ObjectCondition.HEALTHY
            if not identity_ok or retained_state != RetainedReleaseState.TRUSTED:
                action = RestoreAction.BLOCKED
                state = RestoreItemState.BLOCKED
                reasons.append(RestorationReason.RETAINED_RELEASE_UNTRUSTED)
            elif retained is None or not retained.present:
                action = RestoreAction.BLOCKED
                state = RestoreItemState.BLOCKED
                reasons.append(RestorationReason.RETAINED_OBJECT_MISSING)
            elif not retained_ok:
                action = RestoreAction.BLOCKED
                state = RestoreItemState.BLOCKED
                reasons.append(RestorationReason.RETAINED_OBJECT_MISMATCH)
            elif not observation.restore_authorized:
                action = RestoreAction.COPY_FROM_RETAINED_RELEASE
                state = RestoreItemState.PLANNED
                reasons.append(RestorationReason.RESTORE_NOT_AUTHORIZED)
            elif not observation.restore_executed:
                action = RestoreAction.COPY_FROM_RETAINED_RELEASE
                state = RestoreItemState.PLANNED
                reasons.append(RestorationReason.RESTORE_NOT_EXECUTED)
            else:
                action = RestoreAction.COPY_FROM_RETAINED_RELEASE
                post_condition = _object_condition(expected, post_map.get(object_id))
                if post_condition == ObjectCondition.HEALTHY:
                    state = RestoreItemState.VERIFIED
                else:
                    state = RestoreItemState.BLOCKED
                    reasons.append(RestorationReason.POST_RESTORE_OBJECT_MISMATCH)

        results.append(
            ObjectRestorationResult(
                object_id=object_id,
                condition=condition,
                action=action,
                state=state,
                reasons=sorted(set(reasons), key=lambda item: item.value),
            )
        )

    gates = _build_gates(observation, results, identity_ok, retained_state)
    decision = _decision(observation, results, gates)
    report = M16R2RestorationReport(
        generated_at=observation.generated_at,
        drill_id=observation.drill_id,
        operation_id=observation.operation_id,
        identity=observation.identity,
        retained_release_id=observation.retained_release.retained_release_id,
        retained_release_state=retained_state,
        objects=results,
        gates=gates,
        decision=decision,
    )
    return finalize_r2_restoration_report(report)


def r2_restoration_report_sha256(report: M16R2RestorationReport) -> str:
    normalized = _normalized_report(report)
    payload = normalized.model_dump(mode="json")
    payload["artifact_sha256"] = None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((encoded + "\n").encode("utf-8")).hexdigest()


def finalize_r2_restoration_report(report: M16R2RestorationReport) -> M16R2RestorationReport:
    normalized = _normalized_report(report)
    digest = r2_restoration_report_sha256(normalized)
    if report.artifact_sha256 not in {None, digest}:
        raise ValueError("M16 R2 restoration report digest mismatch")
    return normalized.model_copy(update={"artifact_sha256": digest})


def _retained_release_state(evidence: RetainedReleaseEvidence) -> RetainedReleaseState:
    if not evidence.evidence_codes:
        return RetainedReleaseState.UNKNOWN
    if all(
        (
            evidence.immutable,
            evidence.inventory_complete,
            evidence.manifest_verified,
            evidence.source_sha_verified,
        )
    ):
        return RetainedReleaseState.TRUSTED
    return RetainedReleaseState.REJECTED


def _object_condition(
    expected: ReleaseObjectSpec,
    observed: ObservedReleaseObject | None,
) -> ObjectCondition:
    if observed is None or not observed.present:
        return ObjectCondition.MISSING
    if not observed.probe_succeeded:
        return ObjectCondition.PROBE_FAILED
    if observed.size_bytes != expected.size_bytes:
        return ObjectCondition.SIZE_MISMATCH
    if observed.sha256 != expected.sha256:
        return ObjectCondition.DIGEST_MISMATCH
    if expected.etag is not None and _normalize_etag(observed.etag) != _normalize_etag(expected.etag):
        return ObjectCondition.ETAG_MISMATCH
    return ObjectCondition.HEALTHY


def _condition_reasons(condition: ObjectCondition) -> list[RestorationReason]:
    mapping = {
        ObjectCondition.HEALTHY: RestorationReason.NONE,
        ObjectCondition.MISSING: RestorationReason.OBJECT_MISSING,
        ObjectCondition.SIZE_MISMATCH: RestorationReason.OBJECT_SIZE_MISMATCH,
        ObjectCondition.DIGEST_MISMATCH: RestorationReason.OBJECT_DIGEST_MISMATCH,
        ObjectCondition.ETAG_MISMATCH: RestorationReason.OBJECT_ETAG_MISMATCH,
        ObjectCondition.PROBE_FAILED: RestorationReason.PROBE_FAILED,
    }
    reason = mapping[condition]
    return [] if reason == RestorationReason.NONE else [reason]


def _build_gates(
    observation: RestorationObservation,
    results: list[ObjectRestorationResult],
    identity_ok: bool,
    retained_state: RetainedReleaseState,
) -> list[RestorationGate]:
    damaged = [item.object_id for item in results if item.condition != ObjectCondition.HEALTHY]
    blocked = [item.object_id for item in results if item.state == RestoreItemState.BLOCKED]
    unverified = [
        item.object_id
        for item in results
        if item.condition != ObjectCondition.HEALTHY and item.state != RestoreItemState.VERIFIED
    ]
    planned = [item.object_id for item in results if item.state == RestoreItemState.PLANNED]

    states = {
        RestorationGateName.IDENTITY: (
            RestorationGateState.PASSED if identity_ok else RestorationGateState.BLOCKED
        ),
        RestorationGateName.DAMAGE_DETECTED: (
            RestorationGateState.PASSED if damaged else RestorationGateState.NOT_APPLICABLE
        ),
        RestorationGateName.RETAINED_RELEASE_TRUSTED: (
            RestorationGateState.PASSED
            if retained_state == RetainedReleaseState.TRUSTED
            else RestorationGateState.BLOCKED
        ),
        RestorationGateName.RESTORE_PLAN_COMPLETE: (
            RestorationGateState.BLOCKED if blocked else RestorationGateState.PASSED
        ),
        RestorationGateName.OBJECTS_VERIFIED: (
            RestorationGateState.PASSED
            if observation.restore_executed and not unverified
            else (
                RestorationGateState.NOT_APPLICABLE
                if not observation.restore_executed
                else RestorationGateState.BLOCKED
            )
        ),
        RestorationGateName.MANIFEST_RECONCILED: _optional_gate(
            observation.restore_executed,
            observation.manifest_reconciled,
        ),
        RestorationGateName.POINTER_INVARIANT: _optional_gate(
            observation.restore_executed,
            observation.pointer_unchanged,
        ),
        RestorationGateName.CACHE_RUNTIME: _optional_gate(
            observation.restore_executed,
            observation.cache_refreshed
            and observation.runtime_release_id == observation.identity.release_id,
        ),
        RestorationGateName.QUERY: _optional_gate(
            observation.restore_executed,
            observation.query_verified,
        ),
        RestorationGateName.CITATION: _optional_gate(
            observation.restore_executed,
            observation.citation_verified,
        ),
        RestorationGateName.ACL_NEGATIVE: _optional_gate(
            observation.restore_executed,
            observation.acl_negative_verified,
        ),
        RestorationGateName.EVIDENCE_COMPLETE: (
            RestorationGateState.PASSED
            if observation.evidence_codes and observation.retained_release.evidence_codes
            else RestorationGateState.BLOCKED
        ),
        RestorationGateName.NO_WRITE_AUTHORITY: RestorationGateState.PASSED,
    }
    failed_by_gate = {
        RestorationGateName.IDENTITY: [] if identity_ok else sorted(expected.object_id for expected in observation.expected_objects),
        RestorationGateName.DAMAGE_DETECTED: [],
        RestorationGateName.RETAINED_RELEASE_TRUSTED: [] if retained_state == RetainedReleaseState.TRUSTED else damaged,
        RestorationGateName.RESTORE_PLAN_COMPLETE: blocked,
        RestorationGateName.OBJECTS_VERIFIED: unverified if observation.restore_executed else planned,
        RestorationGateName.MANIFEST_RECONCILED: damaged if observation.restore_executed and observation.manifest_reconciled is not True else [],
        RestorationGateName.POINTER_INVARIANT: damaged if observation.restore_executed and observation.pointer_unchanged is not True else [],
        RestorationGateName.CACHE_RUNTIME: damaged if observation.restore_executed and states[RestorationGateName.CACHE_RUNTIME] == RestorationGateState.BLOCKED else [],
        RestorationGateName.QUERY: damaged if observation.restore_executed and observation.query_verified is not True else [],
        RestorationGateName.CITATION: damaged if observation.restore_executed and observation.citation_verified is not True else [],
        RestorationGateName.ACL_NEGATIVE: damaged if observation.restore_executed and observation.acl_negative_verified is not True else [],
        RestorationGateName.EVIDENCE_COMPLETE: [] if observation.evidence_codes and observation.retained_release.evidence_codes else damaged,
        RestorationGateName.NO_WRITE_AUTHORITY: [],
    }
    return [
        RestorationGate(
            name=name,
            state=states[name],
            failed_object_ids=sorted(set(failed_by_gate[name])),
        )
        for name in sorted(RestorationGateName, key=lambda item: item.value)
    ]


def _decision(
    observation: RestorationObservation,
    results: list[ObjectRestorationResult],
    gates: list[RestorationGate],
) -> RestorationDecision:
    damaged = [item for item in results if item.condition != ObjectCondition.HEALTHY]
    if not damaged:
        return RestorationDecision.HEALTHY
    if any(gate.name in {RestorationGateName.IDENTITY, RestorationGateName.RETAINED_RELEASE_TRUSTED, RestorationGateName.RESTORE_PLAN_COMPLETE} and gate.state == RestorationGateState.BLOCKED for gate in gates):
        return RestorationDecision.BLOCKED
    if not observation.restore_authorized or not observation.restore_executed:
        return RestorationDecision.READY_FOR_GOVERNED_RESTORE
    if all(gate.state != RestorationGateState.BLOCKED for gate in gates):
        return RestorationDecision.RESTORED_AND_VERIFIED
    return RestorationDecision.BLOCKED


def _optional_gate(applicable: bool, value: bool | None) -> RestorationGateState:
    if not applicable:
        return RestorationGateState.NOT_APPLICABLE
    return RestorationGateState.PASSED if value is True else RestorationGateState.BLOCKED


def _normalized_report(report: M16R2RestorationReport) -> M16R2RestorationReport:
    objects = sorted(report.objects, key=lambda item: item.object_id)
    gates = sorted(report.gates, key=lambda item: item.name.value)
    return report.model_copy(update={"objects": objects, "gates": gates})


def _normalize_etag(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip('"').lower()
    if not re.fullmatch(r"[0-9a-f]{32}(?:-[0-9]+)?", cleaned):
        return None
    return cleaned


def _validate_codes(values: list[str], label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if not 3 <= len(value) <= 96:
            raise ValueError(f"{label} must be bounded")
        if not all(character.islower() or character.isdigit() or character in "._-:" for character in value):
            raise ValueError(f"{label} must contain safe code characters")


def _require_unique_object_ids(objects: list[object], label: str) -> None:
    identifiers = [getattr(item, "object_id") for item in objects]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{label} contains duplicate object IDs")


def _reject_forbidden(payload: object) -> None:
    serialized = json.dumps(payload, sort_keys=True).lower()
    for fragment in _FORBIDDEN_FRAGMENTS:
        if fragment in serialized:
            raise ValueError(f"forbidden private evidence fragment: {fragment}")
