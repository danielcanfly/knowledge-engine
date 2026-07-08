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

SCHEMA_VERSION = "idempotent-replay-approval/v1"
EVIDENCE_ROOT = Path("governed_batches/evidence")
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

REQUIRED_SCOPE = {
    "single_idempotent_replay_dispatch_authorized": True,
    "verify_existing_intent_authorized": True,
    "verify_existing_receipt_authorized": True,
    "post_replay_acceptance_authorized": True,
    "permanent_ledger_append_on_success_authorized": True,
    "closure_reconciliation_after_success_authorized": True,
    "request_modification_authorized": False,
    "operation_id_replacement_authorized": False,
    "target_substitution_authorized": False,
    "baseline_weakening_authorized": False,
    "raw_fallback_authorized": False,
    "rollback_authorized": False,
    "new_non_idempotent_promotion_authorized": False,
    "additional_replays_authorized": False,
}

REQUIRED_REPLAY_OUTCOME = {
    "precondition_state": "already_target",
    "promotion_status": "already_promoted",
    "idempotent": True,
    "production_pointer_byte_exact_unchanged": True,
    "operation_intent_reused": True,
    "promotion_receipt_reused": True,
}


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise IntegrityError(f"{label} does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntegrityError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise IntegrityError(f"{label} must be a JSON object")
    return payload


def _object(payload: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise IntegrityError(f"{label} field must be an object: {key}")
    return value


def _string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError(f"{label} field is required: {key}")
    return value.strip()


def _validate_evidence_path(path: Path, label: str) -> None:
    if path.is_absolute() or path.parent != EVIDENCE_ROOT or path.suffix != ".json":
        raise IntegrityError(
            f"{label} path must match governed_batches/evidence/*.json"
        )


def _validate_timestamp(value: str) -> None:
    if not value.endswith("Z"):
        raise IntegrityError("authorized_at must be an ISO-8601 UTC timestamp")
    try:
        datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise IntegrityError("authorized_at must be an ISO-8601 UTC timestamp") from exc


def validate_idempotent_replay_approval(
    *,
    approval_path: str | Path,
    spec_path: str | Path,
    request_path: str | Path,
    promotion_observation_path: str | Path,
    lifecycle_path: str | Path,
) -> dict[str, Any]:
    approval_path = Path(approval_path)
    request_path = Path(request_path)
    observation_path = Path(promotion_observation_path)
    lifecycle_path = Path(lifecycle_path)
    _validate_evidence_path(approval_path, "replay approval")
    _validate_evidence_path(observation_path, "promotion observation")
    _validate_evidence_path(lifecycle_path, "lifecycle history")

    approval = _read_object(approval_path, "replay approval")
    observation = _read_object(observation_path, "promotion observation")
    lifecycle = _read_object(lifecycle_path, "lifecycle history")
    spec = load_batch_spec(spec_path)
    request = load_promotion_request_spec(
        request_path=request_path,
        control_plane_sha="0" * 40,
    )
    normalized = request.normalized()

    if approval.get("schema_version") != SCHEMA_VERSION:
        raise IntegrityError(f"replay approval schema_version must be {SCHEMA_VERSION!r}")
    if _string(approval, "batch_id", "replay approval") != spec.batch_id:
        raise IntegrityError("replay approval batch_id does not match batch spec")
    if approval.get("decision") != "approve":
        raise IntegrityError("replay approval decision must be approve")
    _string(approval, "authorized_by", "replay approval")
    _validate_timestamp(_string(approval, "authorized_at", "replay approval"))
    _string(approval, "authorization_text", "replay approval")
    if not isinstance(approval.get("approval_issue"), int) or approval["approval_issue"] <= 0:
        raise IntegrityError("replay approval approval_issue must be a positive integer")

    if spec.lifecycle_state != "production_promoted":
        raise IntegrityError(
            "idempotent replay approval requires lifecycle_state production_promoted"
        )

    approved_request = _object(approval, "request", "replay approval")
    if _string(approved_request, "request_path", "replay approval request") != str(
        request_path
    ):
        raise IntegrityError("replay approval request_path does not match input")
    if approved_request["request_path"] != spec.request_path:
        raise IntegrityError("replay approval request_path does not match batch spec")
    if _string(approved_request, "operation_id", "replay approval request") != (
        spec.operation_id
    ):
        raise IntegrityError("replay approval operation_id does not match batch spec")

    request_sha256 = hashlib.sha256(request_path.read_bytes()).hexdigest()
    if approved_request.get("request_sha256") != request_sha256:
        raise IntegrityError("replay approval request_sha256 does not match request bytes")
    request_merge_commit = _string(
        approved_request,
        "request_merge_commit",
        "replay approval request",
    )
    if not SHA.fullmatch(request_merge_commit):
        raise IntegrityError("replay approval request_merge_commit is invalid")
    if "control_plane_sha" in request.raw:
        raise IntegrityError("committed promotion request must not contain control_plane_sha")

    if observation.get("status") != "passed":
        raise IntegrityError("promotion observation must have passed")
    if observation.get("batch_id") != spec.batch_id:
        raise IntegrityError("promotion observation batch_id does not match batch spec")
    if observation.get("production_mutated") is not True:
        raise IntegrityError("promotion observation must record production mutation")
    security = _object(observation, "security_notes", "promotion observation")
    if security.get("idempotent_replay_used") is not False:
        raise IntegrityError("promotion observation must precede idempotent replay")
    if security.get("rollback_used") is not False:
        raise IntegrityError("promotion observation must not record rollback")

    promotion = _object(observation, "promotion", "promotion observation")
    ledger = _object(observation, "ledger", "promotion observation")
    original = _object(approval, "original_promotion", "replay approval")
    expected_original = {
        "run_id": promotion.get("run_id"),
        "job_id": promotion.get("job_id"),
        "artifact_id": promotion.get("artifact_id"),
        "artifact_digest": promotion.get("artifact_digest"),
        "control_plane_sha": promotion.get("control_plane_sha"),
        "precondition_state": promotion.get("precondition_state"),
        "status": promotion.get("status"),
        "idempotent": promotion.get("idempotent"),
        "ledger_comment_id": ledger.get("comment_id"),
        "reconciliation_merge_commit": original.get("reconciliation_merge_commit"),
    }
    if original != expected_original:
        raise IntegrityError("replay approval original promotion identity is invalid")
    if not isinstance(original["run_id"], int) or original["run_id"] <= 0:
        raise IntegrityError("original promotion run_id is invalid")
    if not isinstance(original["job_id"], int) or original["job_id"] <= 0:
        raise IntegrityError("original promotion job_id is invalid")
    if not isinstance(original["artifact_id"], int) or original["artifact_id"] <= 0:
        raise IntegrityError("original promotion artifact_id is invalid")
    if not DIGEST.fullmatch(original["artifact_digest"]):
        raise IntegrityError("original promotion artifact_digest is invalid")
    if not SHA.fullmatch(original["control_plane_sha"]):
        raise IntegrityError("original promotion control_plane_sha is invalid")
    if not SHA.fullmatch(original["reconciliation_merge_commit"]):
        raise IntegrityError("reconciliation_merge_commit is invalid")
    if original["precondition_state"] != "ready_to_promote":
        raise IntegrityError("original promotion precondition must be ready_to_promote")
    if original["status"] != "promoted" or original["idempotent"] is not False:
        raise IntegrityError("original promotion must be non-idempotent and promoted")

    current = _object(approval, "current_production", "replay approval")
    target = _object(observation, "production_target", "promotion observation")
    if current != target:
        raise IntegrityError("replay approval current production does not match target")
    if current.get("release_id") != normalized["release_id"]:
        raise IntegrityError("current production release does not match request")
    if current.get("manifest_sha256") != normalized["manifest_sha256"]:
        raise IntegrityError("current production manifest does not match request")
    if not SHA256.fullmatch(str(current.get("pointer_sha256", ""))):
        raise IntegrityError("current production pointer_sha256 is invalid")

    replay_outcome = _object(
        approval,
        "required_replay_outcome",
        "replay approval",
    )
    if replay_outcome != REQUIRED_REPLAY_OUTCOME:
        raise IntegrityError("replay approval required_replay_outcome is invalid")

    acceptance = _object(
        approval,
        "required_post_replay_acceptance",
        "replay approval",
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
        raise IntegrityError("replay approval acceptance contract is invalid")

    scope = _object(approval, "authorization_scope", "replay approval")
    if scope != REQUIRED_SCOPE:
        raise IntegrityError("replay approval authorization_scope is invalid")
    if approval.get("lifecycle_state_before_replay") != "production_promoted":
        raise IntegrityError("replay approval lifecycle_state_before_replay is invalid")
    if approval.get("lifecycle_transition_authorized_after_successful_replay") != (
        "production_promoted -> closed"
    ):
        raise IntegrityError("replay approval lifecycle transition is invalid")
    if approval.get("replay_dispatched_during_approval") is not False:
        raise IntegrityError("approval must not claim replay dispatch")
    if approval.get("production_mutated_during_approval") is not False:
        raise IntegrityError("approval must not claim production mutation")
    if approval.get("permanent_ledger_appended_during_approval") is not False:
        raise IntegrityError("approval must not claim permanent ledger append")
    if approval.get("mutations_performed") != []:
        raise IntegrityError("replay approval mutations_performed must be empty")
    if approval.get("next_action") != "dispatch_idempotent_replay":
        raise IntegrityError("replay approval next_action is invalid")

    transitions = [
        (item.get("from"), item.get("to"))
        for item in lifecycle.get("transitions", [])
        if isinstance(item, dict)
    ]
    if not transitions or transitions[-1] != (
        "request_spec_committed",
        "production_promoted",
    ):
        raise IntegrityError("lifecycle history is not ready for replay approval")
    if lifecycle.get("final_state") != "production_promoted":
        raise IntegrityError("lifecycle final_state must be production_promoted")
    if lifecycle.get("next_legal_action") != "review_idempotent_replay":
        raise IntegrityError("lifecycle next_legal_action must be review_idempotent_replay")

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
        "target_pointer_sha256": current["pointer_sha256"],
        "original_promotion_run": original["run_id"],
        "original_promotion_artifact": original["artifact_id"],
        "single_idempotent_replay_dispatch_authorized": True,
        "permanent_ledger_append_on_success_authorized": True,
        "closure_reconciliation_after_success_authorized": True,
        "rollback_authorized": False,
        "additional_replays_authorized": False,
        "replay_dispatched": False,
        "production_mutated": False,
        "permanent_ledger_appended": False,
        "mutations_performed": [],
        "next_action": "dispatch_idempotent_replay",
    }


def write_replay_approval_validation(result: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
