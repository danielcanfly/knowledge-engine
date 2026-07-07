from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .batch_registry import load_batch_registry, validate_batch_registry
from .batch_spec import REGISTRY_PATH, load_batch_spec
from .errors import IntegrityError

REQUIRED_HEALTH = {
    "ci": "success",
    "r2_release_integration": "success",
    "replay_rollback": "success",
    "ledger_open": True,
}


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise IntegrityError(f"{label} does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntegrityError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise IntegrityError(f"{label} must be a JSON object")
    return payload


def _validate_health(path: Path) -> dict[str, Any]:
    payload = _load_object(path, "workflow health evidence")
    for key, expected in REQUIRED_HEALTH.items():
        if payload.get(key) != expected:
            raise IntegrityError(
                f"workflow health {key} must be {expected!r}, got {payload.get(key)!r}"
            )
    return {key: payload[key] for key in REQUIRED_HEALTH}


def _validate_pointer(
    path: Path,
    expected_release_id: str,
    expected_manifest_sha256: str,
) -> dict[str, str]:
    payload = _load_object(path, "production pointer evidence")
    actual = {
        "release_id": payload.get("release_id"),
        "manifest_sha256": payload.get("manifest_sha256"),
    }
    expected = {
        "release_id": expected_release_id,
        "manifest_sha256": expected_manifest_sha256,
    }
    if actual != expected:
        raise IntegrityError(
            f"production pointer drift: expected {expected!r}, got {actual!r}"
        )
    return expected


def _validate_batch_contracts(spec_paths: list[str]) -> dict[str, Any]:
    owners: dict[str, str] = {}
    batches: list[dict[str, Any]] = []
    for spec_path in spec_paths:
        spec = load_batch_spec(spec_path)
        source_paths = spec.raw["source"]["paths"]
        for source_path in source_paths:
            if source_path in owners:
                raise IntegrityError(
                    "Source path overlap: "
                    f"{source_path} is owned by {owners[source_path]} and {spec.batch_id}"
                )
            owners[source_path] = spec.batch_id

        acceptance = spec.raw["acceptance"]
        citation_url = acceptance["expected_citation_url"]
        parsed = urlsplit(citation_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise IntegrityError(
                f"batch {spec.batch_id} citation target must use stable HTTPS"
            )
        if acceptance.get("acl_query") is None:
            raise IntegrityError(f"batch {spec.batch_id} must configure an ACL query")
        if acceptance.get("expected_acl_status") != "not_found":
            raise IntegrityError(
                f"batch {spec.batch_id} ACL expected status must be not_found"
            )
        if acceptance.get("raw_fallback_allowed") is not False:
            raise IntegrityError(
                f"batch {spec.batch_id} must keep raw fallback disabled"
            )
        batches.append(
            {
                "batch_id": spec.batch_id,
                "lifecycle_state": spec.lifecycle_state,
                "source_path_count": len(source_paths),
                "citation_url": citation_url,
                "acl_status": "not_found",
            }
        )
    return {
        "batch_count": len(batches),
        "source_path_count": len(owners),
        "batches": batches,
    }


def run_scale_readiness(
    *,
    registry_path: Path = REGISTRY_PATH,
    production_pointer_path: Path,
    expected_release_id: str,
    expected_manifest_sha256: str,
    workflow_health_path: Path,
) -> dict[str, Any]:
    registry = load_batch_registry(registry_path)
    registry_result = validate_batch_registry(registry)
    if not registry.entries:
        raise IntegrityError("batch registry must contain at least one governed batch")

    contracts = _validate_batch_contracts(
        [entry.spec_path for entry in registry.entries]
    )
    pointer = _validate_pointer(
        production_pointer_path,
        expected_release_id,
        expected_manifest_sha256,
    )
    health = _validate_health(workflow_health_path)
    return {
        "status": "ready_for_governed_dry_run",
        "registry": registry_result,
        "contracts": contracts,
        "production_pointer": pointer,
        "workflow_health": health,
        "mutations_performed": [],
    }


def write_readiness_evidence(result: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
