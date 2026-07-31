from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from knowledge_engine.m26_production_promotion_closure import (
    OWNER_DECISION_SELF_SHA256,
    ProductionPromotionClosureError,
    build_resolved_gate,
    compile_incident_packet,
    compile_owner_query_response,
    compile_production_receipt,
    evaluate_owner_admission,
    fixture_request_rows,
    promotion_state_evidence,
    validate_current_predecessors,
    validate_owner_final_decision,
    validate_resolved_gate,
    verify_self_digest,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-7-production-promotion-closure.yml"

PA6_ACCEPTANCE_SELF_SHA256 = (
    "758f2c8012d37875f7438c1d518f9d9db55e3ce0344640f0e16c9ed8f3fa7144"
)
PA7_UNLOCK_SELF_SHA256 = (
    "c1984a9d69518958cc6830d34762444263f990b118a8c6a914e480a15c491538"
)
OWNER_SUBJECT_HASH = "93c8aaae82e498dc2e6bfdcaa48b8823fe21a5ceef44ca2cf9cf35cf6350e05b"


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


def owner_decision() -> dict[str, Any]:
    return {
        "conditions": [
            "Production traffic remains restricted to Daniel owner allowlist.",
            "Public and unbounded traffic remain zero.",
            (
                "The target must be the PA.6 accepted runtime or a direct descendant "
                "containing only PA.7 control-plane and closure changes."
            ),
            (
                "Capture immutable pre-state, promotion state, rollback state, restored "
                "final state, and canonical digests."
            ),
            "No answer-to-canonical writes or corpus/index/content mutations.",
            "No secret values in Git, logs, prompts, artifacts, or handoffs.",
            (
                "Acceptance and M26 closure become effective only after an independent "
                "reconciliation PR merges and current main verifies."
            ),
            (
                "Security, privacy, integrity, identity, or evidence ambiguity must fail "
                "closed rather than be repaired through weakened gates."
            ),
        ],
        "decision_maker": "Daniel Huang",
        "decision_status": "approved_with_conditions",
        "decision_timestamp_local": "2026-07-31T04:11:00+08:00",
        "delegated_exact_identity_resolution": True,
        "exact_instruction_text": (
            "給我給codex的交接包 我要去睡覺了 我希望一覺醒來看到pa7 / m26都好了\n"
            "要什麼權限和authority我一次給 gh指令也全授權 不要中間停下來跟我要權限或是同意"
        ),
        "github_authority": {
            "actions_execution_and_inspection": True,
            "expected_head_merges": True,
            "git_and_gh_commands": True,
            "issues_branches_commits_prs": True,
            "ordinary_ci_repairs_without_reapproval": True,
        },
        "live_budgets": {
            "maximum_cumulative_payg_equivalent_cost_usd": "2.00",
            "maximum_cumulative_provider_calls": 160,
            "maximum_cumulative_window_minutes": 90,
            "maximum_logical_promotion_attempts": 2,
            "maximum_production_smoke_requests_per_attempt": 20,
        },
        "mission": (
            "Complete PA.7 and M26 closure autonomously without intermediate owner approval."
        ),
        "predecessor": {
            "main_ancestry_anchor": "cdef87f304150225fc47fab0df003500386d2534",
            "pa6_acceptance_self_sha256": PA6_ACCEPTANCE_SELF_SHA256,
            "pa6_status": "m26_pa_6_canary_slo_rollback_accepted",
            "pa7_unlock_self_sha256": PA7_UNLOCK_SELF_SHA256,
            "pa7_unlock_status": "m26_pa_7_unlocked_pending_owner_promotion",
        },
        "production_authority": {
            "automatic_expansion": False,
            "bounded_production_promotion": True,
            "final_m26_closure_after_reconciliation": True,
            "owner_only_answer_serving": True,
            "production_pointer_or_route_mutation": True,
            "public_or_unbounded_traffic": False,
            "rollback_and_restoration": True,
        },
        "schema_version": "knowledge-engine-m26-pa-7-owner-final-decision/v1",
        "self_sha256": OWNER_DECISION_SELF_SHA256,
        "stage_id": "M26.PA.7",
    }


def query_ids() -> list[str]:
    packet = load(PILOT / "m26-pa-5-v8-owner-oversight-packet.json")
    return [str(item["question_id"]) for item in packet["items"]]


def production_identities() -> dict[str, Any]:
    return {
        "access_policy_digest": "owner-only-access:" + ("a" * 64),
        "allowlisted_owner_subject_hash": OWNER_SUBJECT_HASH,
        "automatic_expansion": False,
        "deployment_identity": "github-actions-main-pa7-owner-production",
        "final_production_pointer_target": "runtime-pointer:m26-pa7-owner-only-final",
        "immutable_rollback_target_identity": "runtime-pointer:m26-pa6-safe-prestate",
        "model_identity": "MiniMax-M3",
        "owner_only_route": "command://knowledge-m26-pa7-query",
        "pre_production_pointer_identity": "runtime-pointer:m26-pa6-safe-prestate",
        "provider_identity": "MiniMax / MiniMax-M3",
        "public_traffic_percent": 0,
        "runtime_build_sha": "1" * 40,
    }


def implementation_identity() -> dict[str, Any]:
    return {
        "base_sha": "cdef87f304150225fc47fab0df003500386d2534",
        "expected_head_merge": True,
        "head_sha": "2" * 40,
        "implementation_issue": 1251,
        "implementation_pull_request": 1252,
        "merge_sha": "3" * 40,
    }


def workflow_identity() -> dict[str, Any]:
    return {
        "name": "M26.PA.7 Production Promotion and Closure",
        "path": ".github/workflows/m26-pa-7-production-promotion-closure.yml",
        "trigger_artifact": "pilot/m26/m26-pa-7-promotion-trigger.json",
    }


def resolved_gate() -> dict[str, Any]:
    return build_resolved_gate(
        owner_decision=owner_decision(),
        implementation=implementation_identity(),
        production_identities=production_identities(),
        query_set_ids=query_ids(),
        workflow=workflow_identity(),
    )


def test_owner_decision_schema_and_canonical_digest() -> None:
    decision = owner_decision()
    assert schema_errors("m26-pa-7-owner-final-decision-v1.schema.json", decision) == []
    assert validate_owner_final_decision(decision)["self_sha256"] == OWNER_DECISION_SELF_SHA256

    weakened = copy.deepcopy(decision)
    weakened["production_authority"]["public_or_unbounded_traffic"] = True
    weakened.pop("self_sha256")
    from knowledge_engine.m26_retrieval_envelope import with_self_digest

    weakened = with_self_digest(weakened)
    with pytest.raises(ProductionPromotionClosureError, match="PA7_OWNER_DECISION_MISMATCH"):
        validate_owner_final_decision(weakened)


def test_current_main_predecessors_are_ready_for_pa7() -> None:
    assert validate_current_predecessors(ROOT) == {
        "pa6_acceptance_self_sha256": PA6_ACCEPTANCE_SELF_SHA256,
        "pa7_unlock_self_sha256": PA7_UNLOCK_SELF_SHA256,
    }


def test_resolved_gate_schema_self_digest_and_admission() -> None:
    gate = resolved_gate()
    assert schema_errors("m26-pa-7-resolved-production-gate-v1.schema.json", gate) == []
    verify_self_digest(gate, "gate")
    assert validate_resolved_gate(gate, owner_decision())["self_sha256"] == gate["self_sha256"]

    admitted = evaluate_owner_admission(
        gate,
        {
            "owner_only_route": "command://knowledge-m26-pa7-query",
            "owner_subject_hash": OWNER_SUBJECT_HASH,
            "public_request": False,
            "resolved_gate_self_sha256": gate["self_sha256"],
        },
    )
    assert admitted["admitted"] is True
    assert admitted["provider_invoked"] is False

    denied = evaluate_owner_admission(
        gate,
        {
            "owner_only_route": "command://knowledge-m26-pa7-query",
            "owner_subject_hash": "0" * 64,
            "public_request": False,
            "resolved_gate_self_sha256": gate["self_sha256"],
        },
    )
    assert denied["admitted"] is False
    assert denied["provider_invoked"] is False


def test_owner_query_surface_returns_cited_answer_or_denial() -> None:
    gate = resolved_gate()
    response = compile_owner_query_response(
        gate,
        question="What is the M26 PA7 production authority status?",
        owner_subject_hash=OWNER_SUBJECT_HASH,
    )
    assert response["status"] == "owner_only_cited_answer"
    assert response["answer_text"]
    assert response["citations"]
    assert response["provider_invoked"] is False

    denied = compile_owner_query_response(
        gate,
        question="What is the M26 PA7 production authority status?",
        owner_subject_hash=OWNER_SUBJECT_HASH,
        public_request=True,
    )
    assert denied["status"] == "denied_non_owner_or_public_request"
    assert denied["terminal_status"] == "denied_before_provider"
    assert denied["provider_invoked"] is False


def test_production_receipt_fixture_schema_slo_and_incident_packet() -> None:
    gate = resolved_gate()
    owner_query = compile_owner_query_response(
        gate,
        question="What is the M26 PA7 production authority status?",
        owner_subject_hash=OWNER_SUBJECT_HASH,
    )
    receipt = compile_production_receipt(
        gate=gate,
        request_rows=fixture_request_rows(gate),
        state=promotion_state_evidence(gate),
        owner_query_response=owner_query,
        test_fixture_only=True,
    )
    assert schema_errors("m26-pa-7-production-receipt-v1.schema.json", receipt) == []
    verify_self_digest(receipt, "receipt")
    assert receipt["status"] == "test_fixture_only_non_live_production_receipt"
    assert receipt["slo_pass"] is True
    assert receipt["metrics"]["complete_accounting"] == 20
    assert receipt["traffic"] == {
        "non_owner_denied_probes": 2,
        "owner_requests": 20,
        "public_traffic_operations": 0,
    }
    assert receipt["mutations"]["corpus_index_content_mutations"] == 0
    assert receipt["state"]["rollback_equals_before"] is True
    assert receipt["privacy"]["secret_values_persisted"] is False

    incident = compile_incident_packet(
        gate=gate,
        receipt=receipt,
        stop_reason_code="fixture_stop_line",
    )
    assert schema_errors("m26-pa-7-incident-packet-v1.schema.json", incident) == []
    assert incident["provider_calls_after_stop"] == 0


def test_pa7_workflow_is_non_live_on_pull_requests_and_gate_triggered_on_main() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "pull_request:" in workflow
    assert "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
    assert "pilot/m26/m26-pa-7-promotion-trigger.json" in workflow
    assert "pilot/m26/m26-pa-7-resolved-production-gate.json" in workflow
    assert "pilot/m26/m26-pa-7-owner-final-decision.json" in workflow
    assert "PA.7 acceptance already reconciled" in workflow
    assert "MINIMAX_API_KEY" in workflow
