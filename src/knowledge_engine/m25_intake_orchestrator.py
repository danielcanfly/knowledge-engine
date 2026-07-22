from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .m25_intake_adapters import _normalized_output, default_executors
from .m25_intake_batch import build_plan_bundle
from .m25_intake_common import (
    ACTIONABLE_STATES,
    APPROVED_ADAPTER_IDS,
    EXISTING_INTAKE_ADAPTER,
    LOCAL_MARKDOWN_ADAPTER,
    MAX_INVENTORY_ITEMS,
    REPORT_SCHEMA,
    TERMINAL_M25_2_STATES,
    AdapterExecutor,
    AdapterOutcome,
    _digest,
    _parse_time,
    _pretty_bytes,
    _put_immutable,
)
from .m25_intake_compat import (
    _m21_inventory_item_key,
    _m21_plan_from_checkpoint,
    _validate_plan_bundle,
)
from .m25_intake_inventory import build_source_inventory
from .m25_intake_persistence import (
    load_plan_bundle,
    persist_checkpoint,
    persist_plan_bundle,
)
from .m25_intake_registry import build_adapter_registry, build_authority_envelope
from .m25_intake_state import transition_item_state
from .storage import ObjectStore


def execute_next(
    store: ObjectStore,
    admission_plan: Mapping[str, Any],
    batch_plan: Mapping[str, Any],
    inventory: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    *,
    allowed_root: Path | None,
    run_at: str,
    executors: Mapping[str, AdapterExecutor] | None = None,
) -> dict[str, Any]:
    _validate_plan_bundle(admission_plan, batch_plan, inventory, checkpoint)
    cursor = checkpoint.get("resume_cursor")
    if cursor is None:
        return dict(checkpoint)
    timestamp = _parse_time(run_at, "orchestrator run time")
    item_id = cursor["item_id"]
    item = next(item for item in inventory["items"] if item["item_id"] == item_id)
    current_state = checkpoint["states"][cursor["state_index"]]
    if current_state["state"] == "retryable":
        m21_states = checkpoint["m21_checkpoint"]["states"]
        m21_key = _m21_inventory_item_key(
            item, _m21_plan_from_checkpoint(admission_plan, inventory, checkpoint)
        )
        m21_state = next(state for state in m21_states if state["item_key"] == m21_key)
        retry_at = m21_state.get("retry_at")
        if isinstance(retry_at, str) and retry_at > timestamp:
            return dict(checkpoint)
    if (
        current_state["state"] == "retryable"
        and current_state["attempts"] >= admission_plan["batch_policy"]["max_attempts"]
    ):
        exhausted = transition_item_state(
            admission_plan,
            batch_plan,
            inventory,
            checkpoint,
            item_id=item_id,
            target_state="blocked",
            expected_revision=checkpoint["revision"],
            updated_at=timestamp,
            evidence_refs=["reason:RETRY_ATTEMPTS_EXHAUSTED"],
            failure_code="RETRY_ATTEMPTS_EXHAUSTED",
        )
        persist_checkpoint(store, exhausted)
        return exhausted
    current = transition_item_state(
        admission_plan,
        batch_plan,
        inventory,
        checkpoint,
        item_id=item_id,
        target_state="acquiring",
        expected_revision=checkpoint["revision"],
        updated_at=timestamp,
        evidence_refs=[f"adapter:{item['adapter_id']}"],
    )
    persist_checkpoint(store, current)
    executor = (executors or default_executors()).get(item["adapter_id"])
    if executor is None:
        outcome = AdapterOutcome(status="blocked", failure_code="ADAPTER_EXECUTOR_MISSING")
    else:
        outcome = executor(store, item, allowed_root, timestamp)

    if outcome.status == "accepted":
        current = transition_item_state(
            admission_plan,
            batch_plan,
            inventory,
            current,
            item_id=item_id,
            target_state="snapshotted",
            expected_revision=current["revision"],
            updated_at=timestamp,
            evidence_refs=[
                value
                for value in [outcome.snapshot_key, outcome.raw_blob_key, *outcome.evidence_refs]
                if isinstance(value, str)
            ],
        )
        persist_checkpoint(store, current)
        output = _normalized_output(admission_plan, item, outcome)
        output_key = (
            f"admission/v1/normalized/{admission_plan['plan_id']}/{item_id}/"
            f"{output['output_sha256']}.json"
        )
        _put_immutable(store, output_key, _pretty_bytes(output))
        current = transition_item_state(
            admission_plan,
            batch_plan,
            inventory,
            current,
            item_id=item_id,
            target_state="normalized",
            expected_revision=current["revision"],
            updated_at=timestamp,
            evidence_refs=[
                output_key,
                outcome.derivative_key or "",
                outcome.normalized_key or "",
            ],
        )
    elif outcome.status == "retryable":
        current = transition_item_state(
            admission_plan,
            batch_plan,
            inventory,
            current,
            item_id=item_id,
            target_state="retryable",
            expected_revision=current["revision"],
            updated_at=timestamp,
            evidence_refs=outcome.evidence_refs,
            failure_code=outcome.failure_code or "RETRYABLE_ADAPTER_FAILURE",
            retry_at=outcome.retry_at or timestamp,
        )
    elif outcome.status in {"blocked", "rejected"}:
        current = transition_item_state(
            admission_plan,
            batch_plan,
            inventory,
            current,
            item_id=item_id,
            target_state=outcome.status,
            expected_revision=current["revision"],
            updated_at=timestamp,
            evidence_refs=outcome.evidence_refs,
            failure_code=outcome.failure_code or "ADAPTER_FAILURE",
        )
    else:
        raise IntegrityError("M25-INTAKE-147 unknown adapter outcome")
    persist_checkpoint(store, current)
    return current

def resume_orchestrator(
    store: ObjectStore,
    plan_id: str,
    *,
    allowed_root: Path | None,
    run_at: str,
    max_items: int = 100,
    executors: Mapping[str, AdapterExecutor] | None = None,
) -> dict[str, Any]:
    if not 1 <= max_items <= MAX_INVENTORY_ITEMS:
        raise IntegrityError("M25-INTAKE-148 invalid resume item cap")
    bundle = load_plan_bundle(store, plan_id)
    checkpoint = bundle["checkpoint"]
    processed = 0
    while checkpoint.get("resume_cursor") is not None and processed < max_items:
        previous_sha = checkpoint["checkpoint_sha256"]
        checkpoint = execute_next(
            store,
            bundle["admission_plan"],
            bundle["batch_plan"],
            bundle["inventory"],
            checkpoint,
            allowed_root=allowed_root,
            run_at=run_at,
            executors=executors,
        )
        processed += 1
        if checkpoint["checkpoint_sha256"] == previous_sha:
            break
    report = build_orchestrator_report(
        bundle["admission_plan"],
        bundle["batch_plan"],
        bundle["inventory"],
        checkpoint,
    )
    report_key = (
        f"admission/v1/reports/{plan_id}/{report['report_sha256']}.json"
    )
    _put_immutable(store, report_key, _pretty_bytes(report))
    return {"checkpoint": checkpoint, "report": report, "report_key": report_key}

def build_orchestrator_report(
    admission_plan: Mapping[str, Any],
    batch_plan: Mapping[str, Any],
    inventory: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_plan_bundle(admission_plan, batch_plan, inventory, checkpoint)
    counts = checkpoint["state_counts"]
    terminal_count = sum(counts.get(state, 0) for state in TERMINAL_M25_2_STATES)
    actionable_count = sum(counts.get(state, 0) for state in ACTIONABLE_STATES)
    in_flight_count = counts.get("acquiring", 0) + counts.get("snapshotted", 0)
    accounted_count = terminal_count + actionable_count + in_flight_count
    silent_exclusion_count = max(0, inventory["source_count"] - accounted_count)
    policy_blocked_ids = {
        item["item_id"]
        for item in inventory["items"]
        if item["policy_gate"]["status"] == "blocked"
    }
    state_by_id = {state["item_id"]: state["state"] for state in checkpoint["states"]}
    policy_fail_closed = all(
        state_by_id.get(item_id) == "blocked" for item_id in policy_blocked_ids
    )
    report = {
        "schema_version": REPORT_SCHEMA,
        "plan_id": admission_plan["plan_id"],
        "plan_sha256": admission_plan["plan_sha256"],
        "batch_plan_sha256": batch_plan["batch_plan_sha256"],
        "inventory_sha256": inventory["inventory_sha256"],
        "checkpoint_sha256": checkpoint["checkpoint_sha256"],
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "source_mutation_performed": False,
        "population": {
            "inventory_source_count": inventory["source_count"],
            "terminal_source_count": terminal_count,
            "actionable_source_count": actionable_count,
            "in_flight_source_count": in_flight_count,
            "accounted_source_count": accounted_count,
            "coverage_complete": accounted_count == inventory["source_count"],
        },
        "state_counts": counts,
        "batch_limits_respected": all(
            batch["source_count"] <= admission_plan["batch_policy"]["max_sources_per_batch"]
            and batch["total_declared_bytes"]
            <= admission_plan["batch_policy"]["max_bytes_per_batch"]
            for batch in batch_plan["batches"]
        ),
        "silent_exclusion_count": silent_exclusion_count,
        "unresolved_policy_fail_closed": policy_fail_closed,
        "retries_bounded": True,
        "ready_for_m25_3": (
            counts.get("normalized", 0) > 0
            and actionable_count == 0
            and in_flight_count == 0
            and terminal_count == inventory["source_count"]
            and counts.get("rejected", 0) == 0
            and silent_exclusion_count == 0
            and policy_fail_closed
        ),
    }
    report["report_sha256"] = _digest(report)
    return report

__all__ = [
    "AdapterOutcome",
    "APPROVED_ADAPTER_IDS",
    "EXISTING_INTAKE_ADAPTER",
    "LOCAL_MARKDOWN_ADAPTER",
    "build_adapter_registry",
    "build_authority_envelope",
    "build_orchestrator_report",
    "build_plan_bundle",
    "build_source_inventory",
    "default_executors",
    "execute_next",
    "load_plan_bundle",
    "persist_checkpoint",
    "persist_plan_bundle",
    "resume_orchestrator",
    "transition_item_state",
]
