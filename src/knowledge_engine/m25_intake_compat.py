from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m21_resumable_batch import build_batch_plan as build_m21_batch_plan
from .m25_intake_common import (
    ADMISSION_PLAN_SCHEMA,
    BATCH_PLAN_SCHEMA,
    CHECKPOINT_SCHEMA,
    FOUNDATION_SHA,
    M25_2_ENGINE_BASE_SHA,
    SOURCE_SHA,
    _digest,
    _pretty_bytes,
    _signed,
)
from .m25_intake_inventory import _validate_inventory
from .storage import sha256_bytes


def _m21_inventory(inventory: Mapping[str, Any]) -> dict[str, Any]:
    items = []
    for item in inventory["items"]:
        items.append(
            {
                "canonical_url": item["original_uri"],
                "language": "und",
                "slug": item["item_id"],
                "series": None,
                "part": None,
                "published_at": None,
                "modified_at": None,
                "content_sha256": item["expected_content_sha256"],
                "source_kind": item["adapter_id"],
                "locator": item["locator"],
                "redirects": [],
                "translated_counterpart": None,
                "access_status": "available",
                "intake_status": "pending",
                "ownership_basis": "evidence-bound",
                "audience": item["audience"],
            }
        )
    snapshot = {
        "schema": "knowledge-engine-blog-inventory/v1",
        "authority": "evidence_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "identity": {
            "engine_sha": M25_2_ENGINE_BASE_SHA,
            "source_sha": SOURCE_SHA,
            "foundation_sha": FOUNDATION_SHA,
            "captured_at": inventory["captured_at"],
        },
        "allowed_hosts": [],
        "item_count": len(items),
        "items": items,
    }
    snapshot["snapshot_sha256"] = _digest(snapshot)
    return snapshot

def _validate_plan_bundle(
    admission_plan: Mapping[str, Any],
    batch_plan: Mapping[str, Any],
    inventory: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> None:
    inventory_sha = _validate_inventory(inventory)
    if admission_plan.get("schema_version") != ADMISSION_PLAN_SCHEMA:
        raise IntegrityError("M25-INTAKE-127 invalid admission plan schema")
    plan_sha = _signed(
        admission_plan, "plan_sha256", "M25-INTAKE-128 admission plan digest mismatch"
    )
    if batch_plan.get("schema_version") != BATCH_PLAN_SCHEMA:
        raise IntegrityError("M25-INTAKE-129 invalid batch plan schema")
    batch_sha = _signed(
        batch_plan, "batch_plan_sha256", "M25-INTAKE-130 batch plan digest mismatch"
    )
    if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA:
        raise IntegrityError("M25-INTAKE-131 invalid checkpoint schema")
    _signed(checkpoint, "checkpoint_sha256", "M25-INTAKE-132 checkpoint digest mismatch")
    if (
        admission_plan.get("inventory_ref", {}).get("sha256")
        != sha256_bytes(_pretty_bytes(dict(inventory)))
        or batch_plan.get("inventory_sha256") != inventory_sha
        or batch_plan.get("admission_plan_sha256") != plan_sha
        or checkpoint.get("plan_sha256") != plan_sha
        or checkpoint.get("batch_plan_sha256") != batch_sha
        or checkpoint.get("inventory_sha256") != inventory_sha
    ):
        raise IntegrityError("M25-INTAKE-133 cross-artifact binding mismatch")
    states = checkpoint.get("states")
    if not isinstance(states, list) or len(states) != inventory["source_count"]:
        raise IntegrityError("M25-INTAKE-134 checkpoint population mismatch")
    if {state.get("item_id") for state in states} != {
        item.get("item_id") for item in inventory["items"]
    }:
        raise IntegrityError("M25-INTAKE-135 checkpoint item coverage mismatch")
    for state in states:
        if not isinstance(state, Mapping):
            raise IntegrityError("M25-INTAKE-135 checkpoint state must be an object")
        _signed(state, "state_sha256", "M25-INTAKE-135 state digest mismatch")

def _m21_plan_from_checkpoint(
    admission_plan: Mapping[str, Any],
    inventory: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    plan = build_m21_batch_plan(_m21_inventory(inventory), batch_size=1)
    if (
        plan["plan_sha256"] != checkpoint.get("m21_plan_sha256")
        or admission_plan["plan_id"] != checkpoint.get("plan_id")
    ):
        raise IntegrityError("M25-INTAKE-141 M21 compatibility plan drift")
    return plan

def _m21_inventory_item_key(
    item: Mapping[str, Any],
    m21_plan: Mapping[str, Any],
) -> str:
    matches = [
        planned
        for batch in m21_plan["batches"]
        for planned in batch["items"]
        if planned["locator"] == item["locator"]
        and planned["content_sha256"] == item["expected_content_sha256"]
        and planned["source_kind"] == item["adapter_id"]
    ]
    if len(matches) != 1:
        raise IntegrityError("M25-INTAKE-142 M21 item key missing or ambiguous")
    return matches[0]["item_key"]

