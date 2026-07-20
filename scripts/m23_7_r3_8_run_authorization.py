from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

SCHEMA_VERSION = "knowledge-engine-r3-8-run-authorization/v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[0-9]{1,20}$")
WORKER = re.compile(r"^knowledge-engine-r3-8-[0-9]{1,20}$")
ACTION = re.compile(r"^[a-z_]{1,40}$")
MAX_AUTHORIZATION_BYTES = 50_000

AUTHORIZATION_KEYS = {
    "schema_version",
    "affected_run_id",
    "affected_engine_sha",
    "worker_name",
    "allowed_actions",
    "observation_artifact_sha256",
    "expires_at",
    "production_mutation_authorized",
    "qdrant_mutation_authorized",
    "r2_mutation_authorized",
    "source_mutation_authorized",
    "blocker_clearance_authorized",
    "authorization_sha256",
}


class RunAuthorizationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _validate_false_authority(value: dict[str, Any]) -> None:
    for key in (
        "production_mutation_authorized",
        "qdrant_mutation_authorized",
        "r2_mutation_authorized",
        "source_mutation_authorized",
        "blocker_clearance_authorized",
    ):
        if value.get(key) is not False:
            raise RunAuthorizationError("authorization_authority_boundary")


def _validate_expiry(value: str) -> None:
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RunAuthorizationError("authorization_expiry_invalid") from exc
    if expiry.tzinfo is None:
        raise RunAuthorizationError("authorization_expiry_invalid")
    if expiry <= datetime.now(UTC):
        raise RunAuthorizationError("authorization_expired")


def load_authorization(
    path: Path,
    *,
    requested_action: str,
    actual_head: str,
) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if len(raw) > MAX_AUTHORIZATION_BYTES:
        raise RunAuthorizationError("authorization_oversized")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != AUTHORIZATION_KEYS:
        raise RunAuthorizationError("authorization_keys")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise RunAuthorizationError("authorization_schema")
    supplied = value.get("authorization_sha256")
    unsigned = dict(value)
    unsigned.pop("authorization_sha256", None)
    if not isinstance(supplied, str) or supplied != canonical_sha256(unsigned):
        raise RunAuthorizationError("authorization_digest_mismatch")
    if not isinstance(actual_head, str) or not HEX40.fullmatch(actual_head):
        raise RunAuthorizationError("authorization_exact_head_invalid")
    if not isinstance(value.get("affected_engine_sha"), str) or not HEX40.fullmatch(
        value["affected_engine_sha"]
    ):
        raise RunAuthorizationError("authorization_affected_engine_sha")
    if not isinstance(value.get("affected_run_id"), str) or not RUN_ID.fullmatch(
        value["affected_run_id"]
    ):
        raise RunAuthorizationError("authorization_run_id")
    expected_worker = f"knowledge-engine-r3-8-{value['affected_run_id']}"
    if value.get("worker_name") != expected_worker or not WORKER.fullmatch(
        expected_worker
    ):
        raise RunAuthorizationError("authorization_worker_identity")
    actions = value.get("allowed_actions")
    if (
        not isinstance(actions, list)
        or not actions
        or len(actions) != len(set(actions))
        or actions != sorted(actions)
        or any(not isinstance(action, str) or not ACTION.fullmatch(action) for action in actions)
    ):
        raise RunAuthorizationError("authorization_actions")
    if requested_action not in actions:
        raise RunAuthorizationError("authorization_action_not_allowed")
    if (
        not isinstance(value.get("observation_artifact_sha256"), str)
        or not HEX64.fullmatch(value["observation_artifact_sha256"])
    ):
        raise RunAuthorizationError("authorization_artifact_digest")
    if not isinstance(value.get("expires_at"), str):
        raise RunAuthorizationError("authorization_expiry_invalid")
    _validate_expiry(value["expires_at"])
    _validate_false_authority(value)
    return value
