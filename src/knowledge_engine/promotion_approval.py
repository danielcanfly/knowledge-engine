from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .batch_spec import load_batch_spec
from .errors import IntegrityError
from .promotion_request import load_promotion_request_spec

SCHEMA_VERSION = "production-promotion-approval/v1"
APPROVAL_ROOT = Path("governed_batches/evidence")
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_SCOPE = {
    "promotion_dispatch_authorized": True,
    "post_promote_acceptance_authorized": True,
    "permanent_ledger_append_on_success_authorized": True,
    "request_modification_authorized": False,
    "target_substitution_authorized": False,
    "baseline_weakening_authorized": False,
    "raw_fallback_authorized": False,
    "rollback_authorized": False,
    "idempotent_replay_authorized": False,
}


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise IntegrityError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntegrityError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"{label} must be a JSON object")
    return value


def _string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError(f"{label} field is required: {key}")
    return value.strip()


def _object(payload: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise IntegrityError(f"{label} field must be an object: {key}")
    return value


def _validate_approval_path(path: Path) -> None:
    if path.is_absolute() or path.parent != APPROVAL_ROOT or path.suffix != ".json":
        raise IntegrityError(
            "approval path must match governed_batches/evidence/*.json"
        )


def _validate_timestamp(value: str) -> None:
    if not value.endswith("Z"):
        raise IntegrityError("authorized_at must be an ISO-8601 UTC timestamp")
    try:
        datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise IntegrityError("authorized_at must be an ISO-8601 UTC timestamp") from exc


def validate_production_promotion_approval(
    *,
    approval_path: str | Path,
    spec_path: str | Path,
    request_path: str | Path,
) -> dict[str, Any]:
    approval_path = Path(approval_path)
    request_path = Path(request_path)
    _validate_approval_path(approval_path)

    approval = _read_object(approval_path, "promotion approval")
    spec = load_batch_spec(spec_path)
    request = load_promotion_request_spec(
        request_path=request_path,
        control_plane_sha="0" * 40,
    )
    normalized = request.normalized()

    if approval.get("schema_version") != SCHEMA_VERSION:
        raise IntegrityError(
            f"promotion approval schema_version must be {SCHEMA_VERSION!r}"
        )
    if _string(approval, "batch_id", "promotion approval") != spec.batch_id:
        raise IntegrityError("promotion approval batch_id does not match batch spec")
    if approval.get("decision") != "approve":
        raise IntegrityError("promotion approval decision must be approve")
    _string(approval, "authorized_by", "promotion approval")
    _validate_timestamp(_string(approval, "authorized_at", "promotion approval"))
    _string(approval, "authorization_text", "promotion approval")
    if not isinstance(approval.get("approval_issue"), int) or approval["approval_issue"] <= 0:
        raise IntegrityError("promotion approval approval_issue must be a positive integer")

    if spec.lifecycle_state != "request_spec_committed":
        raise IntegrityError(
            "promotion approval requires lifecycle_state request_spec_committed"
        )

    approved_request = _object(approval, "request", "promotion approval")
    approved_request_path = _string(
        approved_request,
        "request_path",
        "promotion approval request",
    )
    if approved_request_path != str(request_path):
        raise IntegrityError("promotion approval request_path does not match input")
    if approved_request_path != spec.request_path:
        raise IntegrityError("promotion approval request_path does not match batch spec")
    if _string(approved_request, "operation_id", "promotion approval request") != (
        spec.operation_id
    ):
        raise IntegrityError("promotion approval operation_id does not match batch spec")

    request_sha256 = hashlib.sha256(request_path.read_bytes()).hexdigest()
    approved_sha256 = _string(
        approved_request,
        "request_sha256",
        "promotion approval request",
    )
    if not SHA256.fullmatch(approved_sha256) or approved_sha256 != request_sha256:
        raise IntegrityError("promotion approval request_sha256 does not match request bytes")
    request_merge_commit = _string(
        approved_request,
        "request_merge_commit",
        "promotion approval request",
    )
    if not SHA.fullmatch(request_merge_commit):
        raise IntegrityError("promotion approval request_merge_commit is invalid")

    if "control_plane_sha" in request.raw:
        raise IntegrityError("committed promotion request must not contain control_plane_sha")

    target = _object(approval, "target", "promotion approval")
    expected_target = {
        "candidate_channel": normalized["candidate_channel"],
        "release_id": normalized["release_id"],
        "manifest_sha256": normalized["manifest_sha256"],
        "source_repository": normalized["source_repository"],
        "source_sha": normalized["source_sha"],
        "builder_sha": normalized["builder_sha"],
        "foundation_sha": normalized["foundation_sha"],
    }
    if target != expected_target:
        raise IntegrityError("promotion approval target does not match committed request")

    previous = _object(
        approval,
        "expected_previous_production",
        "promotion approval",
    )
    expected_previous = {
        "release_id": normalized["expected_previous_release_id"],
        "manifest_sha256": normalized["expected_previous_manifest_sha256"],
        "pointer_sha256": _string(
            previous,
            "pointer_sha256",
            "expected_previous_production",
        ),
    }
    if not SHA256.fullmatch(expected_previous["pointer_sha256"]):
        raise IntegrityError("expected previous production pointer_sha256 is invalid")
    if previous != expected_previous:
        raise IntegrityError(
            "promotion approval previous production does not match committed request"
        )

    acceptance = _object(
        approval,
        "required_post_promote_acceptance",
        "promotion approval",
    )
    expected_acceptance = {
        "public_query": normalized["post_promote_public_query"],
        "expected_public_status": normalized["expected_public_status"],
        "expected_citation_url": normalized["expected_citation_url"],
        "acl_query": normalized.get("post_promote_acl_query"),
        "expected_acl_status": normalized.get("expected_acl_status"),
        "raw_fallback_allowed": False,
    }
    if acceptance != expected_acceptance:
        raise IntegrityError(
            "promotion approval acceptance contract does not match committed request"
        )

    scope = _object(approval, "authorization_scope", "promotion approval")
    if scope != REQUIRED_SCOPE:
        raise IntegrityError("promotion approval authorization_scope is invalid")

    if approval.get("lifecycle_state_before_dispatch") != "request_spec_committed":
        raise IntegrityError("approval lifecycle_state_before_dispatch is invalid")
    if approval.get("lifecycle_transition_authorized_on_success") != (
        "request_spec_committed -> production_promoted"
    ):
        raise IntegrityError("approval lifecycle transition is invalid")
    if approval.get("production_mutated_during_approval") is not False:
        raise IntegrityError("approval must not claim a production mutation")
    if approval.get("mutations_performed") != []:
        raise IntegrityError("approval mutations_performed must be empty")
    if approval.get("next_action") != "dispatch_production_promotion":
        raise IntegrityError("approval next_action must be dispatch_production_promotion")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "approved",
        "batch_id": spec.batch_id,
        "decision": approval["decision"],
        "authorized_by": approval["authorized_by"],
        "authorized_at": approval["authorized_at"],
        "approval_issue": approval["approval_issue"],
        "approval_path": str(approval_path),
        "approval_sha256": hashlib.sha256(approval_path.read_bytes()).hexdigest(),
        "operation_id": spec.operation_id,
        "request_path": spec.request_path,
        "request_sha256": request_sha256,
        "target_release_id": normalized["release_id"],
        "target_manifest_sha256": normalized["manifest_sha256"],
        "expected_previous_release_id": normalized["expected_previous_release_id"],
        "expected_previous_manifest_sha256": normalized[
            "expected_previous_manifest_sha256"
        ],
        "expected_previous_pointer_sha256": previous["pointer_sha256"],
        "production_dispatch_authorized": True,
        "production_mutated": False,
        "mutations_performed": [],
        "next_action": "dispatch_production_promotion",
    }


def write_approval_validation(result: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
