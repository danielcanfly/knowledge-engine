from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
GIT_SHA_RE = re.compile(r"^[a-f0-9]{40}$")
BATCH_ID_RE = re.compile(r"^mbatch_[a-f0-9]{32}$")
OPERATION_ID_RE = re.compile(r"^mop_[a-f0-9]{32}$")
REVIEW_ID_RE = re.compile(r"^mreview_[a-f0-9]{32}$")
RELEASE_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}$")
CANDIDATE_CHANNEL_RE = re.compile(r"^candidate/mbatch_[a-f0-9]{32}/[0-9]{4}$")
ARTIFACT_NAME_RE = re.compile(
    r"^mbatch_[a-f0-9]{32}--[a-z0-9][a-z0-9-]{0,62}--[a-f0-9]{12}\.[a-z0-9]{1,12}$"
)
LEDGER_ID_RE = re.compile(r"^ledger:mbatch_[a-f0-9]{32}:mop_[a-f0-9]{32}$")
AUDIENCES = frozenset({"public", "internal", "confidential", "restricted"})


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _digest(prefix: str, payload: Any) -> str:
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _validate_timestamp(value: str, field_name: str) -> None:
    if not value.endswith("Z"):
        raise ValueError(f"{field_name} must end in Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field_name} must be valid ISO-8601") from exc


class BatchState(StrEnum):
    PLANNED = "planned"
    INTAKE_ACTIVE = "intake_active"
    SOURCE_REVIEW = "source_review"
    CANDIDATE_BUILDING = "candidate_building"
    CANDIDATE_READY = "candidate_ready"
    EVALUATION_READY = "evaluation_ready"
    PROMOTION_READY = "promotion_ready"
    PRODUCTION_ACTIVE = "production_active"
    SUPERSEDED = "superseded"
    ABANDONED = "abandoned"
    CLOSED = "closed"
    REJECTED = "rejected"


class OperationKind(StrEnum):
    PLAN_BATCH = "plan_batch"
    START_INTAKE = "start_intake"
    OPEN_SOURCE_REVIEW = "open_source_review"
    BUILD_CANDIDATE = "build_candidate"
    REBUILD_CANDIDATE = "rebuild_candidate"
    RECORD_EVALUATION = "record_evaluation"
    PREPARE_PROMOTION = "prepare_promotion"
    PROMOTE_PRODUCTION = "promote_production"
    ROLLBACK_PRODUCTION = "rollback_production"
    MARK_SUPERSEDED = "mark_superseded"
    ABANDON_BATCH = "abandon_batch"
    CLOSE_BATCH = "close_batch"


class OperationStatus(StrEnum):
    REQUESTED = "requested"
    VALIDATED = "validated"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    ABANDONED = "abandoned"


TERMINAL_BATCH_STATES = frozenset(
    {BatchState.ABANDONED, BatchState.CLOSED, BatchState.REJECTED}
)
TERMINAL_OPERATION_STATUSES = frozenset(
    {
        OperationStatus.SUCCEEDED,
        OperationStatus.REJECTED,
        OperationStatus.FAILED,
        OperationStatus.SUPERSEDED,
        OperationStatus.ABANDONED,
    }
)
PRODUCTION_MUTATION_KINDS = frozenset(
    {OperationKind.PROMOTE_PRODUCTION, OperationKind.ROLLBACK_PRODUCTION}
)

BATCH_TRANSITIONS: dict[BatchState, frozenset[BatchState]] = {
    BatchState.PLANNED: frozenset(
        {BatchState.INTAKE_ACTIVE, BatchState.ABANDONED, BatchState.REJECTED}
    ),
    BatchState.INTAKE_ACTIVE: frozenset(
        {BatchState.SOURCE_REVIEW, BatchState.ABANDONED, BatchState.REJECTED}
    ),
    BatchState.SOURCE_REVIEW: frozenset(
        {BatchState.CANDIDATE_BUILDING, BatchState.ABANDONED, BatchState.REJECTED}
    ),
    BatchState.CANDIDATE_BUILDING: frozenset(
        {BatchState.CANDIDATE_READY, BatchState.ABANDONED, BatchState.REJECTED}
    ),
    BatchState.CANDIDATE_READY: frozenset(
        {
            BatchState.CANDIDATE_BUILDING,
            BatchState.EVALUATION_READY,
            BatchState.SUPERSEDED,
            BatchState.ABANDONED,
            BatchState.REJECTED,
        }
    ),
    BatchState.EVALUATION_READY: frozenset(
        {
            BatchState.CANDIDATE_BUILDING,
            BatchState.PROMOTION_READY,
            BatchState.SUPERSEDED,
            BatchState.ABANDONED,
            BatchState.REJECTED,
        }
    ),
    BatchState.PROMOTION_READY: frozenset(
        {
            BatchState.CANDIDATE_BUILDING,
            BatchState.PRODUCTION_ACTIVE,
            BatchState.SUPERSEDED,
            BatchState.ABANDONED,
            BatchState.REJECTED,
        }
    ),
    BatchState.PRODUCTION_ACTIVE: frozenset(
        {BatchState.SUPERSEDED, BatchState.CLOSED}
    ),
    BatchState.SUPERSEDED: frozenset({BatchState.CLOSED}),
    BatchState.ABANDONED: frozenset(),
    BatchState.CLOSED: frozenset(),
    BatchState.REJECTED: frozenset(),
}

OPERATION_TRANSITIONS: dict[OperationStatus, frozenset[OperationStatus]] = {
    OperationStatus.REQUESTED: frozenset(
        {OperationStatus.VALIDATED, OperationStatus.REJECTED, OperationStatus.ABANDONED}
    ),
    OperationStatus.VALIDATED: frozenset(
        {
            OperationStatus.RUNNING,
            OperationStatus.REJECTED,
            OperationStatus.SUPERSEDED,
            OperationStatus.ABANDONED,
        }
    ),
    OperationStatus.RUNNING: frozenset(
        {
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED,
            OperationStatus.SUPERSEDED,
            OperationStatus.ABANDONED,
        }
    ),
    OperationStatus.SUCCEEDED: frozenset(),
    OperationStatus.REJECTED: frozenset(),
    OperationStatus.FAILED: frozenset(),
    OperationStatus.SUPERSEDED: frozenset(),
    OperationStatus.ABANDONED: frozenset(),
}

KIND_BATCH_TRANSITIONS: dict[OperationKind, tuple[BatchState, BatchState]] = {
    OperationKind.PLAN_BATCH: (BatchState.PLANNED, BatchState.PLANNED),
    OperationKind.START_INTAKE: (BatchState.PLANNED, BatchState.INTAKE_ACTIVE),
    OperationKind.OPEN_SOURCE_REVIEW: (
        BatchState.INTAKE_ACTIVE,
        BatchState.SOURCE_REVIEW,
    ),
    OperationKind.BUILD_CANDIDATE: (
        BatchState.SOURCE_REVIEW,
        BatchState.CANDIDATE_BUILDING,
    ),
    OperationKind.REBUILD_CANDIDATE: (
        BatchState.CANDIDATE_READY,
        BatchState.CANDIDATE_BUILDING,
    ),
    OperationKind.RECORD_EVALUATION: (
        BatchState.CANDIDATE_READY,
        BatchState.EVALUATION_READY,
    ),
    OperationKind.PREPARE_PROMOTION: (
        BatchState.EVALUATION_READY,
        BatchState.PROMOTION_READY,
    ),
    OperationKind.PROMOTE_PRODUCTION: (
        BatchState.PROMOTION_READY,
        BatchState.PRODUCTION_ACTIVE,
    ),
    OperationKind.ROLLBACK_PRODUCTION: (
        BatchState.PRODUCTION_ACTIVE,
        BatchState.SUPERSEDED,
    ),
    OperationKind.MARK_SUPERSEDED: (
        BatchState.PROMOTION_READY,
        BatchState.SUPERSEDED,
    ),
    OperationKind.ABANDON_BATCH: (BatchState.PLANNED, BatchState.ABANDONED),
    OperationKind.CLOSE_BATCH: (BatchState.SUPERSEDED, BatchState.CLOSED),
}


@dataclass(frozen=True)
class ProductionIdentity:
    release_id: str
    manifest_sha256: str
    pointer_sha256: str

    def __post_init__(self) -> None:
        if not RELEASE_ID_RE.fullmatch(self.release_id):
            raise ValueError("release_id is invalid")
        for name in ("manifest_sha256", "pointer_sha256"):
            if not SHA256_RE.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} is invalid")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class BatchPlan:
    title: str
    created_at: str
    actor: str
    source_commit_sha: str
    base_production: ProductionIdentity
    intended_audiences: tuple[str, ...]
    source_refs: tuple[str, ...]
    parent_batch_id: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _validate_timestamp(self.created_at, "created_at")
        if not self.title.strip() or not self.actor.strip():
            raise ValueError("title and actor are required")
        if not GIT_SHA_RE.fullmatch(self.source_commit_sha):
            raise ValueError("source_commit_sha is invalid")
        if not self.source_refs or any(not item.strip() for item in self.source_refs):
            raise ValueError("source_refs must contain non-empty values")
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("source_refs cannot contain duplicates")
        if not self.intended_audiences:
            raise ValueError("intended_audiences is required")
        if not set(self.intended_audiences).issubset(AUDIENCES):
            raise ValueError("intended_audiences contains an invalid audience")
        if len(set(self.intended_audiences)) != len(self.intended_audiences):
            raise ValueError("intended_audiences cannot contain duplicates")
        if self.parent_batch_id is not None and not BATCH_ID_RE.fullmatch(
            self.parent_batch_id
        ):
            raise ValueError("parent_batch_id is invalid")
        metadata_keys = [key for key, _ in self.metadata]
        if len(set(metadata_keys)) != len(metadata_keys):
            raise ValueError("metadata keys cannot contain duplicates")
        if any(not key or not value for key, value in self.metadata):
            raise ValueError("metadata entries must be non-empty")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-multi-batch-plan/v1",
            "title": self.title.strip(),
            "created_at": self.created_at,
            "actor": self.actor.strip(),
            "source_commit_sha": self.source_commit_sha,
            "base_production": self.base_production.to_dict(),
            "intended_audiences": sorted(self.intended_audiences),
            "source_refs": sorted(self.source_refs),
            "parent_batch_id": self.parent_batch_id,
            "metadata": {key: value for key, value in sorted(self.metadata)},
        }

    @property
    def batch_id(self) -> str:
        return _digest("mbatch", self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "batch_id": self.batch_id}


@dataclass(frozen=True)
class OperationRequest:
    batch_id: str
    kind: OperationKind
    requested_at: str
    actor: str
    expected_batch_state: BatchState
    target_batch_state: BatchState
    evidence_refs: tuple[str, ...]
    candidate_generation: int | None = None
    expected_previous_production: ProductionIdentity | None = None
    request_nonce: str | None = None

    def __post_init__(self) -> None:
        if not BATCH_ID_RE.fullmatch(self.batch_id):
            raise ValueError("batch_id is invalid")
        _validate_timestamp(self.requested_at, "requested_at")
        if not self.actor.strip():
            raise ValueError("actor is required")
        if not self.evidence_refs or any(not item.strip() for item in self.evidence_refs):
            raise ValueError("evidence_refs must contain non-empty values")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs cannot contain duplicates")
        expected_transition = KIND_BATCH_TRANSITIONS[self.kind]
        if (self.expected_batch_state, self.target_batch_state) != expected_transition:
            raise ValueError("operation kind and batch transition do not match")
        if self.kind != OperationKind.PLAN_BATCH:
            validate_batch_transition(self.expected_batch_state, self.target_batch_state)
        if self.kind in {OperationKind.BUILD_CANDIDATE, OperationKind.REBUILD_CANDIDATE}:
            if self.candidate_generation is None or self.candidate_generation < 1:
                raise ValueError("candidate_generation is required for candidate builds")
        elif self.candidate_generation is not None:
            raise ValueError("candidate_generation is only valid for candidate builds")
        if self.kind in PRODUCTION_MUTATION_KINDS:
            if self.expected_previous_production is None:
                raise ValueError(
                    "expected_previous_production is required for production mutation"
                )
        elif self.expected_previous_production is not None:
            raise ValueError(
                "expected_previous_production is only valid for production mutation"
            )
        if self.request_nonce is not None and not self.request_nonce.strip():
            raise ValueError("request_nonce cannot be blank")

    @property
    def requires_exclusive_production_mutation(self) -> bool:
        return self.kind in PRODUCTION_MUTATION_KINDS

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-multi-batch-operation-request/v1",
            "batch_id": self.batch_id,
            "kind": self.kind.value,
            "requested_at": self.requested_at,
            "actor": self.actor.strip(),
            "expected_batch_state": self.expected_batch_state.value,
            "target_batch_state": self.target_batch_state.value,
            "candidate_generation": self.candidate_generation,
            "expected_previous_production": (
                self.expected_previous_production.to_dict()
                if self.expected_previous_production
                else None
            ),
            "evidence_refs": sorted(self.evidence_refs),
            "request_nonce": self.request_nonce,
            "requires_exclusive_production_mutation": (
                self.requires_exclusive_production_mutation
            ),
        }

    @property
    def operation_id(self) -> str:
        return _digest("mop", self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "operation_id": self.operation_id}


@dataclass(frozen=True)
class OperationResult:
    operation_id: str
    batch_id: str
    kind: OperationKind
    status: OperationStatus
    before_batch_state: BatchState
    after_batch_state: BatchState
    occurred_at: str
    evidence_refs: tuple[str, ...]
    failure_code: str | None = None
    mutation_performed: bool = False
    production_identity_after: ProductionIdentity | None = None
    canonical_source_write_permitted: bool = False
    candidate_write_permitted: bool = False
    production_write_permitted: bool = False
    ledger_append_permitted: bool = False

    def __post_init__(self) -> None:
        if not OPERATION_ID_RE.fullmatch(self.operation_id):
            raise ValueError("operation_id is invalid")
        if not BATCH_ID_RE.fullmatch(self.batch_id):
            raise ValueError("batch_id is invalid")
        _validate_timestamp(self.occurred_at, "occurred_at")
        if not self.evidence_refs or any(not item for item in self.evidence_refs):
            raise ValueError("evidence_refs is required")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs cannot contain duplicates")
        if self.status == OperationStatus.SUCCEEDED:
            if self.failure_code is not None:
                raise ValueError("successful result cannot include failure_code")
            expected = KIND_BATCH_TRANSITIONS[self.kind]
            if (self.before_batch_state, self.after_batch_state) != expected:
                raise ValueError("successful result transition does not match operation kind")
        else:
            if self.after_batch_state != self.before_batch_state:
                raise ValueError("non-successful result cannot change batch state")
            if self.status in {OperationStatus.REJECTED, OperationStatus.FAILED}:
                if not self.failure_code:
                    raise ValueError("rejected or failed result requires failure_code")
        if self.mutation_performed:
            if self.kind not in PRODUCTION_MUTATION_KINDS:
                raise ValueError("only production operations may perform mutation")
            if self.status != OperationStatus.SUCCEEDED:
                raise ValueError("only successful operation may perform mutation")
            if self.production_identity_after is None:
                raise ValueError("production identity after mutation is required")
        elif self.production_identity_after is not None:
            raise ValueError("production identity requires mutation_performed")
        if any(
            (
                self.canonical_source_write_permitted,
                self.candidate_write_permitted,
                self.production_write_permitted,
                self.ledger_append_permitted,
            )
        ):
            raise ValueError("M13.1 contract results cannot grant write permissions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-multi-batch-operation-result/v1",
            "operation_id": self.operation_id,
            "batch_id": self.batch_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "before_batch_state": self.before_batch_state.value,
            "after_batch_state": self.after_batch_state.value,
            "occurred_at": self.occurred_at,
            "evidence_refs": sorted(self.evidence_refs),
            "failure_code": self.failure_code,
            "mutation_performed": self.mutation_performed,
            "production_identity_after": (
                self.production_identity_after.to_dict()
                if self.production_identity_after
                else None
            ),
            "canonical_source_write_permitted": False,
            "candidate_write_permitted": False,
            "production_write_permitted": False,
            "ledger_append_permitted": False,
        }


def validate_batch_transition(before: BatchState, after: BatchState) -> None:
    if before in TERMINAL_BATCH_STATES:
        raise ValueError(f"terminal batch state {before.value} cannot transition")
    if after not in BATCH_TRANSITIONS[before]:
        raise ValueError(f"invalid batch transition: {before.value} -> {after.value}")


def validate_operation_transition(
    before: OperationStatus, after: OperationStatus
) -> None:
    if before in TERMINAL_OPERATION_STATUSES:
        raise ValueError(f"terminal operation status {before.value} cannot transition")
    if after not in OPERATION_TRANSITIONS[before]:
        raise ValueError(f"invalid operation transition: {before.value} -> {after.value}")


def candidate_channel(batch_id: str, generation: int) -> str:
    if not BATCH_ID_RE.fullmatch(batch_id):
        raise ValueError("batch_id is invalid")
    if not 1 <= generation <= 9999:
        raise ValueError("generation must be between 1 and 9999")
    value = f"candidate/{batch_id}/{generation:04d}"
    if not CANDIDATE_CHANNEL_RE.fullmatch(value):
        raise ValueError("candidate channel is invalid")
    return value


def artifact_name(batch_id: str, kind: str, payload_sha256: str, extension: str) -> str:
    if not BATCH_ID_RE.fullmatch(batch_id):
        raise ValueError("batch_id is invalid")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", kind):
        raise ValueError("artifact kind is invalid")
    if not SHA256_RE.fullmatch(payload_sha256):
        raise ValueError("payload_sha256 is invalid")
    if not re.fullmatch(r"[a-z0-9]{1,12}", extension):
        raise ValueError("extension is invalid")
    value = f"{batch_id}--{kind}--{payload_sha256[:12]}.{extension}"
    if not ARTIFACT_NAME_RE.fullmatch(value):
        raise ValueError("artifact name is invalid")
    return value


def review_id(batch_id: str, reviewer: str, evidence_refs: tuple[str, ...]) -> str:
    if not BATCH_ID_RE.fullmatch(batch_id):
        raise ValueError("batch_id is invalid")
    if not reviewer.strip() or not evidence_refs:
        raise ValueError("reviewer and evidence_refs are required")
    value = _digest(
        "mreview",
        {
            "batch_id": batch_id,
            "reviewer": reviewer.strip(),
            "evidence_refs": sorted(evidence_refs),
        },
    )
    if not REVIEW_ID_RE.fullmatch(value):
        raise ValueError("review identity is invalid")
    return value


def ledger_identifier(batch_id: str, operation_id: str) -> str:
    if not BATCH_ID_RE.fullmatch(batch_id) or not OPERATION_ID_RE.fullmatch(operation_id):
        raise ValueError("batch_id or operation_id is invalid")
    value = f"ledger:{batch_id}:{operation_id}"
    if not LEDGER_ID_RE.fullmatch(value):
        raise ValueError("ledger identifier is invalid")
    return value
