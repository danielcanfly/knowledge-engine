from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from knowledge_engine.m26_production_promotion_closure import (
    CORRECTIVE_FORMAL_TEST_CONTRACT_SELF_SHA256,
    CORRECTIVE_OWNER_AUTHORITY_SELF_SHA256,
    CORRECTIVE_REOPEN_SELF_SHA256,
    OWNER_DECISION_SELF_SHA256,
    validate_corrective_formal_test_manifest,
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

ACCEPTED_STATUS = "m26_pa_7_arbitrary_owner_query_product_readiness_accepted"
CLOSURE_STATUS = "m26_closed"
OLD_ACCEPTANCE_SELF_SHA256 = (
    "c3936e3a4d9f93b398053e3d92294eeb520f2adbaac4b1481896a2c6a1a6afc1"
)
OLD_CLOSURE_SELF_SHA256 = (
    "c68d4fe433856cebfebf7a952b4915d460ddbc71c980baf88d462a39530c690c"
)
PA6_ACCEPTANCE_SELF_SHA256 = (
    "758f2c8012d37875f7438c1d518f9d9db55e3ce0344640f0e16c9ed8f3fa7144"
)
PA7_UNLOCK_SELF_SHA256 = (
    "c1984a9d69518958cc6830d34762444263f990b118a8c6a914e480a15c491538"
)
FORMAL_MANIFEST_SELF_SHA256 = (
    "62c14a4076238fd9f6c7424f5eccd555248616866caac5f2ea293bf1e6e073b9"
)
CORRECTED_GATE_SELF_SHA256 = (
    "667874a2e2873ac7847371b156906c256fab479c494214438b3cf79ca65274c6"
)
CORRECTED_TRIGGER_SELF_SHA256 = (
    "c278f66e434290eb4f8cd834588fb4e4b315a0368ad55b90a148e33e2521162e"
)
ACCEPTANCE_SELF_SHA256 = (
    "5358898627ededadd825af8794b27ee8be40d1bb5fb9ffd47e403c89909910ba"
)
CLOSURE_SELF_SHA256 = "8557ee70c9693634c20e353bfd82a64088346369ef0a7eba39e4f044d82319f3"
PR_A_HEAD_SHA = "3d965192242406c2af721a2ffe27e394d624e099"
PR_A_MERGE_SHA = "23413d9336a958fb5915068bc2e5a1ea34f28f57"
PR_B_HEAD_SHA = "c1e8b4125b8976f7696d26c8822244e353ab59c6"
PR_B_MERGE_SHA = "7eb1629dad9228da967989c975cb6a6a900a42c1"
PR_B_REPAIR_HEAD_SHA = "bbf40ffe5451b099574f0551cdee3f7d347a560a"
PR_B_REPAIR_MERGE_SHA = "4a6222bf7be410f1def23a6b15f68091aa2c20bc"
LIVE_RUN_ID = 30619558449
LIVE_ARTIFACT_ID = 8788807930
LIVE_ARTIFACT_DIGEST = "sha256:7b0146b8a9f634bfc7da10453724ddacff61cafa92d948b70c927e6ac341a058"
LIVE_RECEIPT_FILE_SHA256 = (
    "00f9e3ef2ca517f72041bbd17855985319686e212344ecda808660ae183832f3"
)
LIVE_RECEIPT_SELF_SHA256 = (
    "af9213286079e84395b8e0db9cc68f31760dba45119dc5c805eb0e3bdc1a81a9"
)
LIVE_PRODUCTION_JOB_ID = 91120694689
LIVE_STATIC_JOB_ID = 91120581031


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


def test_corrected_pa7_acceptance_schema_self_digest_and_live_evidence() -> None:
    acceptance = load(PILOT / "m26-pa-7-acceptance.json")
    assert schema_errors("m26-pa-7-corrected-acceptance-v2.schema.json", acceptance) == []
    verify_self_digest(acceptance, "corrected pa7 acceptance")
    assert acceptance["self_sha256"] == ACCEPTANCE_SELF_SHA256
    assert acceptance["accepted"] is True
    assert acceptance["status"] == ACCEPTED_STATUS
    assert acceptance["schema_version"] == "knowledge-engine-m26-pa-7-corrected-acceptance/v2"
    assert acceptance["stage_id"] == "M26.PA.7"
    assert acceptance["owner_decision"]["self_sha256"] == OWNER_DECISION_SELF_SHA256
    assert acceptance["corrective_authority"] == {
        "corrective_reopen_path": "pilot/m26/m26-pa-7-corrective-reopen.json",
        "corrective_reopen_self_sha256": CORRECTIVE_REOPEN_SELF_SHA256,
        "formal_test_contract_path": "pilot/m26/m26-pa-7-corrective-formal-test-contract.json",
        "formal_test_contract_self_sha256": CORRECTIVE_FORMAL_TEST_CONTRACT_SELF_SHA256,
        "formal_test_manifest_path": "pilot/m26/m26-pa-7-corrective-formal-test-manifest.json",
        "formal_test_manifest_self_sha256": FORMAL_MANIFEST_SELF_SHA256,
        "owner_authority_path": "pilot/m26/m26-pa-7-corrective-owner-authority.json",
        "owner_authority_self_sha256": CORRECTIVE_OWNER_AUTHORITY_SELF_SHA256,
    }
    assert acceptance["resolved_gate"]["self_sha256"] == CORRECTED_GATE_SELF_SHA256
    assert acceptance["promotion_trigger"]["self_sha256"] == CORRECTED_TRIGGER_SELF_SHA256

    evidence = acceptance["live_evidence"]
    assert evidence["run_id"] == LIVE_RUN_ID
    assert evidence["artifact_id"] == LIVE_ARTIFACT_ID
    assert evidence["artifact_archive_digest"] == LIVE_ARTIFACT_DIGEST
    assert evidence["artifact_archive_digest_verified"] is True
    assert evidence["artifact_entry_names"] == [
        "m26-pa-7-corrective-formal-receipt.json",
        "m26-pa-7-corrective-formal-receipt.json.sha256",
    ]
    assert evidence["receipt_file_sha256"] == LIVE_RECEIPT_FILE_SHA256
    assert evidence["receipt_self_sha256"] == LIVE_RECEIPT_SELF_SHA256
    assert evidence["receipt_status"] == "live_corrective_formal_receipt_pending_reconciliation"
    assert evidence["receipt_schema_version"] == (
        "knowledge-engine-m26-pa-7-corrective-formal-receipt/v1"
    )
    assert evidence["slo_pass"] is True
    assert evidence["workflow_head_sha"] == PR_B_REPAIR_MERGE_SHA
    assert evidence["production_promotion_job_id"] == LIVE_PRODUCTION_JOB_ID
    assert evidence["static_validate_job_id"] == LIVE_STATIC_JOB_ID


def test_corrected_acceptance_binds_predecessors_supersession_and_prs() -> None:
    acceptance = load(PILOT / "m26-pa-7-acceptance.json")
    decision = load(PILOT / "m26-pa-7-owner-final-decision.json")
    manifest = load(PILOT / "m26-pa-7-corrective-formal-test-manifest.json")
    gate = load(PILOT / "m26-pa-7-corrected-resolved-production-gate.json")
    trigger = load(PILOT / "m26-pa-7-corrected-promotion-trigger.json")

    assert validate_owner_final_decision(decision)["self_sha256"] == OWNER_DECISION_SELF_SHA256
    assert validate_corrective_formal_test_manifest(manifest)["self_sha256"] == (
        FORMAL_MANIFEST_SELF_SHA256
    )
    assert validate_resolved_gate(gate, decision)["self_sha256"] == CORRECTED_GATE_SELF_SHA256
    assert validate_promotion_trigger(trigger, gate, decision)["self_sha256"] == (
        CORRECTED_TRIGGER_SELF_SHA256
    )
    assert acceptance["supersedes_false_positive"] == {
        "old_acceptance_path": "pilot/m26/m26-pa-7-acceptance.json",
        "old_acceptance_self_sha256": OLD_ACCEPTANCE_SELF_SHA256,
        "old_acceptance_status": "m26_pa_7_production_answer_authority_and_closure_accepted",
        "old_closure_path": "pilot/m26/m26-pa-7-m26-closure.json",
        "old_closure_self_sha256": OLD_CLOSURE_SELF_SHA256,
        "old_closure_status": "m26_closed",
        "reason": (
            "prior PA.7/M26 closure proved fixed status/control-plane promotion but not "
            "arbitrary owner query product readiness"
        ),
    }
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
            "head_sha": PR_A_HEAD_SHA,
            "issue": 1257,
            "merge_sha": PR_A_MERGE_SHA,
            "pull_request": 1258,
            "scope": "corrective arbitrary owner query runtime and false-positive reopen",
        },
        "pr_b": {
            "head_sha": PR_B_HEAD_SHA,
            "issue": 1259,
            "merge_sha": PR_B_MERGE_SHA,
            "pull_request": 1260,
            "scope": "corrected formal gate, trigger, owner authority, schemas, workflow wiring",
        },
        "pr_b_calibration_repair": {
            "head_sha": PR_B_REPAIR_HEAD_SHA,
            "issue": 1259,
            "merge_sha": PR_B_REPAIR_MERGE_SHA,
            "pull_request": 1261,
            "scope": "repair cross-document calibration query and refresh dependent digests",
        },
        "pr_c": {
            "base_sha": PR_B_REPAIR_MERGE_SHA,
            "effective_only_on_merge": True,
            "issue": 1262,
            "pull_request": None,
        },
    }


def test_corrected_formal_metrics_bound_product_readiness() -> None:
    acceptance = load(PILOT / "m26-pa-7-acceptance.json")
    evidence = acceptance["live_evidence"]
    metrics = evidence["metrics"]

    assert evidence["calibration"] == {"provider_calls": 4, "query_count": 4, "slo_pass": True}
    assert evidence["formal"]["query_count"] == 8
    assert evidence["formal"]["answerable_count"] == 6
    assert evidence["formal"]["answerable_provider_invoked_count"] == 6
    assert evidence["formal"]["runtime_path"] == (
        "knowledge_engine.m26_pa7_arbitrary_query_runtime.run_owner_arbitrary_query"
    )
    assert evidence["formal"]["temporal_conflict_outcome"] == (
        "safe_abstention_allowed_by_acceptance_matrix_a24"
    )
    assert metrics["complete_accounting"] == 8
    assert metrics["answerable_grounded_pass_rate"] >= 0.8
    assert metrics["citation_locator_validity"] == 1.0
    assert metrics["material_claim_support_precision"] == 1.0
    assert metrics["safe_terminal_outcome_rate"] == 1.0
    assert metrics["mandatory_abstention_correctness"] == 1.0
    assert metrics["unsupported_accepted_claims"] == 0
    assert metrics["provider_error_count"] == 0
    assert metrics["provider_calls"] <= 32
    assert Decimal(metrics["total_payg_equivalent_cost_usd"]) <= Decimal("0.75")
    assert evidence["traffic"] == {
        "non_owner_denied_probes": 2,
        "non_owner_provider_calls": 0,
        "owner_requests": 8,
        "public_traffic_operations": 0,
    }
    assert all(value == 0 for value in evidence["mutations"].values())
    assert all(value is False for value in evidence["privacy"].values())
    failed = acceptance["failed_closed_calibration_repair_accounting"]
    assert failed["run_id"] == 30618768225
    assert failed["formal_query_count"] == 0
    assert failed["calibration_slo_pass"] is False
    assert failed["repair_pr"] == 1261


def test_m26_corrected_closure_schema_self_digest_and_final_state() -> None:
    acceptance = load(PILOT / "m26-pa-7-acceptance.json")
    closure = load(PILOT / "m26-pa-7-m26-closure.json")
    assert schema_errors("m26-pa-7-corrected-m26-closure-v2.schema.json", closure) == []
    verify_self_digest(closure, "corrected m26 closure")
    assert closure["self_sha256"] == CLOSURE_SELF_SHA256
    assert closure["status"] == CLOSURE_STATUS
    assert closure["m26_closed"] is True
    assert closure["acceptance_self_sha256"] == acceptance["self_sha256"]
    assert closure["accepted_status"] == ACCEPTED_STATUS
    assert closure["live_run_id"] == LIVE_RUN_ID
    assert closure["live_receipt_self_sha256"] == LIVE_RECEIPT_SELF_SHA256
    assert closure["supersedes_false_positive"] == acceptance["supersedes_false_positive"]
    assert closure["final_state"] == {
        "M26.PA.7": ACCEPTED_STATUS,
        "M26_CLOSED": True,
        "PRODUCTION_ANSWER_SERVING": True,
        "PRODUCTION_AUDIENCE": "Daniel owner allowlist only",
        "PUBLIC_OR_UNBOUNDED_TRAFFIC": False,
    }
    assert closure["evidence_bindings"] == {
        "artifact_id": LIVE_ARTIFACT_ID,
        "artifact_sha256": LIVE_ARTIFACT_DIGEST,
        "implementation_merge_sha": PR_A_MERGE_SHA,
        "receipt_file_sha256": LIVE_RECEIPT_FILE_SHA256,
        "receipt_self_sha256": LIVE_RECEIPT_SELF_SHA256,
        "run_id": LIVE_RUN_ID,
        "trigger_merge_sha": PR_B_MERGE_SHA,
        "trigger_repair_merge_sha": PR_B_REPAIR_MERGE_SHA,
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
    assert "Verify remote PA.7 corrected formal product-readiness evidence" in workflow
    assert str(LIVE_RUN_ID) in workflow
    assert str(LIVE_ARTIFACT_ID) in workflow
    assert "m26-pa-7-corrective-formal-receipt.json" in workflow
    assert "m26-pa-7-corrected-acceptance-v2.schema.json" in workflow
    assert "m26-pa-7-corrected-m26-closure-v2.schema.json" in workflow

    promotion_workflow = PROMOTION_WORKFLOW.read_text(encoding="utf-8")
    assert "m26_pa_7_arbitrary_owner_query_product_readiness_accepted" in promotion_workflow
    assert "Corrected PA.7 acceptance already reconciled" in promotion_workflow
    assert "steps.pa7_gate.outputs.authorized == 'true'" in promotion_workflow
