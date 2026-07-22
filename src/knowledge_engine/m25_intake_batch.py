from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m21_resumable_batch import (
    build_batch_plan as build_m21_batch_plan,
    build_initial_checkpoint as build_m21_initial_checkpoint,
    transition_checkpoint as transition_m21_checkpoint,
)
from .m25_intake_common import (
    ADAPTER_SCHEMA,
    ADMISSION_PLAN_SCHEMA,
    AUTHORITY_SCHEMA,
    BATCH_PLAN_SCHEMA,
    INVENTORY_SCHEMA,
    M25_1_ENTRY_BASELINE_SHA256,
    MAX_ATTEMPTS,
    MAX_BATCH_BYTES,
    MAX_BATCH_SOURCES,
    _artifact_ref,
    _digest,
    _parse_time,
    _pretty_bytes,
)
from .m25_intake_compat import _m21_inventory
from .m25_intake_inventory import _validate_inventory
from .m25_intake_registry import build_adapter_registry, build_authority_envelope
from .m25_intake_state import _checkpoint, _new_state
from .storage import sha256_bytes

def _pack_batches(
    eligible: list[dict[str, Any]],
    *,
    inventory_sha256: str,
    max_sources: int,
    max_bytes: int,
) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for item in eligible:
        would_overflow = current and (
            len(current) >= max_sources or current_bytes + item["declared_bytes"] > max_bytes
        )
        if would_overflow:
            batches.append(_batch_record(inventory_sha256, len(batches), current))
            current = []
            current_bytes = 0
        current.append(item)
        current_bytes += item["declared_bytes"]
    if current:
        batches.append(_batch_record(inventory_sha256, len(batches), current))
    return batches

def _batch_record(
    inventory_sha256: str,
    index: int,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    seed = {
        "inventory_sha256": inventory_sha256,
        "batch_index": index,
        "item_ids": [item["item_id"] for item in items],
        "m21_item_keys": [item["m21_item_key"] for item in items],
    }
    return {
        "batch_index": index,
        "batch_id": "m25batch_" + _digest(seed),
        "item_ids": seed["item_ids"],
        "m21_item_keys": seed["m21_item_keys"],
        "source_count": len(items),
        "total_declared_bytes": sum(item["declared_bytes"] for item in items),
    }

def build_plan_bundle(
    inventory: Mapping[str, Any],
    *,
    max_sources_per_batch: int = 25,
    max_bytes_per_batch: int = 200_000,
    max_attempts: int = MAX_ATTEMPTS,
    created_at: str,
) -> dict[str, Any]:
    inventory_sha = _validate_inventory(inventory)
    timestamp = _parse_time(created_at, "checkpoint creation time")
    if not 1 <= max_sources_per_batch <= MAX_BATCH_SOURCES:
        raise IntegrityError("M25-INTAKE-124 invalid max sources per batch")
    if not 1 <= max_bytes_per_batch <= MAX_BATCH_BYTES:
        raise IntegrityError("M25-INTAKE-125 invalid max bytes per batch")
    if not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise IntegrityError("M25-INTAKE-126 invalid max attempts")

    registry = build_adapter_registry()
    authority = build_authority_envelope()
    adapter_by_id = {item["adapter_id"]: item for item in registry["adapters"]}
    m21_inventory = _m21_inventory(inventory)
    m21_plan = build_m21_batch_plan(m21_inventory, batch_size=1)
    m21_items = [batch["items"][0] for batch in m21_plan["batches"]]
    m21_by_locator = {
        (item["locator"], item["content_sha256"], item["source_kind"]): item
        for item in m21_items
    }

    executable: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in inventory["items"]:
        m21_item = m21_by_locator[
            (item["locator"], item["expected_content_sha256"], item["adapter_id"])
        ]
        enriched = {
            "item_id": item["item_id"],
            "m21_item_key": m21_item["item_key"],
            "declared_bytes": item["declared_bytes"],
            "adapter_id": item["adapter_id"],
        }
        reason_code = None
        if item["policy_gate"]["status"] != "resolved":
            reason_code = item["policy_gate"]["reason_code"]
        elif item["adapter_id"] not in adapter_by_id:
            reason_code = "ADAPTER_NOT_APPROVED"
        elif item["declared_bytes"] > max_bytes_per_batch:
            reason_code = "SOURCE_EXCEEDS_BATCH_BYTES"
        if reason_code is None:
            executable.append(enriched)
        else:
            blocked.append({**enriched, "reason_code": reason_code})

    executable.sort(key=lambda item: item["item_id"])
    blocked.sort(key=lambda item: item["item_id"])
    batches = _pack_batches(
        executable,
        inventory_sha256=inventory_sha,
        max_sources=max_sources_per_batch,
        max_bytes=max_bytes_per_batch,
    )
    adapter_payloads = {
        item["adapter_id"]: _pretty_bytes(item) for item in registry["adapters"]
    }
    adapter_refs = [
        _artifact_ref(
            ADAPTER_SCHEMA,
            f"admission/v1/adapters/{adapter_id}/{sha256_bytes(payload)}.json",
            payload,
        )
        for adapter_id, payload in sorted(adapter_payloads.items())
    ]
    authority_payload = _pretty_bytes(authority)
    authority_key = f"admission/v1/authority/{authority['authority_id']}.json"
    inventory_key = f"admission/v1/inventories/{inventory['inventory_id']}.json"
    inventory_payload = _pretty_bytes(dict(inventory))
    admission_body = {
        "schema_version": ADMISSION_PLAN_SCHEMA,
        "entry_baseline_ref": {
            "schema_version": "knowledge-engine-m25-1-entry-baseline/v1",
            "object_key": "pilot/m25/m25-1-entry-baseline.json",
            "sha256": M25_1_ENTRY_BASELINE_SHA256,
        },
        "inventory_ref": _artifact_ref(INVENTORY_SCHEMA, inventory_key, inventory_payload),
        "adapter_envelopes": adapter_refs,
        "batch_policy": {
            "max_sources_per_batch": max_sources_per_batch,
            "max_bytes_per_batch": max_bytes_per_batch,
            "max_attempts": max_attempts,
            "checkpoint_required": True,
        },
        "authority_envelope": _artifact_ref(AUTHORITY_SCHEMA, authority_key, authority_payload),
    }
    plan_identity = _digest(admission_body)
    admission_plan = {**admission_body, "plan_id": "m25plan_" + plan_identity}
    admission_plan["plan_sha256"] = _digest(admission_plan)

    batch_plan = {
        "schema_version": BATCH_PLAN_SCHEMA,
        "plan_id": admission_plan["plan_id"],
        "admission_plan_sha256": admission_plan["plan_sha256"],
        "inventory_id": inventory["inventory_id"],
        "inventory_sha256": inventory_sha,
        "m21_compatibility_plan_sha256": m21_plan["plan_sha256"],
        "population": {
            "inventory_source_count": inventory["source_count"],
            "inventory_total_declared_bytes": inventory["total_declared_bytes"],
            "executable_source_count": len(executable),
            "blocked_source_count": len(blocked),
            "planned_batch_count": len(batches),
            "coverage_complete": len(executable) + len(blocked) == inventory["source_count"],
        },
        "batch_policy": admission_plan["batch_policy"],
        "batches": batches,
        "blocked_items": blocked,
    }
    batch_plan["batch_plan_sha256"] = _digest(batch_plan)

    m21_checkpoint = build_m21_initial_checkpoint(m21_plan, created_at=timestamp)
    m21_key_by_item = {
        item["item_id"]: item["m21_item_key"] for item in executable + blocked
    }
    for blocked_item in blocked:
        m21_checkpoint = transition_m21_checkpoint(
            m21_plan,
            m21_checkpoint,
            item_key=blocked_item["m21_item_key"],
            target_status="skipped",
            expected_revision=m21_checkpoint["revision"],
            updated_at=timestamp,
        )

    blocked_by_id = {item["item_id"]: item for item in blocked}
    states = []
    for item in inventory["items"]:
        reason = blocked_by_id.get(item["item_id"])
        state = _new_state(
            admission_plan["plan_id"],
            item["item_id"],
            "blocked" if reason else "planned",
            timestamp,
            evidence_refs=(
                [
                    f"reason:{reason['reason_code']}",
                    f"m21:{m21_key_by_item[item['item_id']]}",
                ]
                if reason
                else [f"m21:{m21_key_by_item[item['item_id']]}"]
            ),
        )
        states.append(state)
    checkpoint = _checkpoint(
        admission_plan,
        batch_plan,
        inventory,
        states,
        m21_plan,
        m21_checkpoint,
        revision=0,
        updated_at=timestamp,
    )
    return {
        "inventory": dict(inventory),
        "adapter_registry": registry,
        "adapter_payloads": adapter_payloads,
        "authority_envelope": authority,
        "admission_plan": admission_plan,
        "batch_plan": batch_plan,
        "m21_compatibility_plan": m21_plan,
        "checkpoint": checkpoint,
    }

