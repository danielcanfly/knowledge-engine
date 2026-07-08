from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .compiler_contract_v1 import CompilerFailure
from .intake_v1 import canonical_json_bytes
from .storage import sha256_bytes

REVIEW_PACKET_VERSION = "compiler-review-packet/1.0.0"
PROPOSAL_BATCH_RE = re.compile(r"^synp_[a-f0-9]{64}$")
SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{2,119}$")


@dataclass(frozen=True)
class ReviewerPacketRequest:
    proposal_batch_id: str
    assembled_at: str
    packet_version: str = REVIEW_PACKET_VERSION
    max_items: int = 10000

    def validate(self) -> None:
        if not PROPOSAL_BATCH_RE.fullmatch(self.proposal_batch_id):
            raise CompilerFailure(
                "REVIEW_PACKET_PROPOSAL_BATCH_INVALID",
                "request",
                "proposal batch ID invalid",
            )
        if not self.assembled_at.endswith("Z"):
            raise CompilerFailure(
                "REVIEW_PACKET_TIMESTAMP_INVALID",
                "request",
                "assembled_at must end in Z",
            )
        try:
            datetime.fromisoformat(self.assembled_at[:-1] + "+00:00")
        except ValueError as exc:
            raise CompilerFailure(
                "REVIEW_PACKET_TIMESTAMP_INVALID",
                "request",
                "assembled_at must be valid ISO-8601",
            ) from exc
        if not SAFE_VERSION_RE.fullmatch(self.packet_version):
            raise CompilerFailure(
                "REVIEW_PACKET_VERSION_INVALID", "request", "packet version invalid"
            )
        if not 1 <= self.max_items <= 200000:
            raise CompilerFailure(
                "REVIEW_PACKET_LIMIT_INVALID", "request", "max items invalid"
            )

    def identity(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-compiler-reviewer-packet-request/v1",
            **asdict(self),
        }

    def attempt_id(self) -> str:
        return "rpatt_" + sha256_bytes(canonical_json_bytes(self.identity()))


@dataclass(frozen=True)
class ReviewerPacketResult:
    reviewer_packet_id: str
    proposal_batch_id: str
    status: str
    result_key: str
    event_keys: tuple[str, ...]
    proposal_count: int = 0
    quarantine_count: int = 0
    high_risk_count: int = 0
    packet_prefix: str | None = None
    rejection_key: str | None = None
    failure_code: str | None = None
    idempotent: bool = False
    human_decision_required: bool = True
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
