from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Iterable

from pydantic import BaseModel, Field, model_validator

from .m15_observability_contracts import ObservabilityIdentity

M15_RELEASE_HEALTH_SCHEMA = "knowledge-engine-release-health/v1"
_PRIVATE_URI = re.compile(r"(?:s3|r2|file)://", re.I)


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class HealthIssueCode(StrEnum):
    RELEASE_DRIFT = "release_drift"
    MANIFEST_DRIFT = "manifest_drift"
    POINTER_DRIFT = "pointer_drift"
    CACHE_STALE = "cache_stale"
    OBJECT_MISSING = "object_missing"
    OBJECT_SIZE_MISMATCH = "object_size_mismatch"
    OBJECT_DIGEST_MISMATCH = "object_digest_mismatch"
    OBJECT_ETAG_MALFORMED = "object_etag_malformed"
    DUPLICATE_OBJECT = "duplicate_object"
    PROBE_FAILURE = "probe_failure"
    PRIVATE_URI_REJECTED = "private_uri_rejected"


class ExpectedObject(BaseModel):
    object_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]{0,159}$")
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    etag: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def reject_private_uri(self) -> "ExpectedObject":
        if _PRIVATE_URI.search(self.object_id):
            raise ValueError("private object URI is forbidden in health reports")
        return self


class ObservedObject(BaseModel):
    object_id: str
    present: bool
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    etag: str | None = Field(default=None, max_length=128)


class HealthIssue(BaseModel):
    code: HealthIssueCode
    component: str
    object_id: str | None = None


class ReleaseHealthReport(BaseModel):
    schema_version: str = M15_RELEASE_HEALTH_SCHEMA
    generated_at: datetime
    identity: ObservabilityIdentity
    state: HealthState
    issues: list[HealthIssue]
    checked_objects: int = Field(ge=0)
    healthy_objects: int = Field(ge=0)
    artifact_sha256: str | None = None


@dataclass(frozen=True)
class HealthBaseline:
    release_id: str
    manifest_sha256: str
    pointer_sha256: str
    cache_release_id: str


def normalize_etag(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip('"').lower()
    if not re.fullmatch(r"[0-9a-f]{32}(?:-[0-9]+)?", cleaned):
        return None
    return cleaned


def evaluate_release_health(
    *,
    identity: ObservabilityIdentity,
    expected: HealthBaseline,
    observed_release_id: str | None,
    observed_manifest_sha256: str | None,
    observed_pointer_sha256: str | None,
    observed_cache_release_id: str | None,
    expected_objects: Iterable[ExpectedObject],
    observed_objects: Iterable[ObservedObject],
    probe_failed: bool = False,
    generated_at: datetime | None = None,
) -> ReleaseHealthReport:
    issues: list[HealthIssue] = []
    expected_list = list(expected_objects)
    observed_list = list(observed_objects)
    seen: set[str] = set()
    observed_map: dict[str, ObservedObject] = {}
    for item in observed_list:
        if item.object_id in seen:
            issues.append(HealthIssue(code=HealthIssueCode.DUPLICATE_OBJECT, component="r2", object_id=item.object_id))
        seen.add(item.object_id)
        observed_map[item.object_id] = item

    if probe_failed:
        issues.append(HealthIssue(code=HealthIssueCode.PROBE_FAILURE, component="probe"))
    if observed_release_id != expected.release_id:
        issues.append(HealthIssue(code=HealthIssueCode.RELEASE_DRIFT, component="release"))
    if observed_manifest_sha256 != expected.manifest_sha256:
        issues.append(HealthIssue(code=HealthIssueCode.MANIFEST_DRIFT, component="manifest"))
    if observed_pointer_sha256 != expected.pointer_sha256:
        issues.append(HealthIssue(code=HealthIssueCode.POINTER_DRIFT, component="pointer"))
    if observed_cache_release_id != expected.cache_release_id:
        issues.append(HealthIssue(code=HealthIssueCode.CACHE_STALE, component="cache"))

    healthy_objects = 0
    for expected_object in expected_list:
        observed = observed_map.get(expected_object.object_id)
        if observed is None or not observed.present:
            issues.append(HealthIssue(code=HealthIssueCode.OBJECT_MISSING, component="r2", object_id=expected_object.object_id))
            continue
        object_ok = True
        if observed.size_bytes != expected_object.size_bytes:
            object_ok = False
            issues.append(HealthIssue(code=HealthIssueCode.OBJECT_SIZE_MISMATCH, component="r2", object_id=expected_object.object_id))
        if observed.sha256 != expected_object.sha256:
            object_ok = False
            issues.append(HealthIssue(code=HealthIssueCode.OBJECT_DIGEST_MISMATCH, component="r2", object_id=expected_object.object_id))
        if expected_object.etag is not None and normalize_etag(observed.etag) != normalize_etag(expected_object.etag):
            object_ok = False
            issues.append(HealthIssue(code=HealthIssueCode.OBJECT_ETAG_MALFORMED, component="r2", object_id=expected_object.object_id))
        if object_ok:
            healthy_objects += 1

    issues = sorted(issues, key=lambda item: (item.code.value, item.component, item.object_id or ""))
    if probe_failed:
        state = HealthState.UNKNOWN
    elif any(item.code in {HealthIssueCode.RELEASE_DRIFT, HealthIssueCode.MANIFEST_DRIFT, HealthIssueCode.POINTER_DRIFT, HealthIssueCode.OBJECT_MISSING, HealthIssueCode.OBJECT_DIGEST_MISMATCH} for item in issues):
        state = HealthState.UNHEALTHY
    elif issues:
        state = HealthState.DEGRADED
    else:
        state = HealthState.HEALTHY

    report = ReleaseHealthReport(
        generated_at=generated_at or datetime.now(UTC),
        identity=identity,
        state=state,
        issues=issues,
        checked_objects=len(expected_list),
        healthy_objects=healthy_objects,
    )
    payload = report.model_dump(mode="json")
    payload["artifact_sha256"] = None
    digest = hashlib.sha256((json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
    return report.model_copy(update={"artifact_sha256": digest})
