from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

M15_OBSERVABILITY_SCHEMA = "knowledge-engine-observability-contract/v1"
M15_PRIVACY_POLICY_SCHEMA = "knowledge-engine-observability-privacy/v1"
M15_REPORT_SCHEMA = "knowledge-engine-observability-report/v1"
MAX_DIMENSIONS = 12
MAX_DIMENSION_VALUE_LENGTH = 96
MAX_CLOCK_SKEW_SECONDS = 300
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA64_RE = re.compile(r"^[0-9a-f]{64}$")


class EventFamily(StrEnum):
    RUNTIME_REQUEST = "runtime_request"
    RETRIEVAL = "retrieval"
    CITATION = "citation"
    ACL_FILTERING = "acl_filtering"
    RELEASE_ACTIVATION = "release_activation"
    CACHE_IDENTITY = "cache_identity"
    POINTER_HEALTH = "pointer_health"
    R2_OBJECT_HEALTH = "r2_object_health"
    BATCH_LIFECYCLE = "batch_lifecycle"
    PROMOTION_REPLAY_ROLLBACK = "promotion_replay_rollback"
    FEEDBACK_TRIAGE = "feedback_triage"
    FRESHNESS_IMPACT = "freshness_impact"
    ALERT_STATE = "alert_state"


class RetentionClass(StrEnum):
    EPHEMERAL_24H = "ephemeral_24h"
    OPERATIONAL_30D = "operational_30d"
    GOVERNANCE_1Y = "governance_1y"


class FieldDisposition(StrEnum):
    ALLOWED = "allowed"
    TRANSFORMED = "transformed"
    FORBIDDEN = "forbidden"


FORBIDDEN_FIELDS = frozenset(
    {
        "raw_query",
        "query",
        "raw_answer",
        "answer",
        "authorization",
        "bearer_token",
        "jwt",
        "jwt_claims",
        "cookie",
        "raw_ip",
        "client_ip",
        "client_host",
        "private_source_excerpt",
        "source_excerpt",
        "prompt",
    }
)
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"bearer\s+[a-z0-9._~+/-]+=*", re.I),
    re.compile(r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+"),
    re.compile(r"(?:s3|r2|file)://", re.I),
)
ALLOWED_DIMENSIONS = frozenset(
    {
        "audience",
        "status",
        "transport",
        "surface",
        "error_code",
        "cache_result",
        "health_state",
        "lifecycle_state",
        "decision",
        "severity",
        "sample_class",
        "region_class",
    }
)


class MetricDefinition(BaseModel):
    name: str = Field(pattern=r"^knowledge_engine_[a-z0-9_]+$")
    unit: Literal["count", "seconds", "ratio", "bytes"]
    description: str = Field(min_length=1, max_length=240)
    dimensions: list[str] = Field(default_factory=list, max_length=MAX_DIMENSIONS)
    max_series: int = Field(ge=1, le=10_000)

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("metric dimensions must be unique")
        unknown = sorted(set(value) - ALLOWED_DIMENSIONS)
        if unknown:
            raise ValueError(f"unbounded or unknown metric dimensions: {unknown}")
        return value


class PrivacyFieldRule(BaseModel):
    field: str
    disposition: FieldDisposition
    transform: Literal["none", "drop", "sha256", "truncate", "bucket"] = "none"

    @model_validator(mode="after")
    def validate_rule(self) -> "PrivacyFieldRule":
        if self.field.lower() in FORBIDDEN_FIELDS and self.disposition != FieldDisposition.FORBIDDEN:
            raise ValueError(f"forbidden field cannot be enabled: {self.field}")
        if self.disposition == FieldDisposition.FORBIDDEN and self.transform != "drop":
            raise ValueError("forbidden fields must use drop transform")
        return self


class PrivacyPolicy(BaseModel):
    schema_version: str = M15_PRIVACY_POLICY_SCHEMA
    raw_query_collected: bool = False
    raw_answer_collected: bool = False
    bearer_or_jwt_collected: bool = False
    raw_ip_or_host_collected: bool = False
    private_excerpt_collected: bool = False
    default_retention: RetentionClass = RetentionClass.OPERATIONAL_30D
    sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    field_rules: list[PrivacyFieldRule]

    @model_validator(mode="after")
    def enforce_defaults(self) -> "PrivacyPolicy":
        forbidden_switches = {
            "raw_query_collected": self.raw_query_collected,
            "raw_answer_collected": self.raw_answer_collected,
            "bearer_or_jwt_collected": self.bearer_or_jwt_collected,
            "raw_ip_or_host_collected": self.raw_ip_or_host_collected,
            "private_excerpt_collected": self.private_excerpt_collected,
        }
        enabled = sorted(name for name, value in forbidden_switches.items() if value)
        if enabled:
            raise ValueError(f"privacy-forbidden collection enabled: {enabled}")
        return self


class ObservabilityIdentity(BaseModel):
    engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    canonical_source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    release_id: str | None = Field(default=None, max_length=128)
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pointer_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    request_id: str | None = Field(default=None, min_length=8, max_length=128)
    operation_id: str | None = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def require_correlation(self) -> "ObservabilityIdentity":
        if not self.request_id and not self.operation_id:
            raise ValueError("request_id or operation_id is required")
        if self.release_id and not self.manifest_sha256:
            raise ValueError("release identity requires manifest_sha256")
        return self


class ObservabilityEvent(BaseModel):
    schema_version: str = M15_OBSERVABILITY_SCHEMA
    family: EventFamily
    event_name: str = Field(pattern=r"^[a-z0-9_]+$", max_length=96)
    occurred_at: datetime
    identity: ObservabilityIdentity
    retention: RetentionClass
    sampled: bool = True
    dimensions: dict[str, str] = Field(default_factory=dict)
    measurements: dict[str, float | int] = Field(default_factory=dict)
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("occurred_at must be timezone-aware UTC")
        return value

    @field_validator("dimensions")
    @classmethod
    def validate_dimension_values(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > MAX_DIMENSIONS:
            raise ValueError("too many dimensions")
        unknown = sorted(set(value) - ALLOWED_DIMENSIONS)
        if unknown:
            raise ValueError(f"unbounded or unknown event dimensions: {unknown}")
        for key, item in value.items():
            if len(item) > MAX_DIMENSION_VALUE_LENGTH:
                raise ValueError(f"dimension value too long: {key}")
        return value

    @model_validator(mode="after")
    def reject_sensitive_payloads(self) -> "ObservabilityEvent":
        payload = self.model_dump(mode="json")
        for container_name in ("attributes", "dimensions"):
            container = payload[container_name]
            forbidden = sorted(set(map(str.lower, container)) & FORBIDDEN_FIELDS)
            if forbidden:
                raise ValueError(f"forbidden telemetry fields: {forbidden}")
            for value in container.values():
                text = str(value)
                if any(pattern.search(text) for pattern in FORBIDDEN_VALUE_PATTERNS):
                    raise ValueError("sensitive telemetry value detected")
        return self


class GovernanceBoundary(BaseModel):
    source_write_allowed: bool = False
    source_package_allowed: bool = False
    source_pr_allowed: bool = False
    candidate_dispatch_allowed: bool = False
    production_write_allowed: bool = False
    pointer_repair_allowed: bool = False
    rollback_allowed: bool = False
    physical_delete_allowed: bool = False
    automatic_correction_allowed: bool = False
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def reject_write_authority(self) -> "GovernanceBoundary":
        enabled = sorted(name for name, value in self.model_dump().items() if value)
        if enabled:
            raise ValueError(f"M15.1 is contract-only; write authority enabled: {enabled}")
        return self


class ObservabilityContract(BaseModel):
    schema_version: str = M15_OBSERVABILITY_SCHEMA
    event_families: list[EventFamily]
    metrics: list[MetricDefinition]
    privacy: PrivacyPolicy
    governance: GovernanceBoundary = GovernanceBoundary()
    max_clock_skew_seconds: int = Field(default=MAX_CLOCK_SKEW_SECONDS, ge=0, le=300)

    @field_validator("event_families")
    @classmethod
    def require_closed_event_family_set(cls, value: list[EventFamily]) -> list[EventFamily]:
        expected = set(EventFamily)
        actual = set(value)
        if actual != expected or len(value) != len(expected):
            raise ValueError("event family set must contain each closed M15.1 family exactly once")
        return value


class ObservabilityReport(BaseModel):
    schema_version: str = M15_REPORT_SCHEMA
    contract: ObservabilityContract
    generated_at: datetime
    baseline: ObservabilityIdentity
    artifact_sha256: str | None = None

    @field_validator("generated_at")
    @classmethod
    def require_report_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("generated_at must be timezone-aware UTC")
        return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def report_sha256(report: ObservabilityReport) -> str:
    payload = report.model_dump(mode="json")
    payload["artifact_sha256"] = None
    return hashlib.sha256((canonical_json(payload) + "\n").encode()).hexdigest()


def finalize_report(report: ObservabilityReport) -> ObservabilityReport:
    digest = report_sha256(report)
    if report.artifact_sha256 not in {None, digest}:
        raise ValueError("observability report digest mismatch")
    return report.model_copy(update={"artifact_sha256": digest})
