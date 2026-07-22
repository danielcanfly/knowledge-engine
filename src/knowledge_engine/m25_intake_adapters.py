from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .intake_v1 import (
    IntakeFailure,
    LocalFileConnector,
    LocalMarkdownRequest,
    intake_local_markdown,
)
from .m25_intake_common import (
    EXISTING_INTAKE_ADAPTER,
    LOCAL_MARKDOWN_ADAPTER,
    MAX_DESCRIPTOR_BYTES,
    NORMALIZED_OUTPUT_SCHEMA,
    AdapterExecutor,
    AdapterOutcome,
    _digest,
    _parse_time,
)
from .m25_intake_inventory import _policy_objects
from .storage import ObjectStore, sha256_bytes

def _local_markdown_executor(
    store: ObjectStore,
    item: Mapping[str, Any],
    allowed_root: Path | None,
    run_at: str,
) -> AdapterOutcome:
    if allowed_root is None:
        return AdapterOutcome(status="blocked", failure_code="ALLOWED_ROOT_REQUIRED")
    connector = LocalFileConnector(allowed_root)
    acquisition_time = _parse_time(item.get("retrieved_at"), "item retrieval time")
    try:
        path = connector.canonicalize(item["locator"])
        acquisition = connector.acquire(
            path,
            retrieved_at=acquisition_time,
            max_bytes=MAX_DESCRIPTOR_BYTES,
        )
    except IntakeFailure as failure:
        return AdapterOutcome(
            status="retryable" if failure.transient else "rejected",
            failure_code=failure.code,
            retry_at=run_at if failure.transient else None,
        )
    observed_sha = sha256_bytes(acquisition.data)
    if len(acquisition.data) != item["declared_bytes"] or observed_sha != item[
        "expected_content_sha256"
    ]:
        return AdapterOutcome(status="blocked", failure_code="BYTE_IDENTITY_MISMATCH")
    owner, license_evidence, access = _policy_objects(item)
    result = intake_local_markdown(
        store=store,
        request=LocalMarkdownRequest(
            locator=item["locator"],
            original_uri=item["original_uri"],
            retrieved_at=acquisition_time,
            owner=owner,
            license=license_evidence,
            audience=item["audience"],
            access_policy=access,
            source_id=item.get("source_id"),
            max_bytes=item["declared_bytes"],
        ),
        allowed_root=allowed_root,
    )
    if result.status != "accepted_for_compilation":
        rejection = json.loads(store.get(result.rejection_key)) if result.rejection_key else {}
        failure_code = result.failure_code or "INTAKE_REJECTED"
        if failure_code in {"ACL_UNRESOLVED", "LICENSE_UNRESOLVED"}:
            status = "blocked"
        elif rejection.get("transient") is True:
            status = "retryable"
        else:
            status = "rejected"
        return AdapterOutcome(
            status=status,
            evidence_refs=tuple(result.event_keys),
            snapshot_id=result.snapshot_id,
            snapshot_key=result.snapshot_key,
            derivative_id=result.derivative_id,
            derivative_key=result.derivative_key,
            normalized_key=result.normalized_key,
            raw_blob_key=result.raw_blob_key,
            failure_code=failure_code,
            retry_at=run_at if status == "retryable" else None,
        )
    raw = store.head(result.raw_blob_key)
    snapshot = store.head(result.snapshot_key)
    derivative = store.head(result.derivative_key)
    normalized = store.head(result.normalized_key)
    if any(value is None for value in (raw, snapshot, derivative, normalized)):
        return AdapterOutcome(status="rejected", failure_code="INTAKE_ARTIFACT_MISSING")
    if raw.sha256 != item["expected_content_sha256"] or raw.bytes != item["declared_bytes"]:
        return AdapterOutcome(status="blocked", failure_code="BYTE_IDENTITY_MISMATCH")
    return AdapterOutcome(
        status="accepted",
        evidence_refs=tuple(result.event_keys),
        snapshot_id=result.snapshot_id,
        snapshot_key=result.snapshot_key,
        snapshot_sha256=snapshot.sha256,
        derivative_id=result.derivative_id,
        derivative_key=result.derivative_key,
        derivative_sha256=derivative.sha256,
        normalized_key=result.normalized_key,
        normalized_sha256=normalized.sha256,
        raw_blob_key=result.raw_blob_key,
        raw_sha256=raw.sha256,
        raw_bytes=raw.bytes,
    )

def _existing_intake_executor(
    store: ObjectStore,
    item: Mapping[str, Any],
    allowed_root: Path | None,
    run_at: str,
) -> AdapterOutcome:
    del allowed_root, run_at
    config = item.get("adapter_config")
    if not isinstance(config, Mapping):
        return AdapterOutcome(status="blocked", failure_code="EXISTING_REF_CONFIG_REQUIRED")
    required = {
        "result_key",
        "snapshot_key",
        "derivative_key",
        "normalized_key",
        "raw_blob_key",
    }
    if set(config) != required or any(not isinstance(config[key], str) for key in required):
        return AdapterOutcome(status="blocked", failure_code="EXISTING_REF_CONFIG_INVALID")
    metadata = {key: store.head(config[key]) for key in required}
    if any(value is None for value in metadata.values()):
        return AdapterOutcome(status="rejected", failure_code="EXISTING_REF_MISSING")
    result = json.loads(store.get(config["result_key"]))
    if result.get("status") != "accepted_for_compilation":
        return AdapterOutcome(status="rejected", failure_code="EXISTING_REF_NOT_ACCEPTED")
    expected_bindings = {
        "snapshot_key": config["snapshot_key"],
        "derivative_key": config["derivative_key"],
        "normalized_key": config["normalized_key"],
        "raw_blob_key": config["raw_blob_key"],
    }
    if any(result.get(field) != value for field, value in expected_bindings.items()):
        return AdapterOutcome(status="rejected", failure_code="EXISTING_REF_BINDING_MISMATCH")
    raw = metadata["raw_blob_key"]
    if raw is None or raw.sha256 != item["expected_content_sha256"] or raw.bytes != item[
        "declared_bytes"
    ]:
        return AdapterOutcome(status="blocked", failure_code="BYTE_IDENTITY_MISMATCH")
    snapshot = metadata["snapshot_key"]
    derivative = metadata["derivative_key"]
    normalized = metadata["normalized_key"]
    snapshot_value = json.loads(store.get(config["snapshot_key"]))
    derivative_value = json.loads(store.get(config["derivative_key"]))
    if (
        snapshot_value.get("snapshot_id") != result.get("snapshot_id")
        or derivative_value.get("derivative_id") != result.get("derivative_id")
        or derivative_value.get("snapshot_id") != result.get("snapshot_id")
        or derivative_value.get("normalized_key") != config["normalized_key"]
    ):
        return AdapterOutcome(status="rejected", failure_code="EXISTING_REF_BINDING_MISMATCH")
    return AdapterOutcome(
        status="accepted",
        evidence_refs=(config["result_key"],),
        snapshot_id=result.get("snapshot_id"),
        snapshot_key=config["snapshot_key"],
        snapshot_sha256=snapshot.sha256,
        derivative_id=result.get("derivative_id"),
        derivative_key=config["derivative_key"],
        derivative_sha256=derivative.sha256,
        normalized_key=config["normalized_key"],
        normalized_sha256=normalized.sha256,
        raw_blob_key=config["raw_blob_key"],
        raw_sha256=raw.sha256,
        raw_bytes=raw.bytes,
    )

def default_executors() -> dict[str, AdapterExecutor]:
    return {
        LOCAL_MARKDOWN_ADAPTER: _local_markdown_executor,
        EXISTING_INTAKE_ADAPTER: _existing_intake_executor,
    }

def _normalized_output(
    plan: Mapping[str, Any],
    item: Mapping[str, Any],
    outcome: AdapterOutcome,
) -> dict[str, Any]:
    required = [
        outcome.snapshot_id,
        outcome.snapshot_key,
        outcome.snapshot_sha256,
        outcome.derivative_id,
        outcome.derivative_key,
        outcome.derivative_sha256,
        outcome.normalized_key,
        outcome.normalized_sha256,
        outcome.raw_blob_key,
        outcome.raw_sha256,
        outcome.raw_bytes,
    ]
    if any(value is None for value in required):
        raise IntegrityError("M25-INTAKE-146 accepted adapter outcome is incomplete")
    output = {
        "schema_version": NORMALIZED_OUTPUT_SCHEMA,
        "plan_id": plan["plan_id"],
        "item_id": item["item_id"],
        "adapter_id": item["adapter_id"],
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "source_mutation_permitted": False,
        "raw_ref": {
            "object_key": outcome.raw_blob_key,
            "sha256": outcome.raw_sha256,
            "bytes": outcome.raw_bytes,
        },
        "snapshot_ref": {
            "snapshot_id": outcome.snapshot_id,
            "object_key": outcome.snapshot_key,
            "sha256": outcome.snapshot_sha256,
        },
        "derivative_ref": {
            "derivative_id": outcome.derivative_id,
            "object_key": outcome.derivative_key,
            "sha256": outcome.derivative_sha256,
        },
        "normalized_ref": {
            "object_key": outcome.normalized_key,
            "sha256": outcome.normalized_sha256,
        },
        "expected_content_sha256": item["expected_content_sha256"],
        "declared_bytes": item["declared_bytes"],
        "evidence_refs": sorted(set(outcome.evidence_refs)),
    }
    output["output_sha256"] = _digest(output)
    return output

__all__ = ["default_executors"]
