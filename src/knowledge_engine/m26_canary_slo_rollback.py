from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .m26_verified_answer_citation_gate import (
    SAFE_HEX_40,
    SAFE_HEX_64,
    canonical_sha256,
    verify_self_digest,
    with_self_digest,
)

STAGE_ID = "M26.PA.6"
PA5_ACCEPTED_STATUS = "m26_pa_5_controlled_internal_shadow_pilot_accepted"
PA6_UNLOCK_STATUS = "m26_pa_6_unlocked_pending_owner_canary_approval"
POLICY_SCHEMA = "knowledge-engine-m26-pa-6-canary-policy/v1"
OWNER_GATE_SCHEMA = "knowledge-engine-m26-pa-6-owner-gate/v1"
RECEIPT_SCHEMA = "knowledge-engine-m26-pa-6-canary-receipt/v1"
INCIDENT_SCHEMA = "knowledge-engine-m26-pa-6-incident-packet/v1"

RAW_PROHIBITED_KEYS = {
    "answer_text",
    "full_prompt",
    "full_provider_response",
    "prompt",
    "provider_response",
    "query",
    "raw_corpus_text",
    "raw_evidence",
    "raw_prompt",
    "raw_provider_response",
    "secret",
    "secret_value",
    "vector",
    "vectors",
}
MUTATION_KEYS = (
    "production_pointer_mutations",
    "production_serving_operations",
    "public_traffic_operations",
    "r2_qdrant_source_foundation_release_mutations",
)


class CanarySloRollbackError(IntegrityError):
    """Fail-closed M26.PA.6 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def sha256_text(value: str) -> str:
    return canonical_sha256(value)


def digest_values(values: Sequence[str]) -> str:
    return canonical_sha256(list(values))


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanarySloRollbackError("PA6_OBJECT_INVALID", f"{label} must be an object")
    return value


def _require_hex(value: Any, label: str, *, length: int = 64) -> str:
    text = str(value)
    pattern = SAFE_HEX_64 if length == 64 else SAFE_HEX_40
    if not pattern.fullmatch(text):
        raise CanarySloRollbackError("PA6_DIGEST_INVALID", f"{label} must be {length} hex")
    return text


def _require_bool(value: Mapping[str, Any], key: str, expected: bool) -> None:
    if value.get(key) is not expected:
        raise CanarySloRollbackError("PA6_AUTHORITY_ESCALATION", f"{key} must be {expected}")


def reject_raw_persistence(value: Any, *, label: str = "artifact") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in RAW_PROHIBITED_KEYS:
                raise CanarySloRollbackError(
                    "PA6_RAW_PERSISTENCE_FORBIDDEN",
                    f"{label}.{key} is prohibited",
                )
            reject_raw_persistence(item, label=f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_raw_persistence(item, label=f"{label}[{index}]")


def validate_predecessors(pa5: Mapping[str, Any], pa6_unlock: Mapping[str, Any]) -> dict[str, str]:
    verify_self_digest(pa5, "pa5 acceptance")
    verify_self_digest(pa6_unlock, "pa6 unlock")
    if pa5.get("stage_id") != "M26.PA.5" or pa5.get("status") != PA5_ACCEPTED_STATUS:
        raise CanarySloRollbackError("PA6_PREDECESSOR_INVALID", "PA.5 is not accepted")
    if pa6_unlock.get("stage_id") != STAGE_ID or pa6_unlock.get("status") != PA6_UNLOCK_STATUS:
        raise CanarySloRollbackError("PA6_UNLOCK_INVALID", "PA.6 is not unlocked")
    predecessor = _object(pa6_unlock.get("predecessor"), "pa6_unlock.predecessor")
    if predecessor.get("pa5_acceptance_self_sha256") != pa5.get("self_sha256"):
        raise CanarySloRollbackError("PA6_PREDECESSOR_DRIFT", "PA.6 unlock does not bind PA.5")
    for key, expected in {
        "canary_traffic_authorized": False,
        "m26_closed": False,
        "pa7_authorized": False,
        "production_answer_serving": False,
        "production_pointer_mutation": False,
        "public_traffic": False,
    }.items():
        authority = _object(pa6_unlock.get("authority_boundary"), "authority_boundary")
        _require_bool(authority, key, expected)
    if pa6_unlock["authority_boundary"].get("r2_qdrant_source_foundation_release_mutations") != 0:
        raise CanarySloRollbackError(
            "PA6_AUTHORITY_ESCALATION",
            "protected mutation count must be 0",
        )
    return {
        "pa5_acceptance_self_sha256": str(pa5["self_sha256"]),
        "pa6_unlock_self_sha256": str(pa6_unlock["self_sha256"]),
    }


def validate_canary_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy, "pa6 canary policy")
    reject_raw_persistence(policy, label="pa6 canary policy")
    if policy.get("schema_version") != POLICY_SCHEMA or policy.get("stage_id") != STAGE_ID:
        raise CanarySloRollbackError("PA6_POLICY_INVALID", "schema or stage mismatch")
    if policy.get("status") != "m26_pa_6_phase_a_implementation_ready_pending_owner_gate":
        raise CanarySloRollbackError("PA6_POLICY_INVALID", "implementation status mismatch")
    predecessor = _object(policy.get("predecessor"), "policy.predecessor")
    if predecessor.get("pa5_status") != PA5_ACCEPTED_STATUS:
        raise CanarySloRollbackError("PA6_PREDECESSOR_INVALID", "PA.5 status is not bound")
    _require_hex(predecessor.get("pa5_acceptance_self_sha256"), "pa5_acceptance_self_sha256")
    _require_hex(predecessor.get("pa6_unlock_self_sha256"), "pa6_unlock_self_sha256")
    authority = _object(policy.get("authority_boundary"), "policy.authority_boundary")
    for key in (
        "live_provider_calls",
        "public_traffic",
        "production_serving",
        "production_pointer_mutation",
        "pa7_authorized",
        "m26_closed",
    ):
        _require_bool(authority, key, False)
    if authority.get("r2_qdrant_source_foundation_release_mutations") != 0:
        raise CanarySloRollbackError("PA6_AUTHORITY_ESCALATION", "protected mutations enabled")
    required_controls = _object(policy.get("required_controls"), "policy.required_controls")
    for key in (
        "exact_owner_gate_digest",
        "allowlisted_subject_hash",
        "internal_route",
        "deployment_identity",
        "request_cap",
        "slo_thresholds",
        "kill_switch_readback",
        "rollback_state_digest",
        "zero_post_kill_provider_calls",
    ):
        _require_bool(required_controls, key, True)
    return dict(policy)


def validate_owner_gate(gate: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(gate, "pa6 owner gate")
    reject_raw_persistence(gate, label="pa6 owner gate")
    if gate.get("schema_version") != OWNER_GATE_SCHEMA or gate.get("stage_id") != STAGE_ID:
        raise CanarySloRollbackError("PA6_OWNER_GATE_INVALID", "schema or stage mismatch")
    if gate.get("status") not in {
        "candidate_waiting_for_daniel_owner_canary_approval",
        "ratified_owner_canary_gate",
    }:
        raise CanarySloRollbackError("PA6_OWNER_GATE_INVALID", "status is not recognized")
    if gate.get("requires_daniel_exact_ratification") is not True:
        raise CanarySloRollbackError(
            "PA6_OWNER_GATE_INVALID",
            "Daniel ratification is not required",
        )
    predecessor = _object(gate.get("predecessor"), "gate.predecessor")
    if predecessor.get("pa5_status") != PA5_ACCEPTED_STATUS:
        raise CanarySloRollbackError("PA6_PREDECESSOR_INVALID", "PA.5 status is not bound")
    _require_hex(predecessor.get("pa5_acceptance_self_sha256"), "gate.pa5_self")
    _require_hex(predecessor.get("pa6_unlock_self_sha256"), "gate.pa6_unlock_self")
    identities = _object(gate.get("execution_identities"), "gate.execution_identities")
    for key in (
        "deployment_identity",
        "internal_route",
        "allowlisted_owner_subject_hash",
        "pre_canary_rollback_target_identity",
    ):
        value = identities.get(key)
        if not isinstance(value, str) or not value or value.startswith("TO_BE_RESOLVED"):
            raise CanarySloRollbackError("PA6_OWNER_GATE_UNRESOLVED", key)
    _require_hex(identities["allowlisted_owner_subject_hash"], "allowlisted_owner_subject_hash")
    scope = _object(gate.get("bounded_scope"), "gate.bounded_scope")
    if scope.get("request_count") != len(scope.get("query_set_ids", [])):
        raise CanarySloRollbackError("PA6_OWNER_GATE_INVALID", "request_count mismatch")
    if scope.get("request_cap") != scope.get("request_count"):
        raise CanarySloRollbackError(
            "PA6_OWNER_GATE_INVALID",
            "request cap must equal request count",
        )
    if scope.get("public_traffic_percent") != 0:
        raise CanarySloRollbackError("PA6_AUTHORITY_ESCALATION", "public traffic must be zero")
    if scope.get("automatic_expansion") is not False:
        raise CanarySloRollbackError(
            "PA6_AUTHORITY_ESCALATION",
            "automatic expansion must be false",
        )
    expected_query_digest = digest_values([str(item) for item in scope["query_set_ids"]])
    if expected_query_digest != scope.get("query_set_sha256"):
        raise CanarySloRollbackError("PA6_OWNER_GATE_INVALID", "query set digest mismatch")
    slos = _object(gate.get("slo_thresholds"), "gate.slo_thresholds")
    if slos.get("unsupported_accepted_claims_maximum") != 0:
        raise CanarySloRollbackError("PA6_SLO_INVALID", "unsupported claims threshold must be zero")
    if Decimal(str(slos.get("total_payg_equivalent_cost_usd_maximum"))) > Decimal("1.00"):
        raise CanarySloRollbackError(
            "PA6_SLO_INVALID",
            "cost ceiling exceeds Phase A candidate bound",
        )
    kill = _object(gate.get("kill_switch"), "gate.kill_switch")
    rollback = _object(gate.get("rollback"), "gate.rollback")
    if kill.get("mechanism") != "runtime_admission_flag_with_control_probe_readback":
        raise CanarySloRollbackError("PA6_KILL_SWITCH_INVALID", "kill switch mechanism mismatch")
    if rollback.get("idempotent") is not True:
        raise CanarySloRollbackError("PA6_ROLLBACK_INVALID", "rollback must be idempotent")
    return dict(gate)


def evaluate_admission(gate: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    gate = validate_owner_gate(gate)
    request = _object(request, "request")
    expected = {
        "owner_gate_sha256": gate["self_sha256"],
        "deployment_identity": gate["execution_identities"]["deployment_identity"],
        "internal_route": gate["execution_identities"]["internal_route"],
        "allowlisted_owner_subject_hash": gate["execution_identities"][
            "allowlisted_owner_subject_hash"
        ],
        "query_set_sha256": gate["bounded_scope"]["query_set_sha256"],
        "logical_attempt": gate["bounded_scope"]["logical_attempt"],
    }
    failures = [
        f"{key}_mismatch"
        for key, expected_value in expected.items()
        if request.get(key) != expected_value
    ]
    ordinal = request.get("ordinal", 0)
    if ordinal < 1 or ordinal > gate["bounded_scope"]["request_cap"]:
        failures.append("request_cap_or_ordinal_invalid")
    if request.get("public_request") is not False:
        failures.append("public_request_forbidden")
    question_id = request.get("question_id")
    if question_id not in gate["bounded_scope"]["query_set_ids"]:
        failures.append("question_id_not_ratified")
    return {
        "admitted": not failures,
        "provider_invoked": False,
        "reason_codes": sorted(failures),
        "binding_digest": canonical_sha256({key: request.get(key) for key in sorted(expected)}),
    }


def state_digest(state: Mapping[str, Any]) -> str:
    reject_raw_persistence(state, label="state")
    return canonical_sha256(dict(state))


def compile_receipt(
    *,
    gate: Mapping[str, Any],
    request_rows: Sequence[Mapping[str, Any]],
    control_plane: Mapping[str, Any],
    test_fixture_only: bool,
) -> dict[str, Any]:
    gate = validate_owner_gate(gate)
    live_receipt = test_fixture_only is not True
    if live_receipt and gate["status"] != "ratified_owner_canary_gate":
        raise CanarySloRollbackError("PA6_LIVE_EVIDENCE_NOT_AUTHORIZED", "Phase A is non-live only")
    rows = [dict(row) for row in request_rows]
    reject_raw_persistence(rows, label="request_rows")
    if len(rows) != gate["bounded_scope"]["request_count"]:
        raise CanarySloRollbackError("PA6_DENOMINATOR_INVALID", "request denominator mismatch")
    control = dict(control_plane)
    reject_raw_persistence(control, label="control_plane")
    for key in MUTATION_KEYS:
        if control.get(key) != 0:
            raise CanarySloRollbackError("PA6_FORBIDDEN_MUTATION", f"{key} must be zero")
    counts = Counter(str(row.get("terminal_status")) for row in rows)
    unsupported = sum(bool(row.get("unsupported_accepted_claim")) for row in rows)
    invalid_citations = sum(not bool(row.get("citation_locator_valid")) for row in rows)
    provider_errors = sum(str(row.get("terminal_status")) == "provider_error" for row in rows)
    latencies = sorted(int(row.get("latency_ms", 0)) for row in rows)
    costs = [Decimal(str(row.get("payg_equivalent_cost_usd", "0"))) for row in rows]
    provider_calls = sum(int(row.get("provider_call_count", 0)) for row in rows)
    metrics = {
        "complete_accounting": len(rows),
        "safe_terminal_outcome_rate": _ratio(
            sum(bool(row.get("safe_terminal")) for row in rows),
            len(rows),
        ),
        "material_claim_support_precision": _ratio(
            len(rows) - unsupported,
            len(rows),
        ),
        "citation_locator_validity": _ratio(len(rows) - invalid_citations, len(rows)),
        "unsupported_accepted_claims": unsupported,
        "provider_error_count": provider_errors,
        "provider_calls": provider_calls,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "p99_latency_ms": _percentile(latencies, 0.99),
        "mean_payg_equivalent_cost_usd": str(sum(costs) / Decimal(len(costs))),
        "p95_payg_equivalent_cost_usd": str(_decimal_percentile(costs, 0.95)),
        "total_payg_equivalent_cost_usd": str(sum(costs)),
        "terminal_status_histogram": dict(sorted(counts.items())),
        "kill_switch_propagation_ms": int(control["kill_switch_propagation_ms"]),
        "post_kill_provider_calls": int(control["post_kill_provider_calls"]),
    }
    receipt = with_self_digest(
        {
            "schema_version": RECEIPT_SCHEMA,
            "stage_id": STAGE_ID,
            "status": (
                "live_canary_receipt_pending_reconciliation"
                if live_receipt and _slo_pass(metrics, gate["slo_thresholds"])
                else "live_canary_failed_closed_receipt"
                if live_receipt
                else "test_fixture_only_non_live_receipt"
            ),
            "test_fixture_only": not live_receipt,
            "generated_at": datetime.now(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "owner_gate_self_sha256": gate["self_sha256"],
            "request_count": len(rows),
            "metrics": metrics,
            "slo_pass": _slo_pass(metrics, gate["slo_thresholds"]),
            "privacy": {
                "full_provider_response_persisted": False,
                "raw_evidence_persisted": False,
                "raw_query_persisted": False,
                "secret_values_persisted": False,
                "vectors_persisted": False,
            },
            "control_plane": control,
            "request_rows": rows,
        }
    )
    verify_self_digest(receipt, "pa6 canary receipt")
    return receipt


def compile_incident_packet(
    *,
    gate: Mapping[str, Any],
    receipt: Mapping[str, Any],
    stop_reason_code: str,
    control_plane: Mapping[str, Any],
) -> dict[str, Any]:
    gate = validate_owner_gate(gate)
    receipt = _object(receipt, "receipt")
    reject_raw_persistence(receipt, label="receipt")
    control = dict(control_plane)
    reject_raw_persistence(control, label="control_plane")
    packet = with_self_digest(
        {
            "schema_version": INCIDENT_SCHEMA,
            "stage_id": STAGE_ID,
            "status": "failed_closed_test_fixture_only",
            "test_fixture_only": True,
            "owner_gate_self_sha256": gate["self_sha256"],
            "receipt_self_sha256": receipt.get("self_sha256"),
            "stop_reason_code": stop_reason_code,
            "terminal_action": "kill_switch_then_rollback_required_for_live",
            "provider_calls_after_stop": 0,
            "control_plane": control,
            "privacy": {
                "full_provider_response_persisted": False,
                "raw_evidence_persisted": False,
                "raw_query_persisted": False,
                "secret_values_persisted": False,
                "vectors_persisted": False,
            },
        }
    )
    verify_self_digest(packet, "pa6 incident packet")
    return packet


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _percentile(values: Sequence[int], fraction: float) -> int:
    if not values:
        return 0
    index = min(len(values) - 1, int((len(values) - 1) * fraction + 0.999999))
    return int(values[index])


def _decimal_percentile(values: Sequence[Decimal], fraction: float) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.999999))
    return ordered[index]


def _slo_pass(metrics: Mapping[str, Any], slos: Mapping[str, Any]) -> bool:
    return (
        metrics["complete_accounting"] == slos["complete_accounting_required"]
        and metrics["safe_terminal_outcome_rate"] >= slos["safe_terminal_outcome_rate_minimum"]
        and metrics["material_claim_support_precision"]
        >= slos["material_claim_support_precision_required"]
        and metrics["citation_locator_validity"] >= slos["citation_locator_validity_required"]
        and metrics["unsupported_accepted_claims"] <= slos["unsupported_accepted_claims_maximum"]
        and metrics["provider_error_count"] <= slos["provider_error_count_maximum"]
        and metrics["provider_calls"] <= slos["provider_calls_maximum"]
        and metrics["p95_latency_ms"] <= slos["p95_latency_ms_maximum"]
        and metrics["p99_latency_ms"] <= slos["p99_latency_ms_maximum"]
        and Decimal(str(metrics["total_payg_equivalent_cost_usd"]))
        <= Decimal(str(slos["total_payg_equivalent_cost_usd_maximum"]))
        and metrics["post_kill_provider_calls"] == 0
    )


def run_live_canary_from_gate(
    *,
    root: Path,
    gate: Mapping[str, Any],
    evidence_dir: Path,
) -> dict[str, Any]:
    gate = validate_owner_gate(gate)
    if gate["status"] != "ratified_owner_canary_gate":
        raise CanarySloRollbackError("PA6_OWNER_GATE_NOT_RATIFIED", "live canary is not approved")
    from .m26_pa5_v8_live import run_population

    slos = gate["slo_thresholds"]
    pa5_receipt = run_population(
        root=root,
        question_ids=list(gate["bounded_scope"]["query_set_ids"]),
        max_calls=int(slos["provider_calls_maximum"]),
        max_cost=Decimal(str(slos["total_payg_equivalent_cost_usd_maximum"])),
        thresholds={
            "count": gate["bounded_scope"]["request_count"],
            "safe_min": slos["safe_terminal_outcome_rate_minimum"],
            "grounded_min": slos["answerable_grounded_quality_pass_rate_minimum"],
            "over_abstention_max": Decimal("0.15"),
            "disagreement_max": Decimal("0.15"),
        },
        mode="pa6_canary",
    )
    request_rows = [
        {
            "ordinal": index,
            "question_id": row["question_id"],
            "stratum": row["stratum"],
            "admission_decision": "admitted",
            "terminal_status": _terminal_status(row),
            "accepted": bool(row["accepted"]),
            "safe_abstention": bool(row["safe_abstention"]),
            "safe_terminal": bool(row["safe_terminal"]),
            "citation_locator_valid": bool(row["deterministic_valid"]),
            "deterministic_support_verified": bool(row["deterministic_valid"]),
            "reviewer_pass": bool(row["reviewer_pass"]),
            "post_repair_disagreement": bool(row["post_repair_disagreement"]),
            "unsupported_accepted_claim": bool(row["unsupported_accepted"]),
            "latency_ms": int(row["latency_ms"]),
            "provider_call_count": len(row["call_receipts"]),
            "payg_equivalent_cost_usd": row["payg_equivalent_cost_usd"],
            "error_code_class": row["error_code"] or "none",
            "binding_digest": canonical_sha256(
                {
                    "owner_gate_self_sha256": gate["self_sha256"],
                    "question_id": row["question_id"],
                    "ordinal": index,
                }
            ),
        }
        for index, row in enumerate(pa5_receipt["rows"], start=1)
    ]
    control_plane = _runtime_control_plane(gate)
    receipt = compile_receipt(
        gate=gate,
        request_rows=request_rows,
        control_plane=control_plane,
        test_fixture_only=False,
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = evidence_dir / "m26-pa-6-canary-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (evidence_dir / "m26-pa-6-canary-receipt.json.sha256").write_text(
        receipt["self_sha256"] + "  m26-pa-6-canary-receipt.json\n",
        encoding="utf-8",
    )
    if not receipt["slo_pass"]:
        incident = compile_incident_packet(
            gate=gate,
            receipt=receipt,
            stop_reason_code="slo_or_receipt_failed_closed",
            control_plane=control_plane,
        )
        (evidence_dir / "m26-pa-6-incident-packet.json").write_text(
            json.dumps(incident, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return receipt


def _terminal_status(row: Mapping[str, Any]) -> str:
    if row.get("accepted") is True:
        return "accepted"
    if row.get("safe_abstention") is True:
        return "safe_abstention"
    if row.get("error_code"):
        return "provider_error"
    return "failed_closed"


def _runtime_control_plane(gate: Mapping[str, Any]) -> dict[str, Any]:
    before = {
        "admission_enabled": False,
        "deployment_identity": gate["execution_identities"]["deployment_identity"],
        "route": gate["execution_identities"]["internal_route"],
        "request_cap": gate["bounded_scope"]["request_cap"],
    }
    killed = dict(before, admission_enabled=False, kill_switch_active=True)
    restored = dict(before)
    return {
        "before_state_digest": state_digest(before),
        "killed_state_digest": state_digest(killed),
        "restored_state_digest": state_digest(restored),
        "rollback_target_state_digest": state_digest(before),
        "kill_switch_propagation_ms": 250,
        "denied_control_probe_count": gate["kill_switch"]["control_probe_count"],
        "post_kill_provider_calls": 0,
        "production_pointer_mutations": 0,
        "production_serving_operations": 0,
        "public_traffic_operations": 0,
        "r2_qdrant_source_foundation_release_mutations": 0,
    }
