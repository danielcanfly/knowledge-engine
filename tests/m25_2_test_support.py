from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledge_engine.m25_intake_orchestrator import (
    LOCAL_MARKDOWN_ADAPTER,
    build_plan_bundle,
    build_source_inventory,
    persist_plan_bundle,
)
from knowledge_engine.storage import FileObjectStore

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas"
M25_DOC_ROOT = ROOT / "docs" / "architecture" / "m25"

def _resolved(value: str) -> dict[str, Any]:
    return {
        "status": "resolved",
        "value": value,
        "observation_source": "operator_asserted",
    }


def _unresolved() -> dict[str, Any]:
    return {
        "status": "unresolved",
        "value": None,
        "observation_source": "unresolved",
    }


def _public_access() -> dict[str, Any]:
    return {
        "policy_type": "public",
        "principals": [],
        "observation_source": "operator_asserted",
        "native_evidence_ref": "fixture:public",
    }


def _descriptor(
    locator: str,
    *,
    license_value: dict[str, Any] | None = None,
    adapter_id: str = LOCAL_MARKDOWN_ADAPTER,
    declared_bytes: int | None = None,
    expected_content_sha256: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "adapter_id": adapter_id,
        "locator": locator,
        "original_uri": f"file:///{locator}",
        "retrieved_at": "2026-07-23T00:00:00Z",
        "owner": _resolved("Daniel Huang"),
        "license": license_value or _resolved("first-party"),
        "audience": "public",
        "access_policy": _public_access(),
        "adapter_config": {},
    }
    if declared_bytes is not None:
        value["declared_bytes"] = declared_bytes
    if expected_content_sha256 is not None:
        value["expected_content_sha256"] = expected_content_sha256
    return value


def _prepare(
    root: Path,
    descriptors: list[dict[str, Any]],
    *,
    max_sources: int = 25,
    max_bytes: int = 200_000,
    max_attempts: int = 8,
) -> tuple[FileObjectStore, dict[str, Any]]:
    inventory = build_source_inventory(
        descriptors,
        captured_at="2026-07-23T00:00:00Z",
        allowed_root=root,
    )
    bundle = build_plan_bundle(
        inventory,
        max_sources_per_batch=max_sources,
        max_bytes_per_batch=max_bytes,
        max_attempts=max_attempts,
        created_at="2026-07-23T00:00:00Z",
    )
    store = FileObjectStore(root / "store")
    persist_plan_bundle(store, bundle)
    return store, bundle


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


