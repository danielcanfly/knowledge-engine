from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

M15_GOVERNANCE_HEALTH_SCHEMA = "knowledge-engine-governance-health/v1"


class GovernanceHealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class LifecyclePhase(StrEnum):
    REGISTERED = "registered"
    CLAIMED = "claimed"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_EVIDENCE = "awaiting_evidence"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GovernanceIssueCode(StrEnum):
    MISSING_OWNER = "missing_owner"
    LEASE_EXPIRED = "lease_expired"
    HEARTBEAT_STALE = "heartbeat_stale"
    HEARTBEAT_IN_FUTURE = "heartbeat_in_future"
    APPROVAL_MISSING = "approval_missing"
    EVIDENCE_MISSING = "evidence_missing"
    RETRY_EXHAUSTED = "retry_exhausted"
    DEPENDENCY_BLOCKED = "dependency_blocked"
    IDENTITY_DRIFT = "identity_drift"
    DUPLICATE_WORK_ID = "duplicate_work_id"
    TERMINAL_STATE_INCONSISTENT = "terminal_state_inconsistent"
    TIMESTAMP_INVALID = "timestamp_invalid"


class GovernanceWorkItem(BaseModel):
    work_id: str = Field(min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9._:-]+$")
    phase: LifecyclePhase
    owner_id: str | None = Field(default=None, max_length=128)
    engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    expected_engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    updated_at: datetime
    heartbeat_at: datetime | None = None
    lease_expires_at: datetime | None = None
    approval_required: bool = False
    approval_recorded: bool = False
    evidence_required: bool = False
    evidence_recorded: bool = False
    retry_count: int = Field(default=0, ge=0)
    retry_limit: int = Field(default=3, ge=0, le=100)
    dependencies_satisfied: bool = True
    terminal_result_recorded: bool = False

    @field_validator("created_at", "updated_at", "heartbeat_at", "lease_expires_at")
    @classmethod
    def require_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
            raise ValueError("governance timestamps must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def validate_ordering(self) -> "GovernanceWorkItem":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self


class GovernanceHealthIssue(BaseModel):
    code: GovernanceIssueCode
    state: GovernanceHealthState
    work_id: str


class GovernanceHealthReport(BaseModel):
    schema_version: str = M15_GOVERNANCE_HEALTH_SCHEMA
    generated_at: datetime
    overall_state: GovernanceHealthState
    issues: list[GovernanceHealthIssue]
    work_count: int = Field(ge=0)
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("generated_at must be timezone-aware UTC")
        return value


class GovernanceAuthority(BaseModel):
    automatic_retry_allowed: bool = False
    automatic_reassignment_allowed: bool = False
    automatic_approval_allowed: bool = False
    automatic_close_allowed: bool = False
    automatic_merge_allowed: bool = False
    promotion_allowed: bool = False
    rollback_allowed: bool = False
    source_write_allowed: bool = False
    production_write_allowed: bool = False
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def reject_authority(self) -> "GovernanceAuthority":
        enabled = sorted(name for name, value in self.model_dump().items() if value)
        if enabled:
            raise ValueError(f"M15.4 is read-only; authority enabled: {enabled}")
        return self


def _state_for(code: GovernanceIssueCode) -> GovernanceHealthState:
    if code in {
        GovernanceIssueCode.IDENTITY_DRIFT,
        GovernanceIssueCode.DUPLICATE_WORK_ID,
        GovernanceIssueCode.TERMINAL_STATE_INCONSISTENT,
        GovernanceIssueCode.RETRY_EXHAUSTED,
    }:
        return GovernanceHealthState.UNHEALTHY
    if code in {GovernanceIssueCode.TIMESTAMP_INVALID, GovernanceIssueCode.HEARTBEAT_IN_FUTURE}:
        return GovernanceHealthState.UNKNOWN
    return GovernanceHealthState.DEGRADED


def evaluate_governance_health(
    items: list[GovernanceWorkItem],
    *,
    generated_at: datetime,
    heartbeat_stale_after: timedelta = timedelta(minutes=30),
) -> GovernanceHealthReport:
    if generated_at.tzinfo is None or generated_at.utcoffset() != timedelta(0):
        raise ValueError("generated_at must be timezone-aware UTC")
    issues: list[GovernanceHealthIssue] = []
    seen: set[str] = set()
    terminal = {LifecyclePhase.COMPLETED, LifecyclePhase.FAILED, LifecyclePhase.CANCELLED}
    active = {LifecyclePhase.CLAIMED, LifecyclePhase.RUNNING}

    for item in items:
        codes: list[GovernanceIssueCode] = []
        if item.work_id in seen:
            codes.append(GovernanceIssueCode.DUPLICATE_WORK_ID)
        seen.add(item.work_id)
        if item.phase in active and not item.owner_id:
            codes.append(GovernanceIssueCode.MISSING_OWNER)
        if item.lease_expires_at and item.phase in active and item.lease_expires_at < generated_at:
            codes.append(GovernanceIssueCode.LEASE_EXPIRED)
        if item.heartbeat_at and item.heartbeat_at > generated_at:
            codes.append(GovernanceIssueCode.HEARTBEAT_IN_FUTURE)
        elif item.phase in active and (
            item.heartbeat_at is None or generated_at - item.heartbeat_at > heartbeat_stale_after
        ):
            codes.append(GovernanceIssueCode.HEARTBEAT_STALE)
        if item.approval_required and not item.approval_recorded:
            codes.append(GovernanceIssueCode.APPROVAL_MISSING)
        if item.evidence_required and not item.evidence_recorded:
            codes.append(GovernanceIssueCode.EVIDENCE_MISSING)
        if item.retry_count >= item.retry_limit and item.phase == LifecyclePhase.FAILED:
            codes.append(GovernanceIssueCode.RETRY_EXHAUSTED)
        if not item.dependencies_satisfied and item.phase != LifecyclePhase.BLOCKED:
            codes.append(GovernanceIssueCode.DEPENDENCY_BLOCKED)
        if item.engine_sha != item.expected_engine_sha:
            codes.append(GovernanceIssueCode.IDENTITY_DRIFT)
        if (item.phase in terminal) != item.terminal_result_recorded:
            codes.append(GovernanceIssueCode.TERMINAL_STATE_INCONSISTENT)
        for code in codes:
            issues.append(GovernanceHealthIssue(code=code, state=_state_for(code), work_id=item.work_id))

    issues.sort(key=lambda issue: (issue.code.value, issue.work_id, issue.state.value))
    states = {issue.state for issue in issues}
    if GovernanceHealthState.UNHEALTHY in states:
        overall = GovernanceHealthState.UNHEALTHY
    elif GovernanceHealthState.UNKNOWN in states:
        overall = GovernanceHealthState.UNKNOWN
    elif GovernanceHealthState.DEGRADED in states:
        overall = GovernanceHealthState.DEGRADED
    else:
        overall = GovernanceHealthState.HEALTHY
    report = GovernanceHealthReport(
        generated_at=generated_at,
        overall_state=overall,
        issues=issues,
        work_count=len(items),
    )
    return finalize_governance_report(report)


def governance_report_sha256(report: GovernanceHealthReport) -> str:
    payload = report.model_dump(mode="json")
    payload["artifact_sha256"] = None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def finalize_governance_report(report: GovernanceHealthReport) -> GovernanceHealthReport:
    digest = governance_report_sha256(report)
    if report.artifact_sha256 not in {None, digest}:
        raise ValueError("governance report digest mismatch")
    return report.model_copy(update={"artifact_sha256": digest})
