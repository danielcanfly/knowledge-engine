from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .compiler_contract_v1 import CompilerFailure
from .intake_v1 import canonical_json_bytes
from .storage import sha256_bytes

SYNTHESIZER_VERSION = "provider-neutral-synthesis/1.0.0"
RESOLUTION_BATCH_RE = re.compile(r"^rslv_[a-f0-9]{64}$")
SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{2,119}$")
PROPOSAL_KINDS = {
    "concept_create",
    "concept_update",
    "alias_add",
    "supersession_update",
}
ELIGIBLE_OUTCOMES = {
    "new_concept": "concept_create",
    "existing_concept_update": "concept_update",
    "alias": "alias_add",
    "supersession": "supersession_update",
}


@dataclass(frozen=True)
class SynthesisProposalRequest:
    resolution_batch_id: str
    proposed_at: str
    synthesizer_version: str = SYNTHESIZER_VERSION
    provider: str = "none"
    max_proposals: int = 10000

    def validate(self) -> None:
        if not RESOLUTION_BATCH_RE.fullmatch(self.resolution_batch_id):
            raise CompilerFailure(
                "SYNTHESIS_RESOLUTION_BATCH_INVALID",
                "request",
                "resolution batch ID invalid",
            )
        if not self.proposed_at.endswith("Z"):
            raise CompilerFailure(
                "SYNTHESIS_TIMESTAMP_INVALID", "request", "proposed_at must end in Z"
            )
        try:
            datetime.fromisoformat(self.proposed_at[:-1] + "+00:00")
        except ValueError as exc:
            raise CompilerFailure(
                "SYNTHESIS_TIMESTAMP_INVALID",
                "request",
                "proposed_at must be valid ISO-8601",
            ) from exc
        if not SAFE_VERSION_RE.fullmatch(self.synthesizer_version):
            raise CompilerFailure(
                "SYNTHESIZER_VERSION_INVALID", "request", "synthesizer version invalid"
            )
        if self.provider != "none":
            raise CompilerFailure(
                "SYNTHESIS_PROVIDER_NOT_NEUTRAL",
                "request",
                "M11.4 permits no provider invocation",
            )
        if not 1 <= self.max_proposals <= 200000:
            raise CompilerFailure(
                "SYNTHESIS_LIMIT_INVALID", "request", "max proposals invalid"
            )

    def identity(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-compiler-synthesis-request/v1",
            **asdict(self),
        }

    def attempt_id(self) -> str:
        return "satt_" + sha256_bytes(canonical_json_bytes(self.identity()))


@dataclass(frozen=True)
class SynthesisProposalResult:
    proposal_batch_id: str
    resolution_batch_id: str
    status: str
    result_key: str
    event_keys: tuple[str, ...]
    proposal_count: int = 0
    quarantine_count: int = 0
    proposal_prefix: str | None = None
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
