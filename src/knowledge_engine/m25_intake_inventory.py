from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .intake_v1 import (
    AccessPolicy,
    EvidenceValue,
    IntakeFailure,
    LocalFileConnector,
    LocalMarkdownRequest,
)
from .m25_intake_common import (
    FOUNDATION_SHA,
    INVENTORY_SCHEMA,
    LOCAL_MARKDOWN_ADAPTER,
    M25_1_ACCEPTANCE_SHA256,
    M25_1_ENTRY_BASELINE_SHA256,
    M25_2_ENGINE_BASE_SHA,
    MAX_DESCRIPTOR_BYTES,
    MAX_INVENTORY_ITEMS,
    SOURCE_SHA,
    _digest,
    _hex,
    _parse_time,
    _signed,
    _text,
)
from .storage import sha256_bytes

def _policy_objects(
    descriptor: Mapping[str, Any],
) -> tuple[EvidenceValue, EvidenceValue, AccessPolicy]:
    owner_value = descriptor.get("owner")
    license_value = descriptor.get("license")
    access_value = descriptor.get("access_policy")
    if not isinstance(owner_value, Mapping) or not isinstance(license_value, Mapping):
        raise IntegrityError("M25-INTAKE-105 owner and licence evidence are required")
    if not isinstance(access_value, Mapping):
        raise IntegrityError("M25-INTAKE-106 access policy evidence is required")
    owner = EvidenceValue(
        status=str(owner_value.get("status")),
        value=owner_value.get("value") if isinstance(owner_value.get("value"), str) else None,
        observation_source=str(owner_value.get("observation_source")),
    )
    license_evidence = EvidenceValue(
        status=str(license_value.get("status")),
        value=license_value.get("value")
        if isinstance(license_value.get("value"), str)
        else None,
        observation_source=str(license_value.get("observation_source")),
    )
    principals = access_value.get("principals", [])
    if not isinstance(principals, list) or any(not isinstance(item, str) for item in principals):
        raise IntegrityError("M25-INTAKE-106 access principals must be strings")
    access = AccessPolicy(
        policy_type=str(access_value.get("policy_type")),
        principals=tuple(principals),
        observation_source=str(access_value.get("observation_source")),
        native_evidence_ref=(
            access_value.get("native_evidence_ref")
            if isinstance(access_value.get("native_evidence_ref"), str)
            else None
        ),
    )
    return owner, license_evidence, access

def _policy_gate(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    owner, license_evidence, access = _policy_objects(descriptor)
    request = LocalMarkdownRequest(
        locator=_text(descriptor.get("locator"), "locator"),
        original_uri=_text(descriptor.get("original_uri"), "original uri"),
        retrieved_at=_parse_time(descriptor.get("retrieved_at"), "retrieval time"),
        owner=owner,
        license=license_evidence,
        audience=_text(descriptor.get("audience"), "audience", 32),
        access_policy=access,
        source_id=(
            descriptor.get("source_id") if isinstance(descriptor.get("source_id"), str) else None
        ),
        max_bytes=max(1, int(descriptor.get("declared_bytes", 1))),
    )
    try:
        request.validate()
    except IntakeFailure as failure:
        return {
            "status": "blocked",
            "reason_code": failure.code,
            "stage": failure.stage,
            "message": failure.safe_message,
        }
    if owner.status != "resolved":
        return {
            "status": "blocked",
            "reason_code": "OWNER_UNRESOLVED",
            "stage": "preflight",
            "message": "owner evidence is unresolved",
        }
    if license_evidence.status != "resolved":
        return {
            "status": "blocked",
            "reason_code": "LICENSE_UNRESOLVED",
            "stage": "preflight",
            "message": "licence evidence is unresolved",
        }
    if access.policy_type == "unresolved" or access.observation_source == "unresolved":
        return {
            "status": "blocked",
            "reason_code": "ACL_UNRESOLVED",
            "stage": "preflight",
            "message": "access policy is unresolved",
        }
    return {"status": "resolved", "reason_code": None, "stage": None, "message": None}

def _local_descriptor_bytes(descriptor: Mapping[str, Any], allowed_root: Path) -> tuple[int, str]:
    connector = LocalFileConnector(allowed_root)
    path = connector.canonicalize(_text(descriptor.get("locator"), "locator"))
    data = path.read_bytes()
    if not data or len(data) > MAX_DESCRIPTOR_BYTES:
        raise IntegrityError("M25-INTAKE-107 invalid local source byte size")
    return len(data), sha256_bytes(data)

def build_source_inventory(
    descriptors: Sequence[Mapping[str, Any]],
    *,
    captured_at: str,
    allowed_root: Path | None = None,
) -> dict[str, Any]:
    timestamp = _parse_time(captured_at, "inventory capture time")
    if not isinstance(descriptors, Sequence) or isinstance(descriptors, (str, bytes)):
        raise IntegrityError("M25-INTAKE-108 descriptors must be a sequence")
    if not 1 <= len(descriptors) <= MAX_INVENTORY_ITEMS:
        raise IntegrityError("M25-INTAKE-109 inventory population exceeds bounds")

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_acquisitions: set[tuple[str, str, str]] = set()
    for descriptor_value in descriptors:
        if not isinstance(descriptor_value, Mapping):
            raise IntegrityError("M25-INTAKE-110 descriptor must be an object")
        descriptor = dict(descriptor_value)
        adapter_id = _text(descriptor.get("adapter_id"), "adapter id", 120)
        locator = _text(descriptor.get("locator"), "locator")
        original_uri = _text(descriptor.get("original_uri"), "original uri")
        retrieved_at = _parse_time(descriptor.get("retrieved_at"), "retrieval time")
        adapter_config = descriptor.get("adapter_config", {})
        if not isinstance(adapter_config, Mapping):
            raise IntegrityError("M25-INTAKE-111 adapter config must be an object")

        declared_bytes = descriptor.get("declared_bytes")
        expected_sha = descriptor.get("expected_content_sha256")
        if adapter_id == LOCAL_MARKDOWN_ADAPTER:
            if allowed_root is None:
                raise IntegrityError("M25-INTAKE-112 local adapter requires an allowed root")
            observed_bytes, observed_sha = _local_descriptor_bytes(descriptor, allowed_root)
            if declared_bytes is not None and declared_bytes != observed_bytes:
                raise IntegrityError("M25-INTAKE-113 declared byte count mismatch")
            if expected_sha is not None and expected_sha != observed_sha:
                raise IntegrityError("M25-INTAKE-114 expected content digest mismatch")
            declared_bytes = observed_bytes
            expected_sha = observed_sha
        else:
            if not isinstance(declared_bytes, int) or isinstance(declared_bytes, bool):
                raise IntegrityError("M25-INTAKE-115 declared bytes are required")
            expected_sha = _hex(expected_sha, 64, "expected content digest")

        if not isinstance(declared_bytes, int) or isinstance(declared_bytes, bool):
            raise IntegrityError("M25-INTAKE-115 declared bytes are required")
        if not 1 <= declared_bytes <= MAX_DESCRIPTOR_BYTES:
            raise IntegrityError("M25-INTAKE-116 declared bytes exceed inventory bounds")
        expected_sha = _hex(expected_sha, 64, "expected content digest")
        policy_gate = _policy_gate({**descriptor, "declared_bytes": declared_bytes})
        identity = {
            "adapter_id": adapter_id,
            "locator": locator,
            "original_uri": original_uri,
            "retrieved_at": retrieved_at,
            "source_id": descriptor.get("source_id"),
            "owner": descriptor.get("owner"),
            "license": descriptor.get("license"),
            "audience": descriptor.get("audience"),
            "access_policy": descriptor.get("access_policy"),
            "declared_bytes": declared_bytes,
            "expected_content_sha256": expected_sha,
            "adapter_config": dict(adapter_config),
        }
        acquisition_identity = (adapter_id, locator, expected_sha)
        item_id = "m25item_" + _digest(identity)
        if item_id in seen or acquisition_identity in seen_acquisitions:
            raise IntegrityError("M25-INTAKE-117 duplicate source descriptor")
        seen.add(item_id)
        seen_acquisitions.add(acquisition_identity)
        items.append(
            {
                "item_id": item_id,
                **identity,
                "policy_gate": policy_gate,
            }
        )

    items.sort(key=lambda item: item["item_id"])
    body = {
        "schema_version": INVENTORY_SCHEMA,
        "captured_at": timestamp,
        "entry_baseline": {
            "engine_sha": M25_2_ENGINE_BASE_SHA,
            "source_sha": SOURCE_SHA,
            "foundation_sha": FOUNDATION_SHA,
            "m25_1_entry_baseline_sha256": M25_1_ENTRY_BASELINE_SHA256,
            "m25_1_acceptance_sha256": M25_1_ACCEPTANCE_SHA256,
        },
        "authority": "evidence_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "source_count": len(items),
        "total_declared_bytes": sum(item["declared_bytes"] for item in items),
        "policy_blocked_count": sum(
            item["policy_gate"]["status"] == "blocked" for item in items
        ),
        "items": items,
    }
    identity_sha = _digest(body)
    inventory = {**body, "inventory_id": "m25inv_" + identity_sha}
    inventory["inventory_sha256"] = _digest(inventory)
    return inventory

def _validate_inventory(inventory: Mapping[str, Any]) -> str:
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        raise IntegrityError("M25-INTAKE-118 invalid inventory schema")
    digest = _signed(inventory, "inventory_sha256", "M25-INTAKE-119 inventory digest mismatch")
    if (
        inventory.get("authority") != "evidence_only"
        or inventory.get("canonical_knowledge") is not False
        or inventory.get("production_authority") is not False
    ):
        raise IntegrityError("M25-INTAKE-120 inventory authority drift")
    items = inventory.get("items")
    if not isinstance(items, list) or inventory.get("source_count") != len(items):
        raise IntegrityError("M25-INTAKE-121 inventory population mismatch")
    if len({item.get("item_id") for item in items if isinstance(item, Mapping)}) != len(items):
        raise IntegrityError("M25-INTAKE-122 duplicate inventory item id")
    total = sum(item.get("declared_bytes", 0) for item in items if isinstance(item, Mapping))
    if inventory.get("total_declared_bytes") != total:
        raise IntegrityError("M25-INTAKE-123 inventory byte denominator mismatch")
    return digest

