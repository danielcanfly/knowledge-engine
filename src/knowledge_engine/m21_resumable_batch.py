from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .errors import IntegrityError

MAX_BATCH_SIZE = 100
MAX_BATCHES = 500
MAX_ATTEMPTS = 8
ACTIONABLE_STATES = {"pending", "retryable"}
TERMINAL_STATES = {"completed", "failed", "skipped"}
ALL_STATES = ACTIONABLE_STATES | TERMINAL_STATES | {"running"}
ALLOWED_TRANSITIONS = {
    "pending": {"running", "skipped"},
    "running": {"completed", "failed", "retryable"},
    "retryable": {"running", "failed"},
    "completed": set(),
    "failed": set(),
    "skipped": set(),
}


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _parse_time(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"M21-BATCH-101 invalid {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrityError(f"M21-BATCH-101 invalid {label}") from exc
    if parsed.tzinfo is None:
        raise IntegrityError(f"M21-BATCH-101 invalid {label}")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validate_inventory(snapshot: dict[str, Any]) -> None:
    valid_schema = snapshot.get("schema") == "knowledge-engine-blog-inventory/v1"
    if not isinstance(snapshot, dict) or not valid_schema:
        raise IntegrityError("M21-BATCH-102 invalid inventory schema")
    if snapshot.get("authority") != "evidence_only":
        raise IntegrityError("M21-BATCH-103 inventory authority drift")
    grants_authority = (
        snapshot.get("canonical_knowledge") is not False
        or snapshot.get("production_authority") is not False
    )
    if grants_authority:
        raise IntegrityError("M21-BATCH-104 inventory grants forbidden authority")
    claimed = snapshot.get("snapshot_sha256")
    if not isinstance(claimed, str) or len(claimed) != 64:
        raise IntegrityError("M21-BATCH-105 invalid inventory digest")
    unsigned = dict(snapshot)
    unsigned.pop("snapshot_sha256", None)
    if _digest(unsigned) != claimed:
        raise IntegrityError("M21-BATCH-106 inventory digest mismatch")
    identity = snapshot.get("identity")
    if not isinstance(identity, dict):
        raise IntegrityError("M21-BATCH-107 inventory identity missing")
    for key in ("engine_sha", "source_sha", "foundation_sha"):
        value = identity.get(key)
        if not isinstance(value, str) or len(value) != 40:
            raise IntegrityError(f"M21-BATCH-108 invalid {key}")
    _parse_time(identity.get("captured_at"), label="inventory capture time")
    items = snapshot.get("items")
    if not isinstance(items, list) or not items:
        raise IntegrityError("M21-BATCH-109 inventory items missing")


def _item_key(item: dict[str, Any]) -> str:
    payload = {
        "canonical_url": item.get("canonical_url"),
        "content_sha256": item.get("content_sha256"),
        "source_kind": item.get("source_kind"),
        "locator": item.get("locator"),
        "audience": item.get("audience"),
    }
    for key, value in payload.items():
        if not isinstance(value, str) or not value:
            raise IntegrityError(f"M21-BATCH-110 invalid item {key}")
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def build_batch_plan(snapshot: dict[str, Any], *, batch_size: int = 25) -> dict[str, Any]:
    _validate_inventory(snapshot)
    valid_size = isinstance(batch_size, int) and not isinstance(batch_size, bool)
    if not valid_size or not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise IntegrityError("M21-BATCH-111 batch size exceeds bounds")

    planned: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in snapshot["items"]:
        if not isinstance(item, dict):
            raise IntegrityError("M21-BATCH-112 inventory item must be an object")
        unavailable = item.get("access_status") in {"blocked", "missing"}
        if item.get("intake_status") == "rejected" or unavailable:
            continue
        key = _item_key(item)
        if key in seen_keys:
            raise IntegrityError("M21-BATCH-113 duplicate stable item key")
        seen_keys.add(key)
        expected_action = "verify" if item.get("intake_status") == "captured" else "capture"
        planned.append(
            {
                "item_key": key,
                "canonical_url": item["canonical_url"],
                "content_sha256": item["content_sha256"],
                "source_kind": item["source_kind"],
                "locator": item["locator"],
                "audience": item["audience"],
                "expected_action": expected_action,
            }
        )
    planned.sort(key=lambda item: (item["canonical_url"], item["item_key"]))
    if not planned:
        raise IntegrityError("M21-BATCH-114 no actionable inventory items")

    batches: list[dict[str, Any]] = []
    for offset in range(0, len(planned), batch_size):
        rows = planned[offset : offset + batch_size]
        batch_index = len(batches)
        batch_seed = {
            "inventory_sha256": snapshot["snapshot_sha256"],
            "batch_index": batch_index,
            "item_keys": [row["item_key"] for row in rows],
        }
        batches.append(
            {
                "batch_index": batch_index,
                "batch_id": hashlib.sha256(_canonical_bytes(batch_seed)).hexdigest(),
                "items": rows,
            }
        )
    if len(batches) > MAX_BATCHES:
        raise IntegrityError("M21-BATCH-115 batch count exceeds bounds")

    plan = {
        "schema": "knowledge-engine-resumable-batch/v1",
        "authority": "evidence_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "inventory_sha256": snapshot["snapshot_sha256"],
        "identity": snapshot["identity"],
        "batch_size": batch_size,
        "item_count": len(planned),
        "batches": batches,
    }
    plan["plan_sha256"] = _digest(plan)
    return plan


def build_initial_checkpoint(plan: dict[str, Any], *, created_at: str) -> dict[str, Any]:
    _validate_plan(plan)
    timestamp = _parse_time(created_at, label="checkpoint creation time")
    states = []
    for batch in plan["batches"]:
        for item in batch["items"]:
            states.append(
                {
                    "item_key": item["item_key"],
                    "batch_id": batch["batch_id"],
                    "status": "pending",
                    "attempts": 0,
                    "failure_code": None,
                    "retry_at": None,
                    "updated_at": timestamp,
                }
            )
    checkpoint = {
        "schema": "knowledge-engine-batch-checkpoint/v1",
        "plan_sha256": plan["plan_sha256"],
        "identity": plan["identity"],
        "revision": 0,
        "states": states,
    }
    checkpoint["resume_cursor"] = _resume_cursor(checkpoint)
    checkpoint["checkpoint_sha256"] = _digest(checkpoint)
    return checkpoint


def _validate_plan(plan: dict[str, Any]) -> None:
    valid_schema = plan.get("schema") == "knowledge-engine-resumable-batch/v1"
    if not isinstance(plan, dict) or not valid_schema:
        raise IntegrityError("M21-BATCH-116 invalid batch plan schema")
    claimed = plan.get("plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if not isinstance(claimed, str) or _digest(unsigned) != claimed:
        raise IntegrityError("M21-BATCH-117 batch plan digest mismatch")
    if plan.get("authority") != "evidence_only" or plan.get("production_authority") is not False:
        raise IntegrityError("M21-BATCH-118 batch plan authority drift")


def _validate_checkpoint(plan: dict[str, Any], checkpoint: dict[str, Any]) -> None:
    _validate_plan(plan)
    valid_schema = checkpoint.get("schema") == "knowledge-engine-batch-checkpoint/v1"
    if not isinstance(checkpoint, dict) or not valid_schema:
        raise IntegrityError("M21-BATCH-119 invalid checkpoint schema")
    claimed = checkpoint.get("checkpoint_sha256")
    unsigned = dict(checkpoint)
    unsigned.pop("checkpoint_sha256", None)
    if not isinstance(claimed, str) or _digest(unsigned) != claimed:
        raise IntegrityError("M21-BATCH-120 checkpoint digest mismatch")
    plan_drift = checkpoint.get("plan_sha256") != plan["plan_sha256"]
    identity_drift = checkpoint.get("identity") != plan["identity"]
    if plan_drift or identity_drift:
        raise IntegrityError("M21-BATCH-121 checkpoint identity mismatch")
    expected = {
        item["item_key"]: batch["batch_id"]
        for batch in plan["batches"]
        for item in batch["items"]
    }
    states = checkpoint.get("states")
    if not isinstance(states, list) or len(states) != len(expected):
        raise IntegrityError("M21-BATCH-122 checkpoint state coverage mismatch")
    observed: dict[str, str] = {}
    for state in states:
        key = state.get("item_key")
        if key in observed or key not in expected or state.get("batch_id") != expected.get(key):
            raise IntegrityError("M21-BATCH-123 invalid checkpoint item state")
        if state.get("status") not in ALL_STATES:
            raise IntegrityError("M21-BATCH-124 invalid checkpoint status")
        attempts = state.get("attempts")
        valid_attempts = isinstance(attempts, int) and not isinstance(attempts, bool)
        if not valid_attempts or not 0 <= attempts <= MAX_ATTEMPTS:
            raise IntegrityError("M21-BATCH-125 invalid checkpoint attempts")
        _parse_time(state.get("updated_at"), label="checkpoint update time")
        observed[key] = state["batch_id"]
    if set(observed) != set(expected):
        raise IntegrityError("M21-BATCH-122 checkpoint state coverage mismatch")


def _resume_cursor(checkpoint: dict[str, Any]) -> dict[str, Any] | None:
    for index, state in enumerate(checkpoint["states"]):
        if state["status"] in ACTIONABLE_STATES:
            return {
                "state_index": index,
                "item_key": state["item_key"],
                "batch_id": state["batch_id"],
            }
    return None


def transition_checkpoint(
    plan: dict[str, Any],
    checkpoint: dict[str, Any],
    *,
    item_key: str,
    target_status: str,
    expected_revision: int,
    updated_at: str,
    failure_code: str | None = None,
    retry_at: str | None = None,
) -> dict[str, Any]:
    _validate_checkpoint(plan, checkpoint)
    if checkpoint.get("revision") != expected_revision:
        raise IntegrityError("M21-BATCH-126 stale checkpoint revision")
    timestamp = _parse_time(updated_at, label="checkpoint update time")
    if target_status not in ALL_STATES:
        raise IntegrityError("M21-BATCH-127 invalid target status")

    states = [dict(state) for state in checkpoint["states"]]
    matches = [state for state in states if state["item_key"] == item_key]
    if len(matches) != 1:
        raise IntegrityError("M21-BATCH-128 unknown item key")
    state = matches[0]
    current = state["status"]
    if current == target_status:
        return checkpoint
    if target_status not in ALLOWED_TRANSITIONS[current]:
        raise IntegrityError("M21-BATCH-129 invalid checkpoint transition")

    attempts = state["attempts"]
    if target_status == "running":
        attempts += 1
        if attempts > MAX_ATTEMPTS:
            raise IntegrityError("M21-BATCH-130 retry attempts exhausted")
    invalid_failure_code = (
        target_status in {"failed", "retryable"}
        and (
            not isinstance(failure_code, str)
            or not failure_code
            or len(failure_code) > 100
        )
    )
    if invalid_failure_code:
        raise IntegrityError("M21-BATCH-131 failure code required")
    if target_status == "retryable":
        if retry_at is None:
            raise IntegrityError("M21-BATCH-132 retry time required")
        retry_at = _parse_time(retry_at, label="retry time")
    else:
        retry_at = None
    state.update(
        {
            "status": target_status,
            "attempts": attempts,
            "failure_code": failure_code if target_status in {"failed", "retryable"} else None,
            "retry_at": retry_at,
            "updated_at": timestamp,
        }
    )

    updated = {
        "schema": checkpoint["schema"],
        "plan_sha256": checkpoint["plan_sha256"],
        "identity": checkpoint["identity"],
        "revision": expected_revision + 1,
        "states": states,
    }
    updated["resume_cursor"] = _resume_cursor(updated)
    updated["checkpoint_sha256"] = _digest(updated)
    return updated


__all__ = [
    "build_batch_plan",
    "build_initial_checkpoint",
    "transition_checkpoint",
]
