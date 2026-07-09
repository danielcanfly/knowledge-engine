from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from .compiler_contract_v1 import json_bytes, put_immutable
from .m13_contracts import (
    BATCH_ID_RE,
    CANDIDATE_CHANNEL_RE,
    RELEASE_ID_RE,
    SHA256_RE,
    ProductionIdentity,
    stable_json_bytes,
)
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore

RETENTION_SCHEMA = "knowledge-engine-m13-retention/v1"
ARTIFACT_ID_RE = re.compile(r"^martifact_[a-f0-9]{32}$")
REVIEW_ID_RE = re.compile(r"^mretain_[a-f0-9]{32}$")
PLAN_ID_RE = re.compile(r"^mretplan_[a-f0-9]{32}$")

ArtifactClass = Literal[
    "raw_snapshot",
    "candidate",
    "release",
    "rollback_target",
    "evidence",
    "registry_history",
    "coordination_evidence",
    "production_identity",
]
RetentionDisposition = Literal[
    "permanent",
    "protected",
    "quarantine",
    "deletion_candidate",
]

PERMANENT_CLASSES: frozenset[ArtifactClass] = frozenset(
    {
        "evidence",
        "registry_history",
        "coordination_evidence",
        "production_identity",
    }
)
QUARANTINE_DAYS: dict[ArtifactClass, int] = {
    "raw_snapshot": 90,
    "candidate": 30,
    "release": 180,
    "rollback_target": 365,
}


class M13RetentionError(ValueError):
    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.context = context


@dataclass(frozen=True)
class RetentionArtifact:
    key: str
    artifact_class: ArtifactClass
    created_at: str
    sha256: str
    batch_id: str | None = None
    candidate_channel: str | None = None
    release_id: str | None = None
    terminal_at: str | None = None
    reference_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key or self.key.startswith("/") or ".." in self.key.split("/"):
            raise M13RetentionError("M13_RETENTION_KEY_INVALID", "artifact key is invalid")
        _parse_utc(self.created_at, "created_at")
        if not SHA256_RE.fullmatch(self.sha256):
            raise M13RetentionError("M13_RETENTION_SHA_INVALID", "sha256 is invalid")
        if self.batch_id is not None and not BATCH_ID_RE.fullmatch(self.batch_id):
            raise M13RetentionError("M13_RETENTION_BATCH_INVALID", "batch_id is invalid")
        if self.candidate_channel is not None and not CANDIDATE_CHANNEL_RE.fullmatch(
            self.candidate_channel
        ):
            raise M13RetentionError(
                "M13_RETENTION_CANDIDATE_INVALID", "candidate channel is invalid"
            )
        if self.release_id is not None and not RELEASE_ID_RE.fullmatch(self.release_id):
            raise M13RetentionError("M13_RETENTION_RELEASE_INVALID", "release_id is invalid")
        if self.terminal_at is not None:
            terminal = _parse_utc(self.terminal_at, "terminal_at")
            if terminal < _parse_utc(self.created_at, "created_at"):
                raise M13RetentionError(
                    "M13_RETENTION_TERMINAL_INVALID",
                    "terminal_at cannot precede created_at",
                )
        if len(self.reference_ids) != len(set(self.reference_ids)):
            raise M13RetentionError(
                "M13_RETENTION_REFERENCES_INVALID", "reference_ids cannot contain duplicates"
            )
        if self.artifact_class == "candidate" and self.candidate_channel is None:
            raise M13RetentionError(
                "M13_RETENTION_CANDIDATE_REQUIRED",
                "candidate artifacts require candidate_channel",
            )
        if self.artifact_class in {"release", "rollback_target"} and self.release_id is None:
            raise M13RetentionError(
                "M13_RETENTION_RELEASE_REQUIRED",
                "release artifacts require release_id",
            )

    def to_identity(self) -> dict[str, Any]:
        return {
            "schema_version": f"{RETENTION_SCHEMA}/artifact",
            "key": self.key,
            "artifact_class": self.artifact_class,
            "created_at": self.created_at,
            "sha256": self.sha256,
            "batch_id": self.batch_id,
            "candidate_channel": self.candidate_channel,
            "release_id": self.release_id,
            "terminal_at": self.terminal_at,
            "reference_ids": list(self.reference_ids),
        }

    def artifact_id(self) -> str:
        return _digest(self.to_identity(), "martifact")


@dataclass(frozen=True)
class RetentionReferenceSnapshot:
    observed_at: str
    production: ProductionIdentity
    open_batch_ids: tuple[str, ...] = ()
    active_candidate_channels: tuple[str, ...] = ()
    referenced_release_ids: tuple[str, ...] = ()
    rollback_release_ids: tuple[str, ...] = ()
    referenced_artifact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _parse_utc(self.observed_at, "observed_at")
        _unique(self.open_batch_ids, "open_batch_ids")
        _unique(self.active_candidate_channels, "active_candidate_channels")
        _unique(self.referenced_release_ids, "referenced_release_ids")
        _unique(self.rollback_release_ids, "rollback_release_ids")
        _unique(self.referenced_artifact_ids, "referenced_artifact_ids")
        for batch_id in self.open_batch_ids:
            if not BATCH_ID_RE.fullmatch(batch_id):
                raise M13RetentionError(
                    "M13_RETENTION_BATCH_INVALID", "open batch identity is invalid"
                )
        for channel in self.active_candidate_channels:
            if not CANDIDATE_CHANNEL_RE.fullmatch(channel):
                raise M13RetentionError(
                    "M13_RETENTION_CANDIDATE_INVALID",
                    "active candidate channel is invalid",
                )
        for release_id in (*self.referenced_release_ids, *self.rollback_release_ids):
            if not RELEASE_ID_RE.fullmatch(release_id):
                raise M13RetentionError(
                    "M13_RETENTION_RELEASE_INVALID", "referenced release is invalid"
                )
        for artifact_id in self.referenced_artifact_ids:
            if not ARTIFACT_ID_RE.fullmatch(artifact_id):
                raise M13RetentionError(
                    "M13_RETENTION_ARTIFACT_INVALID", "referenced artifact is invalid"
                )

    def to_identity(self) -> dict[str, Any]:
        return {
            "schema_version": f"{RETENTION_SCHEMA}/reference-snapshot",
            "observed_at": self.observed_at,
            "production": self.production.to_identity(),
            "open_batch_ids": sorted(self.open_batch_ids),
            "active_candidate_channels": sorted(self.active_candidate_channels),
            "referenced_release_ids": sorted(self.referenced_release_ids),
            "rollback_release_ids": sorted(self.rollback_release_ids),
            "referenced_artifact_ids": sorted(self.referenced_artifact_ids),
        }

    def snapshot_sha256(self) -> str:
        return hashlib.sha256(stable_json_bytes(self.to_identity())).hexdigest()


@dataclass(frozen=True)
class RetentionReviewApproval:
    reviewed_by: str
    reviewed_at: str
    reference_snapshot_sha256: str
    approved_artifact_ids: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not self.reviewed_by:
            raise M13RetentionError("M13_RETENTION_REVIEWER_REQUIRED", "reviewer is required")
        _parse_utc(self.reviewed_at, "reviewed_at")
        if not SHA256_RE.fullmatch(self.reference_snapshot_sha256):
            raise M13RetentionError(
                "M13_RETENTION_REFERENCE_SHA_INVALID",
                "reference snapshot sha256 is invalid",
            )
        _unique(self.approved_artifact_ids, "approved_artifact_ids")
        if not self.approved_artifact_ids:
            raise M13RetentionError(
                "M13_RETENTION_APPROVAL_EMPTY", "approval must name artifacts"
            )
        for artifact_id in self.approved_artifact_ids:
            if not ARTIFACT_ID_RE.fullmatch(artifact_id):
                raise M13RetentionError(
                    "M13_RETENTION_ARTIFACT_INVALID", "approved artifact is invalid"
                )
        if not self.rationale.strip():
            raise M13RetentionError(
                "M13_RETENTION_RATIONALE_REQUIRED", "approval rationale is required"
            )

    def to_identity(self) -> dict[str, Any]:
        return {
            "schema_version": f"{RETENTION_SCHEMA}/review",
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "reference_snapshot_sha256": self.reference_snapshot_sha256,
            "approved_artifact_ids": sorted(self.approved_artifact_ids),
            "rationale": self.rationale,
            "governance": GOVERNANCE_NO_WRITE,
        }

    def review_id(self) -> str:
        return _digest(self.to_identity(), "mretain")


@dataclass(frozen=True)
class RetentionDecision:
    artifact_id: str
    key: str
    artifact_class: ArtifactClass
    disposition: RetentionDisposition
    reasons: tuple[str, ...]
    quarantine_until: str | None
    review_id: str | None
    physical_delete_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetentionPlan:
    plan_id: str
    generated_at: str
    reference_snapshot_sha256: str
    review_id: str | None
    decisions: tuple[RetentionDecision, ...]
    governance: dict[str, bool]
    artifact_key: str
    idempotent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": f"{RETENTION_SCHEMA}/plan-result",
            "plan_id": self.plan_id,
            "generated_at": self.generated_at,
            "reference_snapshot_sha256": self.reference_snapshot_sha256,
            "review_id": self.review_id,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "governance": self.governance,
            "artifact_key": self.artifact_key,
            "idempotent": self.idempotent,
        }


def _parse_utc(value: str, field_name: str) -> datetime:
    if not value.endswith("Z"):
        raise M13RetentionError(
            "M13_RETENTION_TIME_INVALID", f"{field_name} must end with Z"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise M13RetentionError(
            "M13_RETENTION_TIME_INVALID", f"{field_name} must be valid ISO-8601"
        ) from exc
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unique(values: tuple[str, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise M13RetentionError(
            "M13_RETENTION_REFERENCES_INVALID", f"{field_name} cannot contain duplicates"
        )


def _digest(value: dict[str, Any], prefix: str) -> str:
    return f"{prefix}_{hashlib.sha256(stable_json_bytes(value)).hexdigest()[:32]}"


def _quarantine_until(artifact: RetentionArtifact) -> str:
    anchor = artifact.terminal_at or artifact.created_at
    days = QUARANTINE_DAYS[artifact.artifact_class]
    return _format_utc(_parse_utc(anchor, "retention_anchor") + timedelta(days=days))


def _protected_reasons(
    artifact: RetentionArtifact,
    references: RetentionReferenceSnapshot,
) -> tuple[str, ...]:
    reasons: list[str] = []
    artifact_id = artifact.artifact_id()
    if artifact_id in references.referenced_artifact_ids:
        reasons.append("artifact_is_referenced")
    if artifact.batch_id in references.open_batch_ids:
        reasons.append("batch_is_nonterminal")
    if artifact.candidate_channel in references.active_candidate_channels:
        reasons.append("candidate_channel_is_active")
    if artifact.release_id == references.production.release_id:
        reasons.append("release_is_current_production")
    if artifact.release_id in references.rollback_release_ids:
        reasons.append("release_is_rollback_target")
    if artifact.release_id in references.referenced_release_ids:
        reasons.append("release_is_referenced")
    if artifact.reference_ids:
        reasons.append("artifact_declares_references")
    return tuple(sorted(set(reasons)))


def classify_artifact(
    artifact: RetentionArtifact,
    *,
    references: RetentionReferenceSnapshot,
    generated_at: str,
    approval: RetentionReviewApproval | None = None,
) -> RetentionDecision:
    now = _parse_utc(generated_at, "generated_at")
    artifact_id = artifact.artifact_id()
    if artifact.artifact_class in PERMANENT_CLASSES:
        return RetentionDecision(
            artifact_id=artifact_id,
            key=artifact.key,
            artifact_class=artifact.artifact_class,
            disposition="permanent",
            reasons=("artifact_class_is_permanent",),
            quarantine_until=None,
            review_id=None,
        )
    protected = _protected_reasons(artifact, references)
    if protected:
        return RetentionDecision(
            artifact_id=artifact_id,
            key=artifact.key,
            artifact_class=artifact.artifact_class,
            disposition="protected",
            reasons=protected,
            quarantine_until=None,
            review_id=None,
        )
    quarantine_until = _quarantine_until(artifact)
    if now < _parse_utc(quarantine_until, "quarantine_until"):
        return RetentionDecision(
            artifact_id=artifact_id,
            key=artifact.key,
            artifact_class=artifact.artifact_class,
            disposition="quarantine",
            reasons=("minimum_retention_window_active",),
            quarantine_until=quarantine_until,
            review_id=None,
        )
    if approval is None:
        return RetentionDecision(
            artifact_id=artifact_id,
            key=artifact.key,
            artifact_class=artifact.artifact_class,
            disposition="quarantine",
            reasons=("explicit_retention_review_required",),
            quarantine_until=quarantine_until,
            review_id=None,
        )
    if approval.reference_snapshot_sha256 != references.snapshot_sha256():
        raise M13RetentionError(
            "M13_RETENTION_REFERENCE_SNAPSHOT_STALE",
            "approval references a different reference snapshot",
        )
    if _parse_utc(approval.reviewed_at, "reviewed_at") > now:
        raise M13RetentionError(
            "M13_RETENTION_REVIEW_FUTURE", "approval cannot occur after plan generation"
        )
    if artifact_id not in approval.approved_artifact_ids:
        return RetentionDecision(
            artifact_id=artifact_id,
            key=artifact.key,
            artifact_class=artifact.artifact_class,
            disposition="quarantine",
            reasons=("artifact_not_approved_for_deletion_candidate",),
            quarantine_until=quarantine_until,
            review_id=approval.review_id(),
        )
    return RetentionDecision(
        artifact_id=artifact_id,
        key=artifact.key,
        artifact_class=artifact.artifact_class,
        disposition="deletion_candidate",
        reasons=("minimum_window_elapsed", "explicit_review_approved"),
        quarantine_until=quarantine_until,
        review_id=approval.review_id(),
        physical_delete_permitted=False,
    )


def create_retention_plan(
    store: ObjectStore,
    *,
    artifacts: tuple[RetentionArtifact, ...],
    references: RetentionReferenceSnapshot,
    generated_at: str,
    approval: RetentionReviewApproval | None = None,
) -> RetentionPlan:
    _parse_utc(generated_at, "generated_at")
    if not artifacts:
        raise M13RetentionError("M13_RETENTION_ARTIFACTS_EMPTY", "artifacts are required")
    artifact_ids = [artifact.artifact_id() for artifact in artifacts]
    if len(artifact_ids) != len(set(artifact_ids)):
        raise M13RetentionError(
            "M13_RETENTION_ARTIFACTS_DUPLICATE", "artifacts contain duplicate identities"
        )
    if approval is not None:
        unknown = set(approval.approved_artifact_ids) - set(artifact_ids)
        if unknown:
            raise M13RetentionError(
                "M13_RETENTION_APPROVAL_UNKNOWN_ARTIFACT",
                "approval names artifacts outside the plan",
                unknown=sorted(unknown),
            )
    decisions = tuple(
        sorted(
            (
                classify_artifact(
                    artifact,
                    references=references,
                    generated_at=generated_at,
                    approval=approval,
                )
                for artifact in artifacts
            ),
            key=lambda decision: decision.artifact_id,
        )
    )
    identity = {
        "schema_version": f"{RETENTION_SCHEMA}/plan",
        "generated_at": generated_at,
        "reference_snapshot": references.to_identity(),
        "review": approval.to_identity() if approval else None,
        "artifacts": [
            artifact.to_identity()
            for artifact in sorted(artifacts, key=lambda item: item.artifact_id())
        ],
        "decisions": [decision.to_dict() for decision in decisions],
        "governance": GOVERNANCE_NO_WRITE,
        "physical_delete_permitted": False,
    }
    plan_id = _digest(identity, "mretplan")
    if not PLAN_ID_RE.fullmatch(plan_id):
        raise M13RetentionError("M13_RETENTION_PLAN_INVALID", "plan identity is invalid")
    artifact_key = f"m13/v1/retention/plans/{plan_id}.json"
    payload = {**identity, "plan_id": plan_id, "artifact_key": artifact_key}
    idempotent = put_immutable(store, artifact_key, json_bytes(payload))
    return RetentionPlan(
        plan_id=plan_id,
        generated_at=generated_at,
        reference_snapshot_sha256=references.snapshot_sha256(),
        review_id=approval.review_id() if approval else None,
        decisions=decisions,
        governance=dict(GOVERNANCE_NO_WRITE),
        artifact_key=artifact_key,
        idempotent=idempotent,
    )
