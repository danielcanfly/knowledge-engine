from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import IntegrityError, ReleaseConflictError
from .intake_v1 import canonical_json_bytes
from .storage import ObjectStore, sha256_bytes

M25_2_ENGINE_BASE_SHA = "8830a59d34dc0df9305b53f9bbb9eff63e03d225"
SOURCE_SHA = "acf78596ace8a7366688ccef72b507204d09d9f9"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
M25_1_ENTRY_BASELINE_SHA256 = (
    "8bfee144b20286be95d32546932115bd8c6623d396db21715072a70054eefca1"
)
M25_1_ACCEPTANCE_SHA256 = (
    "2bffa688f3f4fe62dd0ce7f15b395bad96d99e50f293b9c110b340a065b027e2"
)

INVENTORY_SCHEMA = "knowledge-engine-m25-source-inventory/v1"
BATCH_PLAN_SCHEMA = "knowledge-engine-m25-batch-plan/v1"
CHECKPOINT_SCHEMA = "knowledge-engine-m25-admission-checkpoint/v1"
NORMALIZED_OUTPUT_SCHEMA = "knowledge-engine-m25-normalized-output/v1"
REPORT_SCHEMA = "knowledge-engine-m25-orchestrator-report/v1"
ADMISSION_PLAN_SCHEMA = "knowledge-engine-m25-admission-plan/v1"
ADMISSION_STATE_SCHEMA = "knowledge-engine-m25-admission-state/v1"
AUTHORITY_SCHEMA = "knowledge-engine-m25-authority-envelope/v1"
ADAPTER_SCHEMA = "knowledge-engine-m25-adapter-envelope/v1"

LOCAL_MARKDOWN_ADAPTER = "m25_adapter_intake_v1_local_markdown"
EXISTING_INTAKE_ADAPTER = "m25_adapter_intake_v1_existing_ref"
APPROVED_ADAPTER_IDS = {LOCAL_MARKDOWN_ADAPTER, EXISTING_INTAKE_ADAPTER}

MAX_INVENTORY_ITEMS = 10_000
MAX_DESCRIPTOR_BYTES = 100_000_000
MAX_BATCH_SOURCES = 100
MAX_BATCH_BYTES = 100_000_000
MAX_ATTEMPTS = 8

M25_2_TRANSITIONS = {
    "planned": {"acquiring", "blocked", "rejected"},
    "acquiring": {"snapshotted", "retryable", "blocked", "rejected"},
    "retryable": {"acquiring", "blocked", "rejected"},
    "snapshotted": {"normalized", "blocked", "rejected"},
    "normalized": set(),
    "blocked": set(),
    "rejected": set(),
}
ACTIONABLE_STATES = {"planned", "retryable"}
TERMINAL_M25_2_STATES = {"normalized", "blocked", "rejected"}

@dataclass(frozen=True)
class AdapterOutcome:
    status: str
    evidence_refs: tuple[str, ...] = ()
    snapshot_id: str | None = None
    snapshot_key: str | None = None
    snapshot_sha256: str | None = None
    derivative_id: str | None = None
    derivative_key: str | None = None
    derivative_sha256: str | None = None
    normalized_key: str | None = None
    normalized_sha256: str | None = None
    raw_blob_key: str | None = None
    raw_sha256: str | None = None
    raw_bytes: int | None = None
    failure_code: str | None = None
    retry_at: str | None = None

def _pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")

def _digest(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))

def _signed(value: Mapping[str, Any], field: str, code: str) -> str:
    unsigned = dict(value)
    claimed = unsigned.pop(field, None)
    if not isinstance(claimed, str) or claimed != _digest(unsigned):
        raise IntegrityError(code)
    return claimed

def _parse_time(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"M25-INTAKE-101 invalid {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrityError(f"M25-INTAKE-101 invalid {label}") from exc
    if parsed.tzinfo is None:
        raise IntegrityError(f"M25-INTAKE-101 invalid {label}")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")

def _text(value: Any, label: str, maximum: int = 1024) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"M25-INTAKE-102 invalid {label}")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise IntegrityError(f"M25-INTAKE-102 invalid {label}")
    return normalized

def _hex(value: Any, size: int, label: str) -> str:
    if not isinstance(value, str) or len(value) != size or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise IntegrityError(f"M25-INTAKE-103 invalid {label}")
    return value

def _artifact_ref(schema_version: str, object_key: str, payload: bytes) -> dict[str, str]:
    return {
        "schema_version": schema_version,
        "object_key": object_key,
        "sha256": sha256_bytes(payload),
    }

def _put_immutable(
    store: ObjectStore,
    key: str,
    data: bytes,
    *,
    content_type: str = "application/json",
) -> bool:
    digest = sha256_bytes(data)
    current = store.head(key)
    if current is not None:
        if current.sha256 != digest or store.get(key) != data:
            raise IntegrityError(f"M25-INTAKE-104 immutable collision at {key}")
        return True
    try:
        store.put(
            key,
            data,
            content_type=content_type,
            sha256=digest,
            only_if_absent=True,
        )
    except ReleaseConflictError as exc:
        current = store.head(key)
        if current is None or current.sha256 != digest or store.get(key) != data:
            raise IntegrityError(f"M25-INTAKE-104 immutable collision at {key}") from exc
        return True
    return False

AdapterExecutor = Callable[[ObjectStore, Mapping[str, Any], Path | None, str], AdapterOutcome]
