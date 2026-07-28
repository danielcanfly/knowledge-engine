from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ENTRY_GATE_SCHEMA_VERSION = "knowledge-engine-m26-pa-5-entry-gate/v1"
OWNER_DECISION_SCHEMA_VERSION = "knowledge-engine-m26-pa-5-owner-decision/v1"
PILOT_RECEIPT_SCHEMA_VERSION = "knowledge-engine-m26-pa-5-pilot-receipt/v1"
STAGE_ID = "M26.PA.5"
BLOCKED_STATUS = "m26_pa_5_blocked_pending_owner_approval"
ACCEPTED_STATUS = "m26_pa_5_controlled_internal_shadow_pilot_accepted"
REQUIRED_PREDECESSOR_STATUS = "m26_pa_4_verified_answer_citation_gate_accepted"
PA4_ACCEPTANCE_SELF_SHA256 = (
    "0581fc85a34b106c3dce5ec9c27adc3c215a87008f30384da7f574bfcbf13ac7"
)


class PA5GateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PA5GateError("M26-PA5-001", f"invalid JSON: {path.as_posix()}") from exc
    if not isinstance(value, dict):
        raise PA5GateError("M26-PA5-002", f"expected object: {path.as_posix()}")
    return value


def assert_self_digest(value: Mapping[str, Any], *, label: str) -> None:
    expected = value.get("self_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise PA5GateError("M26-PA5-003", f"{label} self digest missing")
    candidate = dict(value)
    candidate["self_sha256"] = ""
    if canonical_sha256(candidate) != expected:
        raise PA5GateError("M26-PA5-004", f"{label} self digest mismatch")


def validate_schema(value: Mapping[str, Any], schema: Mapping[str, Any], *, label: str) -> None:
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        path = ".".join(str(part) for part in errors[0].absolute_path) or "<root>"
        raise PA5GateError("M26-PA5-005", f"{label} schema error at {path}")


def validate_entry_gate(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != ENTRY_GATE_SCHEMA_VERSION:
        raise PA5GateError("M26-PA5-006", "entry gate schema version mismatch")
    if value.get("stage_id") != STAGE_ID:
        raise PA5GateError("M26-PA5-007", "entry gate stage mismatch")
    if value.get("status") != BLOCKED_STATUS:
        raise PA5GateError("M26-PA5-008", "PA.5 must remain blocked before owner approval")
    predecessor = value.get("predecessor")
    if not isinstance(predecessor, Mapping):
        raise PA5GateError("M26-PA5-009", "predecessor block missing")
    if predecessor.get("pa4_status") != REQUIRED_PREDECESSOR_STATUS:
        raise PA5GateError("M26-PA5-010", "PA.4 accepted status missing")
    if predecessor.get("pa4_acceptance_self_sha256") != PA4_ACCEPTANCE_SELF_SHA256:
        raise PA5GateError("M26-PA5-011", "PA.4 acceptance digest mismatch")
    authority = value.get("authority_boundary")
    if not isinstance(authority, Mapping) or any(authority.values()):
        raise PA5GateError("M26-PA5-012", "entry gate grants forbidden authority")
    owner_gate = value.get("owner_gate")
    if not isinstance(owner_gate, Mapping) or owner_gate.get("required") is not True:
        raise PA5GateError("M26-PA5-013", "owner gate is not required")
    if owner_gate.get("approval_received") is not False:
        raise PA5GateError("M26-PA5-014", "owner approval must not be pre-claimed")
    assert_self_digest(value, label="PA.5 entry gate")
    return {
        "stage_id": STAGE_ID,
        "status": BLOCKED_STATUS,
        "predecessor_status": REQUIRED_PREDECESSOR_STATUS,
        "owner_gate_required": True,
    }


def render_owner_approval_block(
    *,
    implementation_pr: int,
    implementation_head_sha: str,
    pa4_acceptance_sha: str = PA4_ACCEPTANCE_SELF_SHA256,
) -> str:
    return f"""I explicitly approve M26.PA.5 controlled internal shadow pilot with:
- exact implementation PR/head: #{implementation_pr} / {implementation_head_sha}
- exact predecessor acceptance: {pa4_acceptance_sha}
- frozen population count/digest: <COUNT_200_TO_500> / <SHA256>
- reviewer principals and types: <ROSTER_WITH_HUMAN_MODEL_VERIFIER_TYPES>
- adjudicator: <IDENTITY>
- execution duration/window: <WINDOW>
- provider/model and credential environment: <VALUES>
- maximum calls and total spend: <VALUES>
- quality, citation, abstention, latency, cost, and disagreement thresholds: <VALUES>
- incident stop conditions: <VALUES>
- authenticated internal/shadow only; no public answers or production serving

This approval does not authorize PA.6 canary traffic, production pointer mutation, or \
PA.7 closure."""
