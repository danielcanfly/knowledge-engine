from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .batch_spec import REGISTRY_PATH, REGISTRY_SCHEMA, STATES, load_batch_spec
from .errors import IntegrityError


@dataclass(frozen=True)
class RegistryEntry:
    batch_id: str
    spec_path: str
    lifecycle_state: str
    candidate_channel: str | None
    operation_id: str | None
    request_path: str | None


@dataclass(frozen=True)
class BatchRegistry:
    raw: dict[str, Any]
    path: Path
    entries: tuple[RegistryEntry, ...]


def _required(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError(f"{label} field is required: {key}")
    return value.strip()


def _optional(payload: dict[str, Any], key: str, label: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError(f"{label} field must be a non-empty string: {key}")
    return value.strip()


def load_batch_registry(
    registry_path: str | Path = REGISTRY_PATH,
) -> BatchRegistry:
    path = Path(registry_path)
    if path != REGISTRY_PATH:
        raise IntegrityError(f"batch registry path must be {str(REGISTRY_PATH)!r}")
    if not path.is_file():
        raise IntegrityError(f"batch registry does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntegrityError("batch registry is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise IntegrityError("batch registry must be a JSON object")
    if payload.get("schema_version") != REGISTRY_SCHEMA:
        raise IntegrityError(
            f"batch registry schema_version must be {REGISTRY_SCHEMA!r}"
        )
    batches = payload.get("batches")
    if not isinstance(batches, list):
        raise IntegrityError("batch registry batches must be a list")

    entries: list[RegistryEntry] = []
    for index, item in enumerate(batches):
        if not isinstance(item, dict):
            raise IntegrityError(f"batch registry entry {index} must be an object")
        state = _required(item, "lifecycle_state", f"registry entry {index}")
        if state not in STATES:
            raise IntegrityError(f"registry entry {index} lifecycle_state is invalid")
        entries.append(
            RegistryEntry(
                batch_id=_required(item, "batch_id", f"registry entry {index}"),
                spec_path=_required(item, "spec_path", f"registry entry {index}"),
                lifecycle_state=state,
                candidate_channel=_optional(
                    item, "candidate_channel", f"registry entry {index}"
                ),
                operation_id=_optional(
                    item, "operation_id", f"registry entry {index}"
                ),
                request_path=_optional(
                    item, "request_path", f"registry entry {index}"
                ),
            )
        )
    _reject_duplicates(entries)
    return BatchRegistry(raw=dict(payload), path=path, entries=tuple(entries))


def _reject_duplicates(entries: list[RegistryEntry]) -> None:
    for field in (
        "batch_id",
        "spec_path",
        "candidate_channel",
        "operation_id",
        "request_path",
    ):
        seen: set[str] = set()
        for entry in entries:
            value = getattr(entry, field)
            if value is None:
                continue
            if value in seen:
                raise IntegrityError(f"batch registry contains duplicate {field}: {value}")
            seen.add(value)


def validate_batch_registry(registry: BatchRegistry) -> dict[str, Any]:
    batches: list[dict[str, str]] = []
    for entry in registry.entries:
        spec = load_batch_spec(entry.spec_path)
        expected = {
            "batch_id": spec.batch_id,
            "lifecycle_state": spec.lifecycle_state,
            "candidate_channel": spec.candidate_channel,
            "operation_id": spec.operation_id,
            "request_path": spec.request_path,
        }
        for field, value in expected.items():
            if getattr(entry, field) != value:
                raise IntegrityError(
                    f"batch registry {field} mismatch for {entry.batch_id}: "
                    f"expected {value!r}, got {getattr(entry, field)!r}"
                )
        batches.append(
            {
                "batch_id": spec.batch_id,
                "lifecycle_state": spec.lifecycle_state,
                "spec_path": str(spec.path),
            }
        )
    return {
        "status": "valid",
        "schema_version": REGISTRY_SCHEMA,
        "batch_count": len(batches),
        "batches": batches,
    }


def write_registry_evidence(
    *,
    registry: BatchRegistry,
    evidence_dir: Path,
) -> dict[str, Any]:
    result = validate_batch_registry(registry)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "batch-registry-validation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result
