from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m25_extraction_common import (
    MAX_INPUT_TEXT_CHARS,
    MAX_INPUTS,
    ExtractionInput,
    _digest,
    _hex,
    _prompt_findings,
    _secret_findings,
    _signed,
)
from .m25_intake_common import NORMALIZED_OUTPUT_SCHEMA
from .m25_intake_persistence import load_plan_bundle
from .storage import ObjectStore, sha256_bytes


def _load_json(store: ObjectStore, key: str, code: str) -> dict[str, Any]:
    try:
        value = json.loads(store.get(key))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IntegrityError(code) from exc
    if not isinstance(value, dict):
        raise IntegrityError(code)
    return value


def _normalized_output_key(plan_id: str, item_id: str, state: Mapping[str, Any]) -> str:
    prefix = f"admission/v1/normalized/{plan_id}/{item_id}/"
    matches = [
        value
        for value in state.get("evidence_refs", [])
        if isinstance(value, str) and value.startswith(prefix) and value.endswith(".json")
    ]
    if len(matches) != 1:
        raise IntegrityError("M25-EXTRACT-106 normalized output reference missing or ambiguous")
    return matches[0]


def _validate_output(
    output: Mapping[str, Any],
    *,
    plan_id: str,
    item_id: str,
) -> None:
    if output.get("schema_version") != NORMALIZED_OUTPUT_SCHEMA:
        raise IntegrityError("M25-EXTRACT-107 invalid normalized output schema")
    _signed(output, "output_sha256", "M25-EXTRACT-108 normalized output digest mismatch")
    if output.get("plan_id") != plan_id or output.get("item_id") != item_id:
        raise IntegrityError("M25-EXTRACT-109 normalized output identity mismatch")
    if (
        output.get("authority") != "candidate_only"
        or output.get("canonical_knowledge") is not False
        or output.get("production_authority") is not False
        or output.get("source_mutation_permitted") is not False
    ):
        raise IntegrityError("M25-EXTRACT-110 normalized output authority drift")


def _m21_planned_items(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for batch in plan.get("batches", []):
        if not isinstance(batch, Mapping) or not isinstance(batch.get("items"), list):
            raise IntegrityError("M25-EXTRACT-111 malformed M21 compatibility plan")
        batch_id = _hex(batch.get("batch_id"), 64, "M21 batch id")
        for value in batch["items"]:
            if not isinstance(value, Mapping):
                raise IntegrityError("M25-EXTRACT-111 malformed M21 compatibility item")
            locator = value.get("locator")
            content_sha = value.get("content_sha256")
            source_kind = value.get("source_kind")
            key = _hex(value.get("item_key"), 64, "M21 item key")
            identity = f"{locator}\0{content_sha}\0{source_kind}"
            if identity in items:
                raise IntegrityError("M25-EXTRACT-112 ambiguous M21 compatibility item")
            items[identity] = {**value, "item_key": key, "batch_id": batch_id}
    return items


def load_ready_extraction_inputs(store: ObjectStore, plan_id: str) -> dict[str, Any]:
    bundle = load_plan_bundle(store, plan_id)
    inventory = bundle["inventory"]
    checkpoint = bundle["checkpoint"]
    m21_plan = bundle["m21_compatibility_plan"]
    m21_checkpoint = checkpoint.get("m21_checkpoint")
    if not isinstance(m21_checkpoint, dict):
        raise IntegrityError("M25-EXTRACT-113 M21 compatibility checkpoint missing")
    states = checkpoint.get("states")
    if not isinstance(states, list) or len(states) != inventory.get("source_count"):
        raise IntegrityError("M25-EXTRACT-114 M25.2 checkpoint population mismatch")
    state_by_id = {state.get("item_id"): state for state in states if isinstance(state, Mapping)}
    if len(state_by_id) != len(states):
        raise IntegrityError("M25-EXTRACT-114 M25.2 checkpoint item duplication")
    state_names = {state.get("state") for state in states if isinstance(state, Mapping)}
    if "rejected" in state_names or state_names - {"normalized", "blocked"}:
        raise IntegrityError("M25-EXTRACT-115 M25.2 plan is not ready for extraction")

    planned = _m21_planned_items(m21_plan)
    inputs: list[ExtractionInput] = []
    safe_refs: list[dict[str, Any]] = []
    derivatives: list[dict[str, Any]] = []
    for item in inventory.get("items", []):
        if not isinstance(item, Mapping):
            raise IntegrityError("M25-EXTRACT-116 malformed M25.2 inventory item")
        item_id = item.get("item_id")
        state = state_by_id.get(item_id)
        if not isinstance(item_id, str) or state is None:
            raise IntegrityError("M25-EXTRACT-116 M25.2 inventory binding mismatch")
        if state.get("state") == "blocked":
            continue
        output_key = _normalized_output_key(plan_id, item_id, state)
        output = _load_json(store, output_key, "M25-EXTRACT-117 cannot load normalized output")
        _validate_output(output, plan_id=plan_id, item_id=item_id)
        normalized_ref = output.get("normalized_ref")
        derivative_ref = output.get("derivative_ref")
        if not isinstance(normalized_ref, Mapping) or not isinstance(derivative_ref, Mapping):
            raise IntegrityError("M25-EXTRACT-118 normalized output references missing")
        normalized_key = normalized_ref.get("object_key")
        if not isinstance(normalized_key, str):
            raise IntegrityError("M25-EXTRACT-118 normalized object key missing")
        normalized_bytes = store.get(normalized_key)
        normalized_sha = sha256_bytes(normalized_bytes)
        if normalized_sha != normalized_ref.get("sha256"):
            raise IntegrityError("M25-EXTRACT-119 normalized source digest mismatch")
        try:
            text = normalized_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IntegrityError("M25-EXTRACT-120 normalized source is not UTF-8") from exc
        if not text or len(text) > MAX_INPUT_TEXT_CHARS:
            raise IntegrityError("M25-EXTRACT-121 normalized source exceeds extraction bounds")
        secret_findings = _secret_findings(text)
        if secret_findings:
            raise IntegrityError("M25-EXTRACT-122 secret-like normalized source blocked")
        derivative_key = derivative_ref.get("object_key")
        if not isinstance(derivative_key, str):
            raise IntegrityError("M25-EXTRACT-123 derivative object key missing")
        derivative_bytes = store.get(derivative_key)
        if sha256_bytes(derivative_bytes) != derivative_ref.get("sha256"):
            raise IntegrityError("M25-EXTRACT-124 derivative metadata digest mismatch")
        derivative = _load_json(store, derivative_key, "M25-EXTRACT-125 cannot load derivative")
        derivative_id = derivative_ref.get("derivative_id")
        if derivative.get("derivative_id") != derivative_id:
            raise IntegrityError("M25-EXTRACT-126 derivative identity mismatch")
        warnings = sorted(
            {
                *[str(value) for value in derivative.get("warnings", []) if isinstance(value, str)],
                *_prompt_findings(text),
            }
        )
        identity = (
            f"{item.get('locator')}\0{item.get('expected_content_sha256')}\0"
            f"{item.get('adapter_id')}"
        )
        planned_item = planned.get(identity)
        if planned_item is None:
            raise IntegrityError("M25-EXTRACT-127 M21 compatibility item missing")
        audience = item.get("audience")
        m21_audience = "restricted" if audience == "confidential" else audience
        if m21_audience not in {"public", "internal", "restricted"}:
            raise IntegrityError("M25-EXTRACT-128 unsupported extraction audience")
        text_sha = sha256_bytes(normalized_bytes)
        inputs.append(
            ExtractionInput(
                item_id=item_id,
                derivative_id=str(derivative_id),
                audience=str(audience),
                text=text,
                text_sha256=text_sha,
                normalized_key=normalized_key,
                warnings=tuple(warnings),
            )
        )
        safe_refs.append(
            {
                "item_id": item_id,
                "derivative_id": derivative_id,
                "audience": audience,
                "normalized_ref": dict(normalized_ref),
                "snapshot_ref": dict(output["snapshot_ref"]),
                "source_warning_codes": warnings,
            }
        )
        derivatives.append(
            {
                "schema": "knowledge-engine-normalized-derivative/v1",
                "derivative_id": derivative_id,
                "item_key": planned_item["item_key"],
                "batch_id": planned_item["batch_id"],
                "audience": m21_audience,
                "source_content_sha256": item["expected_content_sha256"],
                "normalized": True,
                "language": "und",
                "text": text,
                "text_sha256": text_sha,
            }
        )
    if not 1 <= len(inputs) <= MAX_INPUTS:
        raise IntegrityError("M25-EXTRACT-129 extraction input count exceeds bounds")
    input_manifest = {
        "schema_version": "knowledge-engine-m25-extraction-input-manifest/v1",
        "plan_id": plan_id,
        "m25_2_plan_sha256": bundle["admission_plan"]["plan_sha256"],
        "m25_2_checkpoint_sha256": checkpoint["checkpoint_sha256"],
        "m21_plan_sha256": m21_plan["plan_sha256"],
        "m21_checkpoint_sha256": m21_checkpoint["checkpoint_sha256"],
        "input_count": len(safe_refs),
        "inputs": sorted(safe_refs, key=lambda value: value["item_id"]),
    }
    input_manifest["input_manifest_sha256"] = _digest(input_manifest)
    return {
        "bundle": bundle,
        "inputs": sorted(inputs, key=lambda value: value.item_id),
        "derivatives": sorted(derivatives, key=lambda value: value["derivative_id"]),
        "input_manifest": input_manifest,
    }


__all__ = ["load_ready_extraction_inputs"]
