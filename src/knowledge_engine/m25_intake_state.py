from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError
from .m21_resumable_batch import transition_checkpoint as transition_m21_checkpoint
from .m25_intake_common import (
    ACTIONABLE_STATES,
    ADMISSION_STATE_SCHEMA,
    CHECKPOINT_SCHEMA,
    M25_2_TRANSITIONS,
    _digest,
    _parse_time,
    _signed,
)
from .m25_intake_compat import (
    _m21_inventory_item_key,
    _m21_plan_from_checkpoint,
    _validate_plan_bundle,
)

def _new_state(
    plan_id: str,
    item_id: str,
    state: str,
    updated_at: str,
    *,
    attempts: int = 0,
    revision: int = 0,
    evidence_refs: Sequence[str] = (),
) -> dict[str, Any]:
    body = {
        "schema_version": ADMISSION_STATE_SCHEMA,
        "plan_id": plan_id,
        "item_id": item_id,
        "revision": revision,
        "state": state,
        "attempts": attempts,
        "evidence_refs": sorted(set(evidence_refs)),
        "decision_ref": None,
        "updated_at": updated_at,
    }
    body["state_sha256"] = _digest(body)
    return body

def _state_counts(states: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {state: 0 for state in sorted(M25_2_TRANSITIONS)}
    for state in states:
        name = state.get("state")
        if name in counts:
            counts[name] += 1
    return counts

def _resume_cursor(states: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    for index, state in enumerate(states):
        if state.get("state") in ACTIONABLE_STATES:
            return {
                "state_index": index,
                "item_id": state["item_id"],
                "state": state["state"],
            }
    return None

def _checkpoint(
    admission_plan: Mapping[str, Any],
    batch_plan: Mapping[str, Any],
    inventory: Mapping[str, Any],
    states: Sequence[Mapping[str, Any]],
    m21_plan: Mapping[str, Any],
    m21_checkpoint: Mapping[str, Any],
    *,
    revision: int,
    updated_at: str,
) -> dict[str, Any]:
    counts = _state_counts(states)
    checkpoint = {
        "schema_version": CHECKPOINT_SCHEMA,
        "plan_id": admission_plan["plan_id"],
        "plan_sha256": admission_plan["plan_sha256"],
        "batch_plan_sha256": batch_plan["batch_plan_sha256"],
        "inventory_sha256": inventory["inventory_sha256"],
        "revision": revision,
        "updated_at": updated_at,
        "states": list(states),
        "state_counts": counts,
        "resume_cursor": _resume_cursor(states),
        "m21_plan_sha256": m21_plan["plan_sha256"],
        "m21_checkpoint": dict(m21_checkpoint),
        "population_complete": sum(counts.values()) == inventory["source_count"],
    }
    checkpoint["checkpoint_sha256"] = _digest(checkpoint)
    return checkpoint

def _m21_target(current: str, target: str) -> str | None:
    if target == "acquiring":
        return "running"
    if target == "normalized":
        return "completed"
    if target == "retryable":
        return "retryable"
    if target in {"blocked", "rejected"}:
        return "skipped" if current == "planned" else "failed"
    return None

def transition_item_state(
    admission_plan: Mapping[str, Any],
    batch_plan: Mapping[str, Any],
    inventory: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    *,
    item_id: str,
    target_state: str,
    expected_revision: int,
    updated_at: str,
    evidence_refs: Sequence[str] = (),
    failure_code: str | None = None,
    retry_at: str | None = None,
) -> dict[str, Any]:
    _validate_plan_bundle(admission_plan, batch_plan, inventory, checkpoint)
    if checkpoint.get("revision") != expected_revision:
        raise IntegrityError("M25-INTAKE-136 stale checkpoint revision")
    timestamp = _parse_time(updated_at, "state update time")
    states = [dict(state) for state in checkpoint["states"]]
    matches = [state for state in states if state["item_id"] == item_id]
    if len(matches) != 1:
        raise IntegrityError("M25-INTAKE-137 unknown item id")
    state = matches[0]
    current = state["state"]
    if target_state == current:
        return dict(checkpoint)
    if target_state not in M25_2_TRANSITIONS.get(current, set()):
        raise IntegrityError("M25-INTAKE-138 invalid M25.2 transition")
    attempts = state["attempts"] + (1 if target_state == "acquiring" else 0)
    if attempts > admission_plan["batch_policy"]["max_attempts"]:
        raise IntegrityError("M25-INTAKE-139 retry attempts exhausted")
    if target_state in {"retryable", "blocked", "rejected"} and not failure_code:
        raise IntegrityError("M25-INTAKE-140 failure code required")

    item_lookup = {item["item_id"]: item for item in inventory["items"]}
    item = item_lookup[item_id]
    m21_plan = _m21_plan_from_checkpoint(admission_plan, inventory, checkpoint)
    m21_item_key = _m21_inventory_item_key(item, m21_plan)
    m21_checkpoint = dict(checkpoint["m21_checkpoint"])
    m21_target = _m21_target(current, target_state)
    if m21_target is not None:
        kwargs: dict[str, Any] = {}
        if m21_target in {"retryable", "failed"}:
            kwargs["failure_code"] = failure_code
        if m21_target == "retryable":
            kwargs["retry_at"] = retry_at or timestamp
        m21_checkpoint = transition_m21_checkpoint(
            m21_plan,
            m21_checkpoint,
            item_key=m21_item_key,
            target_status=m21_target,
            expected_revision=m21_checkpoint["revision"],
            updated_at=timestamp,
            **kwargs,
        )

    reason_refs = [f"reason:{failure_code}"] if failure_code is not None else []
    combined_evidence = sorted(
        {*state["evidence_refs"], *evidence_refs, *reason_refs}
    )
    updated_state = _new_state(
        admission_plan["plan_id"],
        item_id,
        target_state,
        timestamp,
        attempts=attempts,
        revision=state["revision"] + 1,
        evidence_refs=combined_evidence,
    )
    states[states.index(state)] = updated_state
    return _checkpoint(
        admission_plan,
        batch_plan,
        inventory,
        states,
        m21_plan,
        m21_checkpoint,
        revision=expected_revision + 1,
        updated_at=timestamp,
    )

