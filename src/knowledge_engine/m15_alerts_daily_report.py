from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

M15_DAILY_REPORT_SCHEMA = "knowledge-engine-m15-daily-report/v1"


class ReportSection(StrEnum):
    OBSERVABILITY_CONTRACTS = "observability_contracts"
    RUNTIME_TELEMETRY = "runtime_telemetry"
    RELEASE_HEALTH = "release_health"
    GOVERNANCE_HEALTH = "governance_health"
    FRESHNESS_IMPACT = "freshness_impact"
    FEEDBACK_TRIAGE = "feedback_triage"


class EvidenceState(StrEnum):
    SUCCESS = "success"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    MISSING = "missing"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertState(StrEnum):
    OK = "ok"
    FIRING = "firing"


class AlertReason(StrEnum):
    MISSING_EVIDENCE = "missing_evidence"
    STALE_EVIDENCE = "stale_evidence"
    UNHEALTHY_EVIDENCE = "unhealthy_evidence"
    UNKNOWN_EVIDENCE = "unknown_evidence"
    IDENTITY_DRIFT = "identity_drift"
    PRIVACY_UNSAFE = "privacy_unsafe"


class GateName(StrEnum):
    PRIVACY = "privacy"
    IDENTITY = "identity"
    EVIDENCE_COMPLETE = "evidence_complete"
    HEALTH = "health"
    FRESHNESS = "freshness"
    FEEDBACK = "feedback"
    NO_WRITE = "no_write"


class GateState(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"


class ClosureDecision(StrEnum):
    READY_TO_CLOSE = "ready_to_close"
    BLOCKED = "blocked"


_FORBIDDEN_FRAGMENTS = (
    "bearer ",
    "authorization:",
    "cookie:",
    "jwt",
    "raw_query",
    "raw_answer",
    "private excerpt",
    "client_ip",
    "hostname",
    "traceback",
    "s3://",
    "r2://",
    "file://",
)

_REQUIRED_SECTIONS = tuple(section for section in ReportSection)
_ACCEPTABLE_STATES = {EvidenceState.SUCCESS, EvidenceState.HEALTHY}


class M15Identity(BaseModel):
    engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    release_id: str = Field(min_length=8, max_length=128)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pointer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class M15EvidenceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: ReportSection
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: EvidenceState
    generated_at: datetime
    identity: M15Identity
    summary_code: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9._:-]+$")

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("M15 evidence timestamps must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def reject_private_material(self) -> Self:
        encoded = json.dumps(self.model_dump(mode="json"), sort_keys=True).lower()
        if any(fragment in encoded for fragment in _FORBIDDEN_FRAGMENTS):
            raise ValueError("M15 evidence contains forbidden private or secret material")
        return self


class M15Alert(BaseModel):
    section: ReportSection
    state: AlertState
    severity: AlertSeverity
    reason: AlertReason


class M15AcceptanceGate(BaseModel):
    name: GateName
    state: GateState
    reason: AlertReason | None = None


class M15DailyReport(BaseModel):
    schema_version: str = M15_DAILY_REPORT_SCHEMA
    generated_at: datetime
    identity: M15Identity
    evidence: list[M15EvidenceArtifact]
    alerts: list[M15Alert]
    gates: list[M15AcceptanceGate]
    closure_decision: ClosureDecision
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("daily report timestamp must be timezone-aware UTC")
        return value


class M15ClosureAuthority(BaseModel):
    source_write_allowed: bool = False
    source_pr_allowed: bool = False
    candidate_dispatch_allowed: bool = False
    production_write_allowed: bool = False
    pointer_repair_allowed: bool = False
    cache_purge_allowed: bool = False
    r2_mutation_allowed: bool = False
    rollback_allowed: bool = False
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def reject_authority(self) -> Self:
        enabled = sorted(name for name, value in self.model_dump().items() if value)
        if enabled:
            raise ValueError(f"M15.7 closure is no-write; authority enabled: {enabled}")
        return self


def _canonical_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evaluate_m15_daily_report(
    evidence: list[M15EvidenceArtifact],
    *,
    generated_at: datetime,
    identity: M15Identity,
    max_age: timedelta = timedelta(days=1),
) -> M15DailyReport:
    if generated_at.tzinfo is None or generated_at.utcoffset() != timedelta(0):
        raise ValueError("generated_at must be timezone-aware UTC")
    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive")

    alerts: list[M15Alert] = []
    by_section = {item.section: item for item in evidence}

    for section in _REQUIRED_SECTIONS:
        item = by_section.get(section)
        if item is None:
            alerts.append(_alert(section, AlertSeverity.CRITICAL, AlertReason.MISSING_EVIDENCE))
            continue
        if item.identity != identity:
            alerts.append(_alert(section, AlertSeverity.CRITICAL, AlertReason.IDENTITY_DRIFT))
        if generated_at - item.generated_at > max_age:
            alerts.append(_alert(section, AlertSeverity.WARNING, AlertReason.STALE_EVIDENCE))
        if item.state == EvidenceState.UNKNOWN:
            alerts.append(_alert(section, AlertSeverity.WARNING, AlertReason.UNKNOWN_EVIDENCE))
        elif item.state not in _ACCEPTABLE_STATES:
            alerts.append(_alert(section, AlertSeverity.CRITICAL, AlertReason.UNHEALTHY_EVIDENCE))

    alerts.sort(key=lambda item: (item.severity.value, item.section.value, item.reason.value))
    gates = _build_gates(alerts)
    closure = (
        ClosureDecision.READY_TO_CLOSE
        if all(gate.state == GateState.PASSED for gate in gates)
        else ClosureDecision.BLOCKED
    )
    report = M15DailyReport(
        generated_at=generated_at,
        identity=identity,
        evidence=sorted(evidence, key=lambda item: item.section.value),
        alerts=alerts,
        gates=gates,
        closure_decision=closure,
    )
    return finalize_m15_daily_report(report)


def _alert(section: ReportSection, severity: AlertSeverity, reason: AlertReason) -> M15Alert:
    return M15Alert(section=section, state=AlertState.FIRING, severity=severity, reason=reason)


def _build_gates(alerts: list[M15Alert]) -> list[M15AcceptanceGate]:
    reasons = {alert.reason for alert in alerts if alert.state == AlertState.FIRING}
    gate_reasons = {
        GateName.PRIVACY: AlertReason.PRIVACY_UNSAFE,
        GateName.IDENTITY: AlertReason.IDENTITY_DRIFT,
        GateName.EVIDENCE_COMPLETE: AlertReason.MISSING_EVIDENCE,
        GateName.HEALTH: AlertReason.UNHEALTHY_EVIDENCE,
        GateName.FRESHNESS: AlertReason.STALE_EVIDENCE,
        GateName.FEEDBACK: AlertReason.UNKNOWN_EVIDENCE,
        GateName.NO_WRITE: None,
    }
    gates: list[M15AcceptanceGate] = []
    for name, reason in gate_reasons.items():
        blocked = reason in reasons if reason is not None else False
        gates.append(
            M15AcceptanceGate(
                name=name,
                state=GateState.BLOCKED if blocked else GateState.PASSED,
                reason=reason if blocked else None,
            )
        )
    return sorted(gates, key=lambda gate: gate.name.value)


def m15_daily_report_sha256(report: M15DailyReport) -> str:
    payload = report.model_dump(mode="json")
    payload["artifact_sha256"] = None
    return _canonical_sha256(payload)


def finalize_m15_daily_report(report: M15DailyReport) -> M15DailyReport:
    digest = m15_daily_report_sha256(report)
    if report.artifact_sha256 not in {None, digest}:
        raise ValueError("M15 daily report digest mismatch")
    return report.model_copy(update={"artifact_sha256": digest})
