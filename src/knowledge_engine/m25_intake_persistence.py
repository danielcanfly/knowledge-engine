from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError, ReleaseConflictError
from .m25_intake_common import _pretty_bytes, _put_immutable, _signed
from .m25_intake_compat import _validate_plan_bundle
from .storage import ObjectStore, sha256_bytes


def persist_plan_bundle(store: ObjectStore, bundle: Mapping[str, Any]) -> dict[str, Any]:
    inventory = bundle["inventory"]
    registry = bundle["adapter_registry"]
    authority = bundle["authority_envelope"]
    plan = bundle["admission_plan"]
    batch_plan = bundle["batch_plan"]
    m21_plan = bundle["m21_compatibility_plan"]
    checkpoint = bundle["checkpoint"]

    written: dict[str, str] = {}
    for adapter in registry["adapters"]:
        payload = _pretty_bytes(adapter)
        key = f"admission/v1/adapters/{adapter['adapter_id']}/{sha256_bytes(payload)}.json"
        _put_immutable(store, key, payload)
        written[adapter["adapter_id"]] = key
    authority_payload = _pretty_bytes(authority)
    authority_key = f"admission/v1/authority/{authority['authority_id']}.json"
    _put_immutable(store, authority_key, authority_payload)
    inventory_payload = _pretty_bytes(inventory)
    inventory_key = f"admission/v1/inventories/{inventory['inventory_id']}.json"
    _put_immutable(store, inventory_key, inventory_payload)
    plan_key = f"admission/v1/plans/{plan['plan_id']}/plan.json"
    _put_immutable(store, plan_key, _pretty_bytes(plan))
    batch_key = f"admission/v1/plans/{plan['plan_id']}/batch-plan.json"
    _put_immutable(store, batch_key, _pretty_bytes(batch_plan))
    m21_key = f"admission/v1/plans/{plan['plan_id']}/m21-compatibility-plan.json"
    _put_immutable(store, m21_key, _pretty_bytes(m21_plan))
    checkpoint_key = persist_checkpoint(store, checkpoint)
    return {
        "plan_id": plan["plan_id"],
        "inventory_key": inventory_key,
        "plan_key": plan_key,
        "batch_plan_key": batch_key,
        "m21_plan_key": m21_key,
        "checkpoint_key": checkpoint_key,
        "authority_key": authority_key,
        "adapter_keys": written,
    }

def persist_checkpoint(store: ObjectStore, checkpoint: Mapping[str, Any]) -> str:
    _signed(checkpoint, "checkpoint_sha256", "M25-INTAKE-132 checkpoint digest mismatch")
    payload = _pretty_bytes(dict(checkpoint))
    key = (
        f"admission/v1/checkpoints/{checkpoint['plan_id']}/"
        f"{checkpoint['revision']:06d}-{checkpoint['checkpoint_sha256']}.json"
    )
    head_key = f"admission/v1/checkpoints/{checkpoint['plan_id']}/HEAD.json"
    head = {
        "schema_version": "knowledge-engine-m25-checkpoint-head/v1",
        "plan_id": checkpoint["plan_id"],
        "revision": checkpoint["revision"],
        "checkpoint_key": key,
        "checkpoint_sha256": checkpoint["checkpoint_sha256"],
    }
    head_payload = _pretty_bytes(head)
    current = store.head(head_key)
    if current is not None:
        current_head = json.loads(store.get(head_key))
        if current_head.get("revision") > checkpoint["revision"]:
            raise IntegrityError("M25-INTAKE-143 checkpoint head moved forward")
        if current_head.get("revision") == checkpoint["revision"]:
            if current_head != head:
                raise IntegrityError("M25-INTAKE-144 checkpoint revision collision")
            _put_immutable(store, key, payload)
            return key

    _put_immutable(store, key, payload)
    if current is None:
        try:
            store.put(
                head_key,
                head_payload,
                content_type="application/json",
                sha256=sha256_bytes(head_payload),
                only_if_absent=True,
            )
            return key
        except ReleaseConflictError as exc:
            current = store.head(head_key)
            if current is None:
                raise IntegrityError("M25-INTAKE-143 checkpoint head disappeared") from exc
    store.put(
        head_key,
        head_payload,
        content_type="application/json",
        sha256=sha256_bytes(head_payload),
        expected_etag=current.etag,
    )
    return key

def load_plan_bundle(store: ObjectStore, plan_id: str) -> dict[str, Any]:
    plan_key = f"admission/v1/plans/{plan_id}/plan.json"
    batch_key = f"admission/v1/plans/{plan_id}/batch-plan.json"
    m21_key = f"admission/v1/plans/{plan_id}/m21-compatibility-plan.json"
    plan = json.loads(store.get(plan_key))
    inventory = json.loads(store.get(plan["inventory_ref"]["object_key"]))
    batch_plan = json.loads(store.get(batch_key))
    m21_plan = json.loads(store.get(m21_key))
    head_key = f"admission/v1/checkpoints/{plan_id}/HEAD.json"
    head = json.loads(store.get(head_key))
    checkpoint = json.loads(store.get(head["checkpoint_key"]))
    _validate_plan_bundle(plan, batch_plan, inventory, checkpoint)
    if m21_plan["plan_sha256"] != checkpoint["m21_plan_sha256"]:
        raise IntegrityError("M25-INTAKE-145 persisted M21 plan mismatch")
    return {
        "inventory": inventory,
        "admission_plan": plan,
        "batch_plan": batch_plan,
        "m21_compatibility_plan": m21_plan,
        "checkpoint": checkpoint,
    }

