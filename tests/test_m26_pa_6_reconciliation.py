from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from knowledge_engine.m26_verified_answer_citation_gate import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-6-reconciliation.yml"
CANARY_WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-6-canary-slo-rollback.yml"

ACCEPTED_STATUS = "m26_pa_6_canary_slo_rollback_accepted"
PA7_UNLOCK_STATUS = "m26_pa_7_unlocked_pending_owner_promotion"
APPROVED_CANDIDATE_SELF_SHA256 = (
    "e59ee979dfe48cc7b3336c0ed4ce98e492538ba9040474cfa2e59ed18e234672"
)
AUTHORIZATION_HEAD_SHA = "e0a36ed1e04f2955677de0956883daa7b2905e4c"
AUTHORIZATION_MERGE_SHA = "71dea82857b63508321e509b3f4cf6770dc139fa"
LIVE_RUN_ID = 30548085276
LIVE_ARTIFACT_ID = 8761645931
LIVE_ARTIFACT_DIGEST = "sha256:79cf3eab86d539a9f69a4b458a4c2a49bc4cfb114a4eb14023a7329286379035"
LIVE_RECEIPT_FILE_SHA256 = (
    "4a936253af6f1e1693c3a5f20bf3749a979250a47c87c3fb8f6e8ab6f7e1aac3"
)
LIVE_RECEIPT_SELF_SHA256 = (
    "b80af1930bf24bb1e285d01c309619d0273a922eddd63ac3218ea1d7282205f6"
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


def assert_self_digest(value: dict[str, Any]) -> None:
    expected = value["self_sha256"]
    candidate = dict(value)
    candidate["self_sha256"] = ""
    assert canonical_sha256(candidate) == expected


def test_pa6_acceptance_schema_self_digest_and_live_evidence() -> None:
    acceptance = load(PILOT / "m26-pa-6-acceptance.json")
    assert schema_errors("m26-pa-6-acceptance-v1.schema.json", acceptance) == []
    assert_self_digest(acceptance)
    assert acceptance["accepted"] is True
    assert acceptance["status"] == ACCEPTED_STATUS
    assert acceptance["stage_id"] == "M26.PA.6"
    assert acceptance["live_evidence"]["run_id"] == LIVE_RUN_ID
    assert acceptance["live_evidence"]["artifact_id"] == LIVE_ARTIFACT_ID
    assert acceptance["live_evidence"]["artifact_archive_digest"] == LIVE_ARTIFACT_DIGEST
    assert acceptance["live_evidence"]["receipt_file_sha256"] == LIVE_RECEIPT_FILE_SHA256
    assert acceptance["live_evidence"]["receipt_self_sha256"] == LIVE_RECEIPT_SELF_SHA256
    assert acceptance["live_evidence"]["slo_pass"] is True
    assert acceptance["live_evidence"]["metrics"]["complete_accounting"] == 20
    assert acceptance["live_evidence"]["metrics"]["provider_calls"] == 40
    assert acceptance["live_evidence"]["metrics"]["post_kill_provider_calls"] == 0
    assert acceptance["reconciliation"]["remote_run_and_artifact_verified"] is True
    assert acceptance["reconciliation"]["thresholds_verified"] is True
    assert acceptance["next_stage"]["stage_id"] == "M26.PA.7"
    assert acceptance["next_stage"]["pa7_unlock_status_after_reconciliation_merge"] == (
        PA7_UNLOCK_STATUS
    )


def test_pa6_acceptance_binds_authorization_and_predecessors() -> None:
    acceptance = load(PILOT / "m26-pa-6-acceptance.json")
    authorized_gate = load(PILOT / "m26-pa-6-owner-gate-authorized.json")
    unlock = load(PILOT / "m26-pa-6-unlock-pending-owner-canary-approval.json")
    pa5 = load(PILOT / "m26-pa-5-v8-acceptance.json")

    assert acceptance["owner_gate_authorization"] == {
        "approved_candidate_self_sha256": APPROVED_CANDIDATE_SELF_SHA256,
        "authorization_base_sha": "581837460451f600af83132cd89509674bdd1964",
        "authorization_head_sha": AUTHORIZATION_HEAD_SHA,
        "authorization_issue": 1247,
        "authorization_merge_sha": AUTHORIZATION_MERGE_SHA,
        "authorization_pull_request": 1248,
        "expected_head_merge": True,
        "ratified_owner_gate_self_sha256": authorized_gate["self_sha256"],
        "workflow_name": "M26.PA.6 Canary SLO Rollback",
    }
    assert acceptance["predecessor"] == {
        "pa5_acceptance_self_sha256": pa5["self_sha256"],
        "pa5_status": pa5["status"],
        "pa6_unlock_self_sha256": unlock["self_sha256"],
        "pa6_unlock_status": unlock["status"],
    }
    assert acceptance["owner_gate_control_plane"] == {
        "before_state_digest": "e00024ad5d19d661bfeefe4e53df614634def870a657b6f0ed1238f5053ac11b",
        "denied_control_probe_count": 2,
        "kill_switch_propagation_ms": 250,
        "killed_state_digest": "d068689a4d7489d1ac338576cf9a5c821905668073bc9c8c34176040d25f3343",
        "post_kill_provider_calls": 0,
        "production_pointer_mutations": 0,
        "production_serving_operations": 0,
        "public_traffic_operations": 0,
        "r2_qdrant_source_foundation_release_mutations": 0,
        "restored_state_digest": "e00024ad5d19d661bfeefe4e53df614634def870a657b6f0ed1238f5053ac11b",
        "rollback_target_state_digest": (
            "e00024ad5d19d661bfeefe4e53df614634def870a657b6f0ed1238f5053ac11b"
        ),
    }


def test_pa7_unlock_schema_self_digest_and_pending_promotion_boundaries() -> None:
    unlock = load(PILOT / "m26-pa-7-unlock-pending-owner-promotion.json")
    acceptance = load(PILOT / "m26-pa-6-acceptance.json")
    assert schema_errors(
        "m26-pa-7-unlock-pending-owner-promotion-v1.schema.json",
        unlock,
    ) == []
    assert_self_digest(unlock)
    assert unlock["status"] == PA7_UNLOCK_STATUS
    assert unlock["stage_id"] == "M26.PA.7"
    assert unlock["effective_only_after_pa6_reconciliation_merge"] is True
    assert unlock["predecessor"] == {
        "pa6_acceptance_path": "pilot/m26/m26-pa-6-acceptance.json",
        "pa6_acceptance_self_sha256": acceptance["self_sha256"],
        "pa6_status": ACCEPTED_STATUS,
    }
    assert unlock["authority_boundary"] == {
        "additional_live_canary_attempts": False,
        "m26_closed": False,
        "pa7_promotion_authorized": False,
        "production_answer_serving": False,
        "production_pointer_mutation": False,
        "public_traffic": False,
        "r2_qdrant_source_foundation_release_mutations": 0,
    }
    assert unlock["next_required_gate"] == {
        "daniel_owner_promotion_approval_required": True,
        "must_bind_final_answer_authority": True,
        "must_bind_m26_closure_decision": True,
        "must_bind_production_pointer_target": True,
        "must_bind_production_promotion_scope": True,
        "must_bind_public_traffic_policy": True,
        "must_preserve_rollback_or_fail_closed_plan": True,
    }


def test_pa6_reconciliation_workflow_is_read_only_and_remote_verifying() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "actions: read" in workflow
    assert "issues: read" in workflow
    assert "pull-requests: read" in workflow
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert "MINIMAX_API_KEY" not in workflow
    assert "pilot/m26/m26-pa-6-acceptance.json" in workflow
    assert "pilot/m26/m26-pa-7-unlock-pending-owner-promotion.json" in workflow
    assert "tests/test_m26_pa_6_reconciliation.py" in workflow


def test_pa6_canary_workflow_skips_live_action_after_reconciliation() -> None:
    workflow = CANARY_WORKFLOW.read_text(encoding="utf-8")
    assert "pilot/m26/m26-pa-6-acceptance.json" in workflow
    assert "PA.6 acceptance already reconciled" in workflow
    assert "steps.owner_gate.outputs.authorized == 'true'" in workflow
