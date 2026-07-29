from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from knowledge_engine.m26_pa5_controlled_internal_pilot import (
    BLOCKED_STATUS,
    ENTRY_GATE_SCHEMA_VERSION,
    PA4_ACCEPTANCE_SELF_SHA256,
    PA5GateError,
    canonical_sha256,
    render_owner_approval_block,
    validate_entry_gate,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-5-controlled-internal-pilot.yml"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def assert_self_digest(value: dict[str, Any]) -> None:
    expected = value["self_sha256"]
    candidate = dict(value)
    candidate["self_sha256"] = ""
    assert canonical_sha256(candidate) == expected


def test_pa5_entry_gate_schema_and_self_digest() -> None:
    gate = load(PILOT / "m26-pa-5-entry-gate.json")
    schema = load(SCHEMAS / "m26-pa-5-entry-gate-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    errors = sorted(
        Draft202012Validator(schema).iter_errors(gate),
        key=lambda error: list(error.absolute_path),
    )
    assert errors == []
    assert_self_digest(gate)
    assert validate_entry_gate(gate) == {
        "owner_gate_required": True,
        "predecessor_status": "m26_pa_4_verified_answer_citation_gate_accepted",
        "stage_id": "M26.PA.5",
        "status": BLOCKED_STATUS,
    }
    assert gate["schema_version"] == ENTRY_GATE_SCHEMA_VERSION


def test_pa5_entry_gate_binds_pa4_acceptance_and_issue() -> None:
    gate = load(PILOT / "m26-pa-5-entry-gate.json")
    assert gate["issue"] == {
        "number": 1212,
        "repository": "danielcanfly/knowledge-engine",
        "state_before_implementation_pr": "open",
        "title": "M26.PA.5 controlled internal shadow pilot implementation gate",
    }
    assert gate["predecessor"] == {
        "pa4_acceptance_self_sha256": PA4_ACCEPTANCE_SELF_SHA256,
        "pa4_reconciliation_merge_sha": "3fcc4e5520db6d3cac7ce18004753c2549592afa",
        "pa4_reconciliation_pull_request": 1211,
        "pa4_status": "m26_pa_4_verified_answer_citation_gate_accepted",
    }
    assert gate["stage_contract"] == {
        "accepted_status": "m26_pa_5_controlled_internal_shadow_pilot_accepted",
        "goal": "Execute and reconcile the real 200-500-question controlled internal pilot.",
        "human_gate": "Daniel population, reviewer, budget, and threshold approval",
        "required_predecessor_status": (
            "m26_pa_4_verified_answer_citation_gate_accepted"
        ),
        "requires_exact_head_ci": True,
        "requires_expected_head_merge": True,
        "requires_fresh_branch": True,
        "requires_implementation_pr": True,
        "requires_independent_reconciliation": True,
        "requires_issue": True,
    }


def test_pa5_owner_gate_values_are_not_inferred() -> None:
    gate = load(PILOT / "m26-pa-5-entry-gate.json")
    assert gate["owner_gate"]["required"] is True
    assert gate["owner_gate"]["approval_received"] is False
    assert gate["owner_gate"]["approval_values_may_not_be_inferred"] is True
    assert gate["next_step"] == {
        "approval_block_required": True,
        "execute_pilot_after_implementation_merge_only_if_approved": True,
        "independent_reconciliation_required_after_execution": True,
        "stop_at_owner_gate": True,
    }
    required_fields = set(gate["owner_gate"]["required_fields"])
    assert required_fields == {
        "adjudicator",
        "authenticated_internal_shadow_only_no_public_answers_or_production_serving",
        "exact_implementation_pr_and_head",
        "exact_predecessor_acceptance",
        "execution_duration_window",
        "frozen_population_count_and_digest",
        "incident_stop_conditions",
        "maximum_calls_and_total_spend",
        "provider_model_and_credential_environment",
        "quality_citation_abstention_latency_cost_disagreement_thresholds",
        "reviewer_principals_and_types",
    }


def test_pa5_population_and_evidence_contract_rejects_placeholders() -> None:
    gate = load(PILOT / "m26-pa-5-entry-gate.json")
    plan = gate["recommended_population_plan"]
    assert plan["minimum_population_count"] == 200
    assert plan["maximum_population_count"] == 500
    assert sum(item["count"] for item in plan["strata"]) == 200
    assert {item["name"] for item in plan["strata"]} == {
        "abstention_no_answer",
        "conflict_and_temporal_freshness",
        "cross_document_comparison",
        "direct_grounded_factual",
        "graph_navigation",
        "prompt_injection_privacy_adversarial",
        "provenance_and_source_trace",
    }
    review_policy = plan["review_policy"]
    assert review_policy["independent_reviews_per_question"] == 2
    assert review_policy["human_review_for_all_disagreements"] is True
    assert review_policy["human_review_sample_minimum_fraction"] == 0.1
    evidence_policy = gate["evidence_policy"]
    assert evidence_policy["forbid_placeholder_questions"] is True
    assert evidence_policy["forbid_invented_reviewer_ids"] is True
    assert evidence_policy["forbid_formula_generated_scores_latency_cost_or_agreement"] is True
    assert evidence_policy["forbid_synthetic_provider_receipts_presented_as_live"] is True
    assert evidence_policy["real_execution_for_entire_approved_population_required"] is True


def test_pa5_owner_decision_and_receipt_schemas_are_strict() -> None:
    for filename in (
        "m26-pa-5-owner-decision-v1.schema.json",
        "m26-pa-5-pilot-receipt-v1.schema.json",
    ):
        schema = load(SCHEMAS / filename)
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"].startswith(
            "knowledge-engine-m26-pa-5-"
        )

    owner_schema = load(SCHEMAS / "m26-pa-5-owner-decision-v1.schema.json")
    parsed = owner_schema["properties"]["parsed_parameters"]["properties"]
    assert parsed["frozen_population_count"] == {"const": 200}
    assert parsed["frozen_population_sha256"]["const"] == (
        "101fb166147195013ede721c68ac2dc2cef9445865436c8cf130a0dd2addd580"
    )
    assert parsed["pa4_acceptance_self_sha256"]["const"] == PA4_ACCEPTANCE_SELF_SHA256


def test_pa5_entry_gate_refuses_premature_authority() -> None:
    gate = load(PILOT / "m26-pa-5-entry-gate.json")
    assert not any(gate["authority_boundary"].values())

    mutated = dict(gate)
    mutated["authority_boundary"] = dict(gate["authority_boundary"])
    mutated["authority_boundary"]["production_answer_serving"] = True
    mutated["self_sha256"] = hashlib.sha256(b"bad").hexdigest()
    with pytest.raises(PA5GateError, match="forbidden authority"):
        validate_entry_gate(mutated)

    mutated = dict(gate)
    mutated["owner_gate"] = dict(gate["owner_gate"])
    mutated["owner_gate"]["approval_received"] = True
    mutated["self_sha256"] = hashlib.sha256(b"bad").hexdigest()
    with pytest.raises(PA5GateError, match="pre-claimed"):
        validate_entry_gate(mutated)


def test_pa5_approval_block_is_exact_head_scoped_but_owner_filled() -> None:
    block = render_owner_approval_block(
        implementation_pr=9999,
        implementation_head_sha="a" * 40,
    )
    assert "#9999 / " + "a" * 40 in block
    assert PA4_ACCEPTANCE_SELF_SHA256 in block
    assert "<COUNT_200_TO_500> / <SHA256>" in block
    assert "<ROSTER_WITH_HUMAN_MODEL_VERIFIER_TYPES>" in block
    assert "does not authorize PA.6 canary traffic" in block
    assert "PA.7 closure" in block


def test_pa5_doc_and_workflow_preserve_gate_boundary() -> None:
    doc = (DOCS / "m26-pa-5-controlled-internal-pilot.md").read_text(encoding="utf-8")
    assert "m26_pa_5_blocked_pending_owner_approval" in doc
    assert PA4_ACCEPTANCE_SELF_SHA256 in doc
    assert "These values must not be inferred or auto-selected" in doc
    assert "does not execute the pilot" in doc
    assert "does not authorize PA.5 execution before owner approval" in doc
    assert "m26_closed" in doc

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "static-authorization:\n    if: github.event_name == 'pull_request'" in workflow
    assert "live-controlled-internal-pilot:" in workflow
    assert "test -z \"${MINIMAX_API_KEY:-}\"" in workflow
