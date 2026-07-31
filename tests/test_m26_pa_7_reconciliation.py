from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from knowledge_engine.m26_production_promotion_closure import (
    OWNER_DECISION_SELF_SHA256,
    validate_owner_final_decision,
    validate_promotion_trigger,
    validate_resolved_gate,
    verify_self_digest,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
RECONCILIATION_WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-7-reconciliation.yml"
PROMOTION_WORKFLOW = (
    ROOT / ".github" / "workflows" / "m26-pa-7-production-promotion-closure.yml"
)

ACCEPTED_STATUS = "m26_pa_7_production_answer_authority_and_closure_accepted"
CLOSURE_STATUS = "m26_closed"
PA6_ACCEPTANCE_SELF_SHA256 = (
    "758f2c8012d37875f7438c1d518f9d9db55e3ce0344640f0e16c9ed8f3fa7144"
)
PA7_UNLOCK_SELF_SHA256 = (
    "c1984a9d69518958cc6830d34762444263f990b118a8c6a914e480a15c491538"
)
RESOLVED_GATE_SELF_SHA256 = (
    "6adf0f4fa53d0b061f9e587b72e99ce38de2805f8b35b23841d5a63e44d9af5b"
)
PROMOTION_TRIGGER_SELF_SHA256 = (
    "6ae1c5f86783634e10ad319c36e5aef8cbb4dc0ee5ff6fc1c780f53063f84902"
)
LIVE_RUN_ID = 30602658208
LIVE_ARTIFACT_ID = 8782491199
LIVE_ARTIFACT_DIGEST = "sha256:d24468d77a9603a41a2cfed3e18d4f454625bd444afc284ec736f59cce54c7cb"
LIVE_RECEIPT_FILE_SHA256 = (
    "1e950799e7a67b3a403b9dd64ba97d9e8d5c59f7a7fe22a9c35d53f15bb67f17"
)
LIVE_RECEIPT_SELF_SHA256 = (
    "4cdbd4fd73f467d33dd54258b185af9b59512b1960e19e86f5e3aa56d3fc38be"
)
PROMOTION_HEAD_SHA = "eff049ca8e3061091291efd2194774c91c84121c"
PROMOTION_MERGE_SHA = "168a403ea5ff69c362009d58382743ad6986850c"
IMPLEMENTATION_HEAD_SHA = "2f3011cc112b9a8b4de587bc937e8ca5dae8540b"
IMPLEMENTATION_MERGE_SHA = "d1fbb9492a789b44b894c64654b7495b2b992f75"


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


def test_pa7_acceptance_schema_self_digest_and_live_evidence() -> None:
    acceptance = load(PILOT / "m26-pa-7-acceptance.json")
    assert schema_errors("m26-pa-7-acceptance-v1.schema.json", acceptance) == []
    verify_self_digest(acceptance, "pa7 acceptance")
    assert acceptance["accepted"] is True
    assert acceptance["status"] == ACCEPTED_STATUS
    assert acceptance["stage_id"] == "M26.PA.7"
    assert acceptance["owner_decision"]["self_sha256"] == OWNER_DECISION_SELF_SHA256
    assert acceptance["resolved_gate"]["self_sha256"] == RESOLVED_GATE_SELF_SHA256
    assert acceptance["promotion_trigger"]["self_sha256"] == PROMOTION_TRIGGER_SELF_SHA256

    evidence = acceptance["live_evidence"]
    assert evidence["run_id"] == LIVE_RUN_ID
    assert evidence["artifact_id"] == LIVE_ARTIFACT_ID
    assert evidence["artifact_archive_digest"] == LIVE_ARTIFACT_DIGEST
    assert evidence["receipt_file_sha256"] == LIVE_RECEIPT_FILE_SHA256
    assert evidence["receipt_self_sha256"] == LIVE_RECEIPT_SELF_SHA256
    assert evidence["receipt_status"] == "live_production_receipt_pending_reconciliation"
    assert evidence["slo_pass"] is True
    assert evidence["metrics"]["complete_accounting"] == 20
    assert evidence["metrics"]["provider_calls"] == 40
    assert evidence["traffic"]["public_traffic_operations"] == 0
    assert evidence["mutations"]["corpus_index_content_mutations"] == 0
    assert evidence["privacy"]["secret_values_persisted"] is False
    assert evidence["workflow_head_sha"] == PROMOTION_MERGE_SHA
    assert evidence["production_promotion_job_id"] == 91068521832


def test_pa7_acceptance_binds_predecessors_implementation_and_artifacts() -> None:
    acceptance = load(PILOT / "m26-pa-7-acceptance.json")
    decision = load(PILOT / "m26-pa-7-owner-final-decision.json")
    gate = load(PILOT / "m26-pa-7-resolved-production-gate.json")
    trigger = load(PILOT / "m26-pa-7-promotion-trigger.json")

    assert validate_owner_final_decision(decision)["self_sha256"] == OWNER_DECISION_SELF_SHA256
    assert validate_resolved_gate(gate, decision)["self_sha256"] == RESOLVED_GATE_SELF_SHA256
    assert validate_promotion_trigger(trigger, gate, decision)["self_sha256"] == (
        PROMOTION_TRIGGER_SELF_SHA256
    )
    assert acceptance["predecessor"] == {
        "pa6_acceptance_path": "pilot/m26/m26-pa-6-acceptance.json",
        "pa6_acceptance_self_sha256": PA6_ACCEPTANCE_SELF_SHA256,
        "pa6_status": "m26_pa_6_canary_slo_rollback_accepted",
        "pa7_unlock_path": "pilot/m26/m26-pa-7-unlock-pending-owner-promotion.json",
        "pa7_unlock_self_sha256": PA7_UNLOCK_SELF_SHA256,
        "pa7_unlock_status": "m26_pa_7_unlocked_pending_owner_promotion",
    }
    assert acceptance["implementation"] == {
        "pr_a": {
            "base_sha": "cdef87f304150225fc47fab0df003500386d2534",
            "head_sha": IMPLEMENTATION_HEAD_SHA,
            "issue": 1251,
            "merge_sha": IMPLEMENTATION_MERGE_SHA,
            "pull_request": 1252,
        },
        "pr_b": {
            "base_sha": IMPLEMENTATION_MERGE_SHA,
            "head_sha": PROMOTION_HEAD_SHA,
            "issue": 1253,
            "merge_sha": PROMOTION_MERGE_SHA,
            "pull_request": 1254,
        },
    }


def test_m26_closure_schema_self_digest_and_final_state() -> None:
    acceptance = load(PILOT / "m26-pa-7-acceptance.json")
    closure = load(PILOT / "m26-pa-7-m26-closure.json")
    assert schema_errors("m26-pa-7-m26-closure-v1.schema.json", closure) == []
    verify_self_digest(closure, "m26 closure")
    assert closure["status"] == CLOSURE_STATUS
    assert closure["m26_closed"] is True
    assert closure["acceptance_self_sha256"] == acceptance["self_sha256"]
    assert closure["final_state"] == {
        "M26.PA.7": ACCEPTED_STATUS,
        "M26_CLOSED": True,
        "PRODUCTION_ANSWER_SERVING": True,
        "PRODUCTION_AUDIENCE": "Daniel owner allowlist only",
        "PUBLIC_OR_UNBOUNDED_TRAFFIC": False,
    }
    assert closure["final_denied_boundaries"] == {
        "answer_to_canonical_writes": False,
        "automatic_expansion": False,
        "corpus_index_content_mutation": False,
        "new_user_admission": False,
        "public_or_unbounded_traffic": False,
        "secret_persistence": False,
    }


def test_pa7_reconciliation_workflow_is_read_only_and_remote_verifying() -> None:
    workflow = RECONCILIATION_WORKFLOW.read_text(encoding="utf-8")
    expected_permissions = (
        "permissions:\n"
        "  contents: read\n"
        "  actions: read\n"
        "  issues: read\n"
        "  pull-requests: read"
    )
    assert expected_permissions in workflow
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert "MINIMAX_API_KEY" not in workflow
    assert "Verify remote PA.7 live production evidence" in workflow
    assert str(LIVE_RUN_ID) in workflow
    assert str(LIVE_ARTIFACT_ID) in workflow
    assert "m26-pa-7-production-receipt.json" in workflow

    promotion_workflow = PROMOTION_WORKFLOW.read_text(encoding="utf-8")
    assert "pilot/m26/m26-pa-7-acceptance.json" in promotion_workflow
    assert "PA.7 acceptance already reconciled" in promotion_workflow
    assert "steps.pa7_gate.outputs.authorized == 'true'" in promotion_workflow
