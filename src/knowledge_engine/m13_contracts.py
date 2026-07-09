from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from .release_quality_gate import GOVERNANCE_NO_WRITE

SCHEMA_VERSION = "knowledge-engine-m13-contracts/v1"
BATCH_ID_RE = re.compile(r"^mbatch_[a-f0-9]{32}$")
OPERATION_ID_RE = re.compile(r"^mop_[a-f0-9]{32}$")
CANDIDATE_CHANNEL_RE = re.compile(r"^candidate-[a-z0-9][a-z0-9-]{2,62}$")
ARTIFACT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{2,180}$")
RELEASE_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}$")
LEDGER_ID_RE = re.compile(r"^ledger_[a-z0-9][a-z0-9-]{2,80}$")
REVIEW_ID_RE = re.compile(r"^(rqdecision|m12closure2|m11closure2)_[a-f0-9]{32}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SHA40_RE = re.compile(r"^[a-f0-9]{40}$")

BatchState = Literal[
    "planned",
    "reviewing_source",
    "candidate_ready",
    "awaiting_production_slot",
    "promoting",
    "closed",
    "rejected",
    "abandoned",
]
OperationState = Literal[
    "planned",
    "running",
    "blocked",
    "completed",
    "rejected",
    "abandoned",
]
OperationKind = Literal[
    "source_review",
    "candidate_build",
    "release_comparison",
    "production_promotion",
    "rollback",
    "retention_review",
    "closeout",
]

BATCH_TRANSITIONS: dict[BatchState, frozenset[BatchState]] = {
    "planned": frozenset({"reviewing_source", "rejected", "abandoned"}),
    "reviewing_source": frozenset({"candidate_ready", "rejected", "abandoned"}),
    "candidate_ready": frozenset({"awaiting_production_slot", "rejected", "abandoned"}),
    "awaiting_production_slot": frozenset({"promoting", "rejected", "abandoned"}),
    "promoting": frozenset({"closed", "rejected"}),
    "closed": frozenset(),
    "rejected": frozenset(),
    "abandoned": frozenset(),
}
OPERATION_TRANSITIONS: dict[OperationState, frozenset[OperationState]] = {
    "planned": frozenset({"running", "blocked", "rejected", "abandoned"}),
    "running": frozenset({"completed", "blocked", "rejected"}),
    "blocked": frozenset({"running", "rejected", "abandoned"}),
    "completed": frozenset(),
    "rejected": frozenset(),
    "abandoned": frozenset(),
}
PRODUCTION_MUTATION_KINDS: frozenset[OperationKind] = frozenset(
    {"production_promotion", "rollback"}
)
TERMINAL_BATCH_STATES = frozenset({"closed", "rejected", "abandoned"})
TERMINAL_OPERATION_STATES = frozenset({"completed", "rejected", "abandoned"})


def stable_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _digest(value: dict[str, Any], prefix: str) -> str:
    return f"{prefix}_{hashlib.sha256(stable_json_bytes(value)).hexdigest()[:32]}"


def _iso_utc(value: str, field_name: str) -> None:
    if not value.endswith("Z"):
        raise ValueError(f"{field_name} must be UTC and end with Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field_name} must be valid ISO-8601") from exc


def _match(pattern: re.Pattern[str], value: str, field_name: str) -> None:
    if not pattern.fullmatch(value):
        raise ValueError(f"{field_name} is invalid")


@dataclass(frozen=True)
class ProductionIdentity:
    release_id: str
    manifest_sha256: str
    pointer_sha256: str

    def __post_init__(self) -> None:
        _match(RELEASE_ID_RE, self.release_id, "release_id")
        _match(SHA256_RE, self.manifest_sha256, "manifest_sha256")
        _match(SHA256_RE, self.pointer_sha256, "pointer_sha256")

    def to_identity(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class M13BatchSeed:
    source_repository: str
    source_commit_sha: str
    production: ProductionIdentity
    requested_by: str
    requested_at: str
    purpose: str
    review_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_repository or "/" not in self.source_repository:
            raise ValueError("source_repository must be owner/name")
        _match(SHA40_RE, self.source_commit_sha, "source_commit_sha")
        _iso_utc(self.requested_at, "requested_at")
        if not self.requested_by:
            raise ValueError("requested_by is required")
        if not self.purpose.strip():
            raise ValueError("purpose is required")
        if len(set(self.review_ids)) != len(self.review_ids):
            raise ValueError("review_ids cannot contain duplicates")
        for review_id in self.review_ids:
            _match(REVIEW_ID_RE, review_id, "review_id")

    def to_identity(self) -> dict[str, Any]:
        return {
            "schema_version": f"{SCHEMA_VERSION}/batch-seed",
            "source_repository": self.source_repository,
            "source_commit_sha": self.source_commit_sha,
            "production": self.production.to_identity(),
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "purpose": self.purpose,
            "review_ids": list(self.review_ids),
        }

    def batch_id(self) -> str:
        return _digest(self.to_identity(), "mbatch")


@dataclass(frozen=True)
class M13BatchRecord:
    batch_id: str
    state: BatchState
    seed: M13BatchSeed
    candidate_channel: str | None = None
    supersedes_batch_ids: tuple[str, ...] = ()
    rebuilt_from_batch_id: str | None = None

    def __post_init__(self) -> None:
        _match(BATCH_ID_RE, self.batch_id, "batch_id")
        if self.batch_id != self.seed.batch_id():
            raise ValueError("batch_id does not match seed identity")
        if self.candidate_channel is not None:
            _match(CANDIDATE_CHANNEL_RE, self.candidate_channel, "candidate_channel")
        if len(set(self.supersedes_batch_ids)) != len(self.supersedes_batch_ids):
            raise ValueError("supersedes_batch_ids cannot contain duplicates")
        for batch_id in self.supersedes_batch_ids:
            _match(BATCH_ID_RE, batch_id, "supersedes_batch_id")
        if self.rebuilt_from_batch_id is not None:
            _match(BATCH_ID_RE, self.rebuilt_from_batch_id, "rebuilt_from_batch_id")
            if self.rebuilt_from_batch_id == self.batch_id:
                raise ValueError("batch cannot rebuild from itself")
        if (
            self.state in {"candidate_ready", "awaiting_production_slot", "promoting"}
            and self.candidate_channel is None
        ):
            raise ValueError("candidate_channel is required for candidate states")

    @classmethod
    def from_seed(
        cls,
        seed: M13BatchSeed,
        *,
        state: BatchState = "planned",
        candidate_channel: str | None = None,
        supersedes_batch_ids: tuple[str, ...] = (),
        rebuilt_from_batch_id: str | None = None,
    ) -> M13BatchRecord:
        return cls(
            batch_id=seed.batch_id(),
            state=state,
            seed=seed,
            candidate_channel=candidate_channel,
            supersedes_batch_ids=supersedes_batch_ids,
            rebuilt_from_batch_id=rebuilt_from_batch_id,
        )

    def to_identity(self) -> dict[str, Any]:
        return {
            "schema_version": f"{SCHEMA_VERSION}/batch-record",
            "batch_id": self.batch_id,
            "state": self.state,
            "seed": self.seed.to_identity(),
            "candidate_channel": self.candidate_channel,
            "supersedes_batch_ids": list(self.supersedes_batch_ids),
            "rebuilt_from_batch_id": self.rebuilt_from_batch_id,
            "terminal": self.state in TERMINAL_BATCH_STATES,
        }


@dataclass(frozen=True)
class ExpectedPreviousProduction:
    production: ProductionIdentity
    checked_at: str

    def __post_init__(self) -> None:
        _iso_utc(self.checked_at, "checked_at")

    def to_identity(self) -> dict[str, Any]:
        return {
            "production": self.production.to_identity(),
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True)
class M13OperationRequest:
    kind: OperationKind
    batch_id: str
    requested_by: str
    requested_at: str
    expected_previous_production: ExpectedPreviousProduction
    artifact_names: tuple[str, ...] = ()
    planning_only: bool = True
    requires_production_slot: bool = False

    def __post_init__(self) -> None:
        _match(BATCH_ID_RE, self.batch_id, "batch_id")
        if not self.requested_by:
            raise ValueError("requested_by is required")
        _iso_utc(self.requested_at, "requested_at")
        if len(set(self.artifact_names)) != len(self.artifact_names):
            raise ValueError("artifact_names cannot contain duplicates")
        for name in self.artifact_names:
            _match(ARTIFACT_NAME_RE, name, "artifact_name")
        if self.kind in PRODUCTION_MUTATION_KINDS:
            if self.planning_only:
                raise ValueError("production mutations cannot be planning_only")
            if not self.requires_production_slot:
                raise ValueError("production mutations require a production slot")
        elif self.requires_production_slot:
            raise ValueError("only production mutations may require a production slot")

    def to_identity(self) -> dict[str, Any]:
        return {
            "schema_version": f"{SCHEMA_VERSION}/operation-request",
            "kind": self.kind,
            "batch_id": self.batch_id,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "expected_previous_production": self.expected_previous_production.to_identity(),
            "artifact_names": list(self.artifact_names),
            "planning_only": self.planning_only,
            "requires_production_slot": self.requires_production_slot,
        }

    def operation_id(self) -> str:
        return _digest(self.to_identity(), "mop")


@dataclass(frozen=True)
class M13OperationResult:
    operation_id: str
    request: M13OperationRequest
    state: OperationState
    result_at: str
    evidence_refs: tuple[str, ...] = ()
    blocked_reason: str | None = None
    rejection_reason: str | None = None
    governance: dict[str, bool] = field(default_factory=lambda: dict(GOVERNANCE_NO_WRITE))

    def __post_init__(self) -> None:
        _match(OPERATION_ID_RE, self.operation_id, "operation_id")
        if self.operation_id != self.request.operation_id():
            raise ValueError("operation_id does not match request identity")
        _iso_utc(self.result_at, "result_at")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs cannot contain duplicates")
        if self.state == "blocked" and not self.blocked_reason:
            raise ValueError("blocked operations require blocked_reason")
        if self.state == "rejected" and not self.rejection_reason:
            raise ValueError("rejected operations require rejection_reason")
        if self.state not in {"blocked", "rejected"} and (
            self.blocked_reason or self.rejection_reason
        ):
            raise ValueError("terminal reasons are only allowed on blocked/rejected states")
        expected_governance = dict(GOVERNANCE_NO_WRITE)
        if self.request.kind in PRODUCTION_MUTATION_KINDS:
            expected_governance = {
                **expected_governance,
                "release_write_permitted": True,
                "production_write_permitted": True,
                "permanent_ledger_append_permitted": True,
            }
        if self.governance != expected_governance:
            raise ValueError("governance boundary does not match operation kind")

    def to_identity(self) -> dict[str, Any]:
        return {
            "schema_version": f"{SCHEMA_VERSION}/operation-result",
            "operation_id": self.operation_id,
            "request": self.request.to_identity(),
            "state": self.state,
            "result_at": self.result_at,
            "evidence_refs": list(self.evidence_refs),
            "blocked_reason": self.blocked_reason,
            "rejection_reason": self.rejection_reason,
            "terminal": self.state in TERMINAL_OPERATION_STATES,
            "governance": self.governance,
        }


def validate_batch_transition(current: BatchState, target: BatchState) -> None:
    if target not in BATCH_TRANSITIONS[current]:
        raise ValueError(f"invalid batch transition: {current} -> {target}")


def validate_operation_transition(current: OperationState, target: OperationState) -> None:
    if target not in OPERATION_TRANSITIONS[current]:
        raise ValueError(f"invalid operation transition: {current} -> {target}")


def assert_expected_previous_production(
    *,
    expected: ProductionIdentity,
    observed: ProductionIdentity,
) -> None:
    if expected != observed:
        raise ValueError("expected previous production identity is stale")


def production_slot_key(production: ProductionIdentity) -> str:
    payload = {"schema_version": f"{SCHEMA_VERSION}/production-slot", **production.to_identity()}
    return _digest(payload, "mopslot")
