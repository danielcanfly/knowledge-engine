from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import IntegrityError

SPEC_SCHEMA = "governed-batch-spec/v2"
REGISTRY_SCHEMA = "governed-batch-registry/v1"
SPEC_ROOT = Path("governed_batches")
REGISTRY_PATH = SPEC_ROOT / "registry.json"

STATES = (
    "planned",
    "source_reviewed",
    "source_validated",
    "candidate_built",
    "runtime_accepted",
    "request_spec_committed",
    "production_promoted",
    "closed",
)
TRANSITIONS = {state: {STATES[index + 1]} for index, state in enumerate(STATES[:-1])}
TRANSITIONS["closed"] = set()

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RELEASE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$")


@dataclass(frozen=True)
class BatchSpec:
    raw: dict[str, Any]
    path: Path
    batch_id: str
    lifecycle_state: str
    candidate_channel: str | None
    operation_id: str | None
    request_path: str | None


@dataclass(frozen=True)
class RegistryEntry:
    batch_id: str
    spec_path: str
    lifecycle_state: str
    candidate_channel: str | None
    operation_id: str | None
    request_path: str | None


def _object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise IntegrityError(f"{label} does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntegrityError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise IntegrityError(f"{label} must be a JSON object")
    return payload


def _string(payload: dict[str, Any], key: str, label: str) -> str:
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


def _nested(payload: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise IntegrityError(f"{label} field must be an object: {key}")
    return value


def _state_at_least(state: str, required: str) -> bool:
    return STATES.index(state) >= STATES.index(required)


def validate_transition(current: str, target: str) -> None:
    if current not in TRANSITIONS or target not in TRANSITIONS[current]:
        raise IntegrityError(f"illegal lifecycle transition: {current} -> {target}")


def load_batch_spec(spec_path: str | Path) -> BatchSpec:
    path = Path(spec_path)
    if path.is_absolute() or path.parent != SPEC_ROOT or path.suffix != ".json":
        raise IntegrityError("batch spec path must match governed_batches/*.json")
    if path.name == REGISTRY_PATH.name:
        raise IntegrityError("registry.json is not a batch spec")
    payload = _object(path, "batch spec")
    if payload.get("schema_version") != SPEC_SCHEMA:
        raise IntegrityError(f"batch spec schema_version must be {SPEC_SCHEMA!r}")

    batch_id = _string(payload, "batch_id", "batch spec")
    if not SAFE_ID.fullmatch(batch_id) or path.stem != batch_id:
        raise IntegrityError("batch_id must be safe and match the filename")
    state = _string(payload, "lifecycle_state", "batch spec")
    if state not in STATES:
        raise IntegrityError("batch spec lifecycle_state is invalid")

    source = _nested(payload, "source", "batch spec")
    _string(source, "repository", "source")
    paths = source.get("paths")
    if not isinstance(paths, list) or not paths or len(paths) != len(set(paths)):
        raise IntegrityError("source paths must be a non-empty unique list")
    if not all(isinstance(item, str) and item.strip() for item in paths):
        raise IntegrityError("source paths must contain non-empty strings")
    source_sha = _optional(source, "sha", "source")
    if source_sha is not None and not SHA.fullmatch(source_sha):
        raise IntegrityError("source sha must be a lowercase 40-character SHA")

    for field in ("builder_sha", "foundation_sha"):
        value = _string(payload, field, "batch spec")
        if not SHA.fullmatch(value):
            raise IntegrityError(f"{field} must be a lowercase 40-character SHA")

    candidate = _nested(payload, "candidate", "batch spec")
    channel = _optional(candidate, "channel", "candidate")
    release_id = _optional(candidate, "release_id", "candidate")
    manifest = _optional(candidate, "manifest_sha256", "candidate")
    if release_id is not None and not RELEASE.fullmatch(release_id):
        raise IntegrityError("candidate release_id is invalid")
    if manifest is not None and not SHA256.fullmatch(manifest):
        raise IntegrityError("candidate manifest_sha256 is invalid")

    production = _nested(payload, "production_request", "batch spec")
    operation_id = _optional(production, "operation_id", "production_request")
    request_path = _optional(production, "request_path", "production_request")
    if operation_id is not None and not SAFE_ID.fullmatch(operation_id):
        raise IntegrityError("operation_id must be a safe lowercase identifier")
    if request_path is not None:
        request = Path(request_path)
        if request.is_absolute() or request.parent != Path("production_promotions"):
            raise IntegrityError("request_path must match production_promotions/*.json")
        if request.suffix != ".json":
            raise IntegrityError("request_path must be a JSON file")

    acceptance = _nested(payload, "acceptance", "batch spec")
    _string(acceptance, "public_query", "acceptance")
    _string(acceptance, "expected_citation_url", "acceptance")
    if _string(acceptance, "expected_public_status", "acceptance") not in {
        "answered",
        "not_found",
    }:
        raise IntegrityError("expected_public_status is invalid")
    acl_query = _optional(acceptance, "acl_query", "acceptance")
    acl_status = _optional(acceptance, "expected_acl_status", "acceptance")
    if acl_status not in {None, "answered", "not_found"}:
        raise IntegrityError("expected_acl_status is invalid")
    if (acl_query is None) != (acl_status is None):
        raise IntegrityError("ACL query and status must be configured together")
    if acceptance.get("raw_fallback_allowed") is not False:
        raise IntegrityError("raw_fallback_allowed must be false")

    if _state_at_least(state, "source_reviewed") and source_sha is None:
        raise IntegrityError("source sha is required from source_reviewed onward")
    if _state_at_least(state, "candidate_built") and None in {
        channel,
        release_id,
        manifest,
    }:
        raise IntegrityError("candidate identity is required from candidate_built onward")
    if _state_at_least(state, "request_spec_committed") and (
        operation_id is None or request_path is None
    ):
        raise IntegrityError("production request identity is required from request-spec onward")

    return BatchSpec(
        raw=dict(payload),
        path=path,
        batch_id=batch_id,
        lifecycle_state=state,
        candidate_channel=channel,
        operation_id=operation_id,
        request_path=request_path,
    )
