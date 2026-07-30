from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from knowledge_engine.m26_canary_slo_rollback import (
    CanarySloRollbackError,
    compile_incident_packet,
    compile_receipt,
    digest_values,
    evaluate_admission,
    state_digest,
    validate_canary_policy,
    validate_owner_gate,
    validate_predecessors,
)
from knowledge_engine.m26_verified_answer_citation_gate import (
    canonical_sha256,
    verify_self_digest,
    with_self_digest,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-6-canary-slo-rollback.yml"

PA5_SELF_SHA256 = "f2943641f2ccc22ca4d39e34a1e47e46798a1dc95ee6d5cb98aa0c3eaf1506eb"
PA6_UNLOCK_SELF_SHA256 = (
    "385c1de7e046be0f317eb162f61ff35a809a6c3ac3a1282cf0fab6366ca669a2"
)
STALE_PACKAGE_PA6_UNLOCK_SELF_SHA256 = (
    "6a14dd3f648779832f12484e14eb6a006515701568d91fae6c09eaf8e2327434"
)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def schema_errors(schema_name: str, value: dict[str, Any]) -> list[str]:
    schema = load(SCHEMAS / schema_name)
    Draft202012Validator.check_schema(schema)
    return [
        error.message
        for error in sorted(
            Draft202012Validator(schema).iter_errors(value),
            key=lambda item: list(item.absolute_path),
        )
    ]


def query_ids() -> list[str]:
    packet = load(PILOT / "m26-pa-5-v8-owner-oversight-packet.json")
    return [str(item["question_id"]) for item in packet["items"]]


def owner_gate_candidate() -> dict[str, Any]:
    policy = load(PILOT / "m26-pa-6-canary-policy.json")
    queries = query_ids()
    rollback_state = {
        "admission_enabled": False,
        "deployment_identity": "github-main-d1b06bf6-pa6-admission-config",
        "internal_route": "internal://knowledge-engine/m26/pa6/canary/owner-allowlisted",
        "public_traffic_percent": 0,
        "request_cap": 20,
    }
    return with_self_digest(
        {
            "schema_version": "knowledge-engine-m26-pa-6-owner-gate/v1",
            "stage_id": "M26.PA.6",
            "status": "candidate_waiting_for_daniel_owner_canary_approval",
            "requires_daniel_exact_ratification": True,
            "predecessor": {
                "pa5_status": policy["predecessor"]["pa5_status"],
                "pa5_acceptance_self_sha256": policy["predecessor"][
                    "pa5_acceptance_self_sha256"
                ],
                "pa6_unlock_status": policy["predecessor"]["pa6_unlock_status"],
                "pa6_unlock_self_sha256": policy["predecessor"][
                    "pa6_unlock_self_sha256"
                ],
            },
            "implementation": {
                "issue": 1243,
                "pull_request": 999999,
                "head_sha": "1" * 40,
                "merge_sha": "2" * 40,
            },
            "execution_identities": {
                "deployment_identity": rollback_state["deployment_identity"],
                "internal_route": rollback_state["internal_route"],
                "allowlisted_owner_subject_hash": canonical_sha256("daniel-huang"),
                "pre_canary_rollback_target_identity": (
                    "state-digest:" + state_digest(rollback_state)
                ),
            },
            "bounded_scope": {
                "logical_attempt": 1,
                "request_count": 20,
                "request_cap": 20,
                "duration_minutes_max": 30,
                "public_traffic_percent": 0,
                "automatic_expansion": False,
                "query_set_source": "PA.5 sanitized owner oversight packet question IDs only",
                "query_set_sha256": digest_values(queries),
                "query_set_ids": queries,
            },
            "slo_thresholds": {
                "complete_accounting_required": 20,
                "safe_terminal_outcome_rate_minimum": 1.0,
                "answerable_grounded_quality_pass_rate_minimum": 0.85,
                "appropriate_abstention_recall_minimum": 0.95,
                "material_claim_support_precision_required": 1.0,
                "citation_locator_validity_required": 1.0,
                "unsupported_accepted_claims_maximum": 0,
                "provider_error_count_maximum": 0,
                "provider_calls_maximum": 80,
                "p95_latency_ms_maximum": 30000,
                "p99_latency_ms_maximum": 60000,
                "mean_payg_equivalent_cost_usd_maximum": "0.05",
                "p95_payg_equivalent_cost_usd_maximum": "0.10",
                "total_payg_equivalent_cost_usd_maximum": "1.00",
                "unresolved_disagreements_maximum": 0,
            },
            "stop_conditions": [
                "non_allowlisted_identity_or_route_admitted",
                "public_request_reaches_canary",
                "deployment_route_gate_sample_or_rollback_identity_drift",
                "unsupported_accepted_claim_or_invalid_citation_locator",
                "unresolved_reviewer_disagreement",
                "acl_privacy_injection_secret_or_raw_persistence_incident",
                "provider_error_in_canary",
                "request_latency_above_60000_ms",
                "p95_latency_above_30000_ms_after_10_terminal_rows",
                "provider_call_or_cost_budget_projected_exceeded",
                "telemetry_denominator_or_receipt_validation_gap",
                "kill_switch_fails_to_stop_admission_or_provider_calls",
                "rollback_cannot_restore_exact_pre_canary_identity",
            ],
            "kill_switch": {
                "mechanism": "runtime_admission_flag_with_control_probe_readback",
                "control_probe_count": 2,
                "requires_zero_post_kill_provider_calls": True,
            },
            "rollback": {
                "mechanism": "restore_pre_canary_admission_config_digest",
                "target_state_digest": state_digest(rollback_state),
                "idempotent": True,
                "post_restore_smoke_required": True,
            },
            "denied": {
                "public_traffic": True,
                "production_serving": True,
                "production_pointer_mutation": True,
                "r2_qdrant_source_foundation_release_mutation": True,
                "pa7": True,
                "m26_closure": True,
            },
            "self_sha256": "",
        }
    )


def successful_rows(gate: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "ordinal": index,
            "question_id": question_id,
            "stratum": question_id.removeprefix("m26-pa5-").rsplit("-", 1)[0],
            "admission_decision": "admitted",
            "terminal_status": "accepted" if "abstention" not in question_id else "safe_abstention",
            "accepted": "abstention" not in question_id,
            "safe_abstention": "abstention" in question_id,
            "safe_terminal": True,
            "citation_locator_valid": True,
            "deterministic_support_verified": True,
            "reviewer_pass": True,
            "post_repair_disagreement": False,
            "unsupported_accepted_claim": False,
            "latency_ms": 1200 + index,
            "provider_call_count": 2,
            "payg_equivalent_cost_usd": "0.0004",
            "error_code_class": "none",
            "binding_digest": canonical_sha256(
                {
                    "owner_gate_self_sha256": gate["self_sha256"],
                    "question_id": question_id,
                    "ordinal": index,
                }
            ),
        }
        for index, question_id in enumerate(gate["bounded_scope"]["query_set_ids"], start=1)
    ]


def control_plane(gate: dict[str, Any]) -> dict[str, Any]:
    before = {
        "admission_enabled": False,
        "deployment_identity": gate["execution_identities"]["deployment_identity"],
        "route": gate["execution_identities"]["internal_route"],
        "request_cap": 20,
    }
    killed = dict(before, admission_enabled=False, kill_switch_active=True)
    restored = dict(before)
    return {
        "before_state_digest": state_digest(before),
        "killed_state_digest": state_digest(killed),
        "restored_state_digest": state_digest(restored),
        "rollback_target_state_digest": state_digest(before),
        "kill_switch_propagation_ms": 250,
        "denied_control_probe_count": 2,
        "post_kill_provider_calls": 0,
        "production_pointer_mutations": 0,
        "production_serving_operations": 0,
        "public_traffic_operations": 0,
        "r2_qdrant_source_foundation_release_mutations": 0,
    }


def test_pa6_predecessors_bind_current_corrected_main_not_stale_package_snapshot() -> None:
    pa5 = load(PILOT / "m26-pa-5-v8-acceptance.json")
    unlock = load(PILOT / "m26-pa-6-unlock-pending-owner-canary-approval.json")
    result = validate_predecessors(pa5, unlock)
    assert result == {
        "pa5_acceptance_self_sha256": PA5_SELF_SHA256,
        "pa6_unlock_self_sha256": PA6_UNLOCK_SELF_SHA256,
    }
    assert unlock["self_sha256"] != STALE_PACKAGE_PA6_UNLOCK_SELF_SHA256


def test_pa6_policy_schema_self_digest_and_forbidden_boundaries() -> None:
    policy = load(PILOT / "m26-pa-6-canary-policy.json")
    assert schema_errors("m26-pa-6-canary-policy-v1.schema.json", policy) == []
    verify_self_digest(policy, "policy")
    assert validate_canary_policy(policy)["self_sha256"] == policy["self_sha256"]
    assert policy["package_drift_correction"] == {
        "current_main_pa6_unlock_self_sha256": PA6_UNLOCK_SELF_SHA256,
        "stale_package_pa6_unlock_self_sha256": STALE_PACKAGE_PA6_UNLOCK_SELF_SHA256,
    }
    assert not policy["authority_boundary"]["live_provider_calls"]
    assert not policy["authority_boundary"]["public_traffic"]
    assert not policy["authority_boundary"]["production_pointer_mutation"]


def test_pa6_owner_gate_candidate_schema_self_digest_and_query_digest() -> None:
    gate = owner_gate_candidate()
    assert schema_errors("m26-pa-6-owner-gate-v1.schema.json", gate) == []
    assert validate_owner_gate(gate)["self_sha256"] == gate["self_sha256"]
    assert gate["bounded_scope"]["query_set_sha256"] == digest_values(query_ids())
    assert "TO_BE_RESOLVED" not in json.dumps(gate, sort_keys=True)


def test_pa6_owner_gate_template_is_not_approval_or_live_evidence() -> None:
    template = load(PILOT / "m26-pa-6-owner-gate-template.json")
    verify_self_digest(template, "owner gate template")
    assert template["status"] == "template_not_approved_not_live_evidence"
    assert template["status_boundary"] == {
        "acceptance_authorized": False,
        "deployment_or_route_mutation_authorized": False,
        "live_canary_authorized": False,
        "provider_calls_authorized": False,
    }
    with pytest.raises(CanarySloRollbackError, match="PA6_OWNER_GATE_INVALID"):
        validate_owner_gate(template)


def test_pa6_admission_rejects_moved_tuple_before_provider_invocation() -> None:
    gate = owner_gate_candidate()
    request = {
        "owner_gate_sha256": gate["self_sha256"],
        "deployment_identity": gate["execution_identities"]["deployment_identity"],
        "internal_route": gate["execution_identities"]["internal_route"],
        "allowlisted_owner_subject_hash": gate["execution_identities"][
            "allowlisted_owner_subject_hash"
        ],
        "query_set_sha256": gate["bounded_scope"]["query_set_sha256"],
        "logical_attempt": 1,
        "ordinal": 1,
        "question_id": gate["bounded_scope"]["query_set_ids"][0],
        "public_request": False,
    }
    assert evaluate_admission(gate, request)["admitted"] is True

    moved = dict(request, internal_route="https://public.example.invalid/ask")
    result = evaluate_admission(gate, moved)
    assert result["admitted"] is False
    assert result["provider_invoked"] is False
    assert result["reason_codes"] == ["internal_route_mismatch"]


def test_pa6_non_live_receipt_schema_slo_and_no_raw_persistence() -> None:
    gate = owner_gate_candidate()
    receipt = compile_receipt(
        gate=gate,
        request_rows=successful_rows(gate),
        control_plane=control_plane(gate),
        test_fixture_only=True,
    )
    assert schema_errors("m26-pa-6-canary-receipt-v1.schema.json", receipt) == []
    assert receipt["test_fixture_only"] is True
    assert receipt["slo_pass"] is True
    assert receipt["metrics"]["complete_accounting"] == 20
    assert receipt["metrics"]["provider_calls"] == 40
    assert receipt["metrics"]["post_kill_provider_calls"] == 0
    assert receipt["privacy"]["raw_query_persisted"] is False


def test_pa6_incident_packet_preserves_fail_closed_boundary() -> None:
    gate = owner_gate_candidate()
    rows = successful_rows(gate)
    rows[0] = dict(rows[0], unsupported_accepted_claim=True)
    receipt = compile_receipt(
        gate=gate,
        request_rows=rows,
        control_plane=control_plane(gate),
        test_fixture_only=True,
    )
    assert receipt["slo_pass"] is False
    packet = compile_incident_packet(
        gate=gate,
        receipt=receipt,
        stop_reason_code="unsupported_accepted_claim_or_invalid_citation_locator",
        control_plane=control_plane(gate),
    )
    assert schema_errors("m26-pa-6-incident-packet-v1.schema.json", packet) == []
    assert packet["status"] == "failed_closed_test_fixture_only"
    assert packet["provider_calls_after_stop"] == 0


def test_pa6_rejects_live_receipt_and_forbidden_mutation_in_phase_a() -> None:
    gate = owner_gate_candidate()
    with pytest.raises(CanarySloRollbackError, match="PA6_LIVE_EVIDENCE_NOT_AUTHORIZED"):
        compile_receipt(
            gate=gate,
            request_rows=successful_rows(gate),
            control_plane=control_plane(gate),
            test_fixture_only=False,
        )
    mutated = copy.deepcopy(control_plane(gate))
    mutated["production_pointer_mutations"] = 1
    with pytest.raises(CanarySloRollbackError, match="PA6_FORBIDDEN_MUTATION"):
        compile_receipt(
            gate=gate,
            request_rows=successful_rows(gate),
            control_plane=mutated,
            test_fixture_only=True,
        )


def test_pa6_workflow_keeps_live_job_authorization_gated() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "live_canary:" in workflow
    assert "pilot/m26/m26-pa-6-owner-gate-authorized.json" in workflow
    assert "m26-pa-6-canary-policy.json" in workflow
    assert "tests/test_m26_pa_6_canary_slo_rollback.py" in workflow
    static_job = workflow.split("  static_validate:", 1)[1].split("  live_canary:", 1)[0]
    assert "secrets." not in static_job
    assert "environment: m23-r3-diagnostic" not in static_job
