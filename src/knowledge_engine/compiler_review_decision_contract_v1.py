from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .compiler_contract_v1 import CompilerFailure
from .compiler_source_v1 import AUDIENCE_RANK, SOURCE_REPOSITORY
from .intake_v1 import canonical_json_bytes
from .storage import sha256_bytes

REVIEW_DECISION_VERSION = "compiler-review-decision/1.0.0"
SOURCE_PR_PACKAGE_VERSION = "compiler-source-pr-package/1.0.0"
PACKET_ID_RE = re.compile(r"^rvwp_[a-f0-9]{64}$")
DECISION_SET_ID_RE = re.compile(r"^rvwd_[a-f0-9]{64}$")
SHA_RE = re.compile(r"^[a-f0-9]{40}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@/-]{2,159}$")
SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{2,119}$")
DECISIONS = {"approved", "rejected", "needs_changes"}


def _validate_timestamp(value: str, label: str) -> None:
    if not value.endswith("Z"):
        raise CompilerFailure(
            "REVIEW_DECISION_TIMESTAMP_INVALID", "request", f"{label} must end in Z"
        )
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CompilerFailure(
            "REVIEW_DECISION_TIMESTAMP_INVALID",
            "request",
            f"{label} must be valid ISO-8601",
        ) from exc


@dataclass(frozen=True)
class ProposalDecisionInput:
    proposal_id: str
    decision: str
    notes: str
    approved_audience: str | None = None
    high_risk_acknowledged: bool = False

    def validate(self) -> None:
        if not self.proposal_id.startswith("cprop_") or len(self.proposal_id) != 70:
            raise CompilerFailure(
                "REVIEW_DECISION_PROPOSAL_ID_INVALID",
                "request",
                "proposal ID invalid",
            )
        if self.decision not in DECISIONS:
            raise CompilerFailure(
                "REVIEW_DECISION_VALUE_INVALID",
                "request",
                "decision must be approved, rejected, or needs_changes",
            )
        if not self.notes.strip() or len(self.notes) > 4000:
            raise CompilerFailure(
                "REVIEW_DECISION_NOTES_INVALID",
                "request",
                "decision notes must contain 1-4000 characters",
            )
        if self.decision == "approved":
            if self.approved_audience not in AUDIENCE_RANK:
                raise CompilerFailure(
                    "REVIEW_DECISION_AUDIENCE_REQUIRED",
                    "request",
                    "approved decisions require approved_audience",
                )
        elif self.approved_audience is not None:
            raise CompilerFailure(
                "REVIEW_DECISION_AUDIENCE_FORBIDDEN",
                "request",
                "non-approved decisions cannot set approved_audience",
            )
        if self.decision != "approved" and self.high_risk_acknowledged:
            raise CompilerFailure(
                "REVIEW_DECISION_RISK_ACK_INVALID",
                "request",
                "risk acknowledgement is only valid for approval",
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompilerReviewDecisionRequest:
    reviewer_packet_id: str
    reviewer: str
    reviewed_at: str
    notes: str
    decisions: tuple[ProposalDecisionInput, ...]
    decision_version: str = REVIEW_DECISION_VERSION

    def validate(self) -> None:
        if not PACKET_ID_RE.fullmatch(self.reviewer_packet_id):
            raise CompilerFailure(
                "REVIEW_DECISION_PACKET_ID_INVALID",
                "request",
                "reviewer packet ID invalid",
            )
        if not SAFE_ID_RE.fullmatch(self.reviewer):
            raise CompilerFailure(
                "REVIEW_DECISION_REVIEWER_INVALID",
                "request",
                "reviewer identity invalid",
            )
        _validate_timestamp(self.reviewed_at, "reviewed_at")
        if not self.notes.strip() or len(self.notes) > 4000:
            raise CompilerFailure(
                "REVIEW_DECISION_NOTES_INVALID",
                "request",
                "review notes must contain 1-4000 characters",
            )
        if not SAFE_VERSION_RE.fullmatch(self.decision_version):
            raise CompilerFailure(
                "REVIEW_DECISION_VERSION_INVALID",
                "request",
                "decision version invalid",
            )
        if not self.decisions:
            raise CompilerFailure(
                "REVIEW_DECISION_SET_EMPTY", "request", "decision set is empty"
            )
        proposal_ids: set[str] = set()
        for item in self.decisions:
            item.validate()
            if item.proposal_id in proposal_ids:
                raise CompilerFailure(
                    "REVIEW_DECISION_DUPLICATE",
                    "request",
                    "proposal decision duplicated",
                )
            proposal_ids.add(item.proposal_id)

    def identity(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-compiler-review-decision-request/v1",
            "reviewer_packet_id": self.reviewer_packet_id,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "notes": self.notes,
            "decisions": [item.to_dict() for item in self.decisions],
            "decision_version": self.decision_version,
        }

    def attempt_id(self) -> str:
        return "rda_" + sha256_bytes(canonical_json_bytes(self.identity()))


@dataclass(frozen=True)
class CompilerReviewDecisionResult:
    decision_set_id: str
    reviewer_packet_id: str
    status: str
    result_key: str
    event_keys: tuple[str, ...]
    decision_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    needs_changes_count: int = 0
    source_package_permitted: bool = False
    decision_prefix: str | None = None
    rejection_key: str | None = None
    failure_code: str | None = None
    idempotent: bool = False
    canonical_write_permitted: bool = False
    github_write_permitted: bool = False
    production_write_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["event_keys"] = list(self.event_keys)
        return value

    def evidence(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("idempotent")
        return value


@dataclass(frozen=True)
class CompilerSourcePRPackageRequest:
    decision_set_id: str
    source_repository: str
    source_commit_sha: str
    packaged_at: str
    actor: str
    package_version: str = SOURCE_PR_PACKAGE_VERSION

    def validate(self) -> None:
        if not DECISION_SET_ID_RE.fullmatch(self.decision_set_id):
            raise CompilerFailure(
                "SOURCE_PR_DECISION_SET_ID_INVALID",
                "request",
                "decision set ID invalid",
            )
        if self.source_repository != SOURCE_REPOSITORY:
            raise CompilerFailure(
                "SOURCE_REPOSITORY_INVALID", "request", "unexpected Source repository"
            )
        if not SHA_RE.fullmatch(self.source_commit_sha):
            raise CompilerFailure(
                "SOURCE_SHA_INVALID", "request", "Source SHA must be exact lowercase"
            )
        _validate_timestamp(self.packaged_at, "packaged_at")
        if not SAFE_ID_RE.fullmatch(self.actor):
            raise CompilerFailure(
                "SOURCE_PR_ACTOR_INVALID", "request", "actor identity invalid"
            )
        if not SAFE_VERSION_RE.fullmatch(self.package_version):
            raise CompilerFailure(
                "SOURCE_PR_PACKAGE_VERSION_INVALID",
                "request",
                "package version invalid",
            )

    def identity(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-compiler-source-pr-package-request/v1",
            **asdict(self),
        }

    def attempt_id(self) -> str:
        return "spra_" + sha256_bytes(canonical_json_bytes(self.identity()))


@dataclass(frozen=True)
class CompilerSourcePRPackageResult:
    source_pr_package_id: str
    decision_set_id: str
    status: str
    result_key: str
    event_keys: tuple[str, ...]
    approved_proposal_count: int = 0
    file_plan_count: int = 0
    manual_review_count: int = 0
    package_prefix: str | None = None
    package_manifest_sha256: str | None = None
    rejection_key: str | None = None
    failure_code: str | None = None
    idempotent: bool = False
    source_pr_creation_permitted: bool = False
    direct_apply_permitted: bool = False
    canonical_write_permitted: bool = False
    github_write_permitted: bool = False
    production_write_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["event_keys"] = list(self.event_keys)
        return value

    def evidence(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("idempotent")
        return value
