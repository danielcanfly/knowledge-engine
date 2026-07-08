from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .compiler_contract_v1 import CompilerFailure
from .compiler_source_v1 import SOURCE_REPOSITORY
from .intake_v1 import canonical_json_bytes
from .storage import ObjectStore, sha256_bytes

RESOLVER_VERSION = "source-aware-resolution/1.0.0"
RUN_ID_RE = re.compile(r"^crun_[a-f0-9]{64}$")
SHA_RE = re.compile(r"^[a-f0-9]{40}$")
SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{2,119}$")
RESOLUTION_OUTCOMES = {
    "new_concept",
    "existing_concept_update",
    "alias",
    "duplicate",
    "contradiction",
    "supersession",
    "unresolved_conflict",
    "rejected_unsupported_claim",
}


@dataclass(frozen=True)
class SourceResolutionRequest:
    compiler_run_id: str
    source_repository: str
    source_commit_sha: str
    resolved_at: str
    resolver_version: str = RESOLVER_VERSION
    strong_match_threshold: float = 0.55
    contradiction_threshold: float = 0.72
    max_candidates: int = 10000

    def validate(self) -> None:
        if not RUN_ID_RE.fullmatch(self.compiler_run_id):
            raise CompilerFailure("RESOLUTION_RUN_ID_INVALID", "request", "compiler run ID invalid")
        if self.source_repository != SOURCE_REPOSITORY:
            raise CompilerFailure(
                "SOURCE_REPOSITORY_INVALID", "request", "unexpected source repository"
            )
        if not SHA_RE.fullmatch(self.source_commit_sha):
            raise CompilerFailure("SOURCE_SHA_INVALID", "request", "source SHA invalid")
        if not self.resolved_at.endswith("Z"):
            raise CompilerFailure(
                "RESOLUTION_TIMESTAMP_INVALID", "request", "resolved_at must end in Z"
            )
        try:
            datetime.fromisoformat(self.resolved_at[:-1] + "+00:00")
        except ValueError as exc:
            raise CompilerFailure(
                "RESOLUTION_TIMESTAMP_INVALID", "request", "resolved_at must be valid ISO-8601"
            ) from exc
        if not SAFE_VERSION_RE.fullmatch(self.resolver_version):
            raise CompilerFailure("RESOLVER_VERSION_INVALID", "request", "resolver version invalid")
        if not 0 < self.strong_match_threshold <= 1:
            raise CompilerFailure(
                "RESOLUTION_THRESHOLD_INVALID", "request", "strong threshold invalid"
            )
        if not 0 < self.contradiction_threshold <= 1:
            raise CompilerFailure(
                "RESOLUTION_THRESHOLD_INVALID", "request", "contradiction threshold invalid"
            )
        if not 1 <= self.max_candidates <= 200000:
            raise CompilerFailure("RESOLUTION_LIMIT_INVALID", "request", "max candidates invalid")

    def identity(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-compiler-resolution-request/v1",
            **asdict(self),
        }

    def attempt_id(self) -> str:
        return "ratt_" + sha256_bytes(canonical_json_bytes(self.identity()))


@dataclass(frozen=True)
class ResolutionBatchResult:
    resolution_batch_id: str
    compiler_run_id: str
    status: str
    result_key: str
    event_keys: tuple[str, ...]
    resolution_count: int = 0
    outcome_counts: dict[str, int] | None = None
    source_snapshot_sha256: str | None = None
    resolution_prefix: str | None = None
    rejection_key: str | None = None
    failure_code: str | None = None
    idempotent: bool = False
    canonical_write_permitted: bool = False
    github_write_permitted: bool = False
    production_write_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["event_keys"] = list(self.event_keys)
        value["outcome_counts"] = dict(sorted((self.outcome_counts or {}).items()))
        return value

    def evidence(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("idempotent")
        return value


def load_json_object(store: ObjectStore, key: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(store.get(key))
    except FileNotFoundError as exc:
        raise CompilerFailure(
            "RESOLUTION_OBJECT_MISSING", "validate", f"missing {label}", key=key
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompilerFailure(
            "RESOLUTION_OBJECT_INVALID", "validate", f"invalid {label}", key=key
        ) from exc
    if not isinstance(value, dict):
        raise CompilerFailure("RESOLUTION_OBJECT_INVALID", "validate", f"{label} must be an object")
    return value


def digest_object(store: ObjectStore, key: str, expected: str | None = None) -> str:
    try:
        data = store.get(key)
    except FileNotFoundError as exc:
        raise CompilerFailure(
            "RESOLUTION_OBJECT_MISSING", "validate", "required object missing", key=key
        ) from exc
    digest = sha256_bytes(data)
    if expected is not None and digest != expected:
        raise CompilerFailure(
            "RESOLUTION_HASH_MISMATCH", "validate", "object hash mismatch", key=key
        )
    return digest
