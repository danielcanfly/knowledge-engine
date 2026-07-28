from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from knowledge_engine.m26_production_promotion_closure import (
    EVIDENCE_CHAIN_STATUSES,
    ProductionPromotionClosureError,
    compile_final_decision_record,
    run_production_closure_benchmark,
    validate_final_decision_policy,
)
from knowledge_engine.m26_retrieval_envelope import verify_self_digest, with_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"
WORKFLOW = (
    ROOT / ".github" / "workflows" / "m26-pa-7-production-promotion-closure.yml"
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


def test_pa7_acceptance_replays_final_decision_benchmark() -> None:
    policy = load(PILOT / "m26-pa-7-final-decision-policy.json")
    cases = load(PILOT / "m26-pa-7-final-decision-cases.json")
    acceptance = load(PILOT / "m26-pa-7-acceptance.json")
    for artifact in (policy, cases, acceptance):
        verify_self_digest(artifact)

    report = run_production_closure_benchmark(cases, policy)
    assert schema_errors("m26-pa-7-production-closure-benchmark-v1.schema.json", report) == []
    assert report["status"] == "m26_pa_7_production_answer_authority_and_closure_ready"
    assert report["case_count"] == 7
    assert report["passed_count"] == 7
    assert report["failed_count"] == 0
    assert report["self_sha256"] == acceptance["benchmark"]["report_self_sha256"]
    assert acceptance["status"] == "m26_pa_7_production_answer_authority_and_closure_accepted"
    assert acceptance["predecessor"]["status"] == "m26_pa_6_canary_slo_rollback_accepted"


def test_pa7_decision_space_and_closure_boundary_are_complete() -> None:
    acceptance = load(PILOT / "m26-pa-7-acceptance.json")
    report = run_production_closure_benchmark(
        load(PILOT / "m26-pa-7-final-decision-cases.json"),
        load(PILOT / "m26-pa-7-final-decision-policy.json"),
    )
    metrics = report["metrics"]
    assert metrics["approved_bounded_count"] == 1
    assert metrics["approved_with_conditions_count"] == 1
    assert metrics["governed_defer_count"] == 2
    assert metrics["rejected_pending_redesign_count"] == 3
    assert metrics["promotion_authorized_count"] == 2
    assert metrics["production_promotion_execution_count"] == 0
    assert metrics["production_pointer_mutation_count"] == 0
    assert metrics["public_traffic_mutation_count"] == 0

    assert acceptance["final_decision"]["decision_status"] == "approved_with_conditions"
    assert acceptance["final_decision"]["production_promotion_execution"] is False
    assert acceptance["m26_closure"]["formal_closure_recorded"] is True
    assert acceptance["m26_closure"]["production_pointer_mutation_in_this_repository"] is False
    assert acceptance["m26_closure"]["public_traffic_mutation_in_this_repository"] is False
    assert [item["status"] for item in acceptance["evidence_chain"]] == list(
        EVIDENCE_CHAIN_STATUSES
    )


def test_pa7_incomplete_chain_defers_and_protected_mutation_rejects() -> None:
    policy = load(PILOT / "m26-pa-7-final-decision-policy.json")
    case = copy.deepcopy(load(PILOT / "m26-pa-7-final-decision-cases.json")["cases"][0])
    case["case_id"] = "pa7-test-incomplete-chain"
    case["evidence_chain"] = case["evidence_chain"][:-1]
    record = compile_final_decision_record(case, policy)
    assert schema_errors("m26-pa-7-final-decision-record-v1.schema.json", record) == []
    assert record["decision_status"] == "governed_defer"
    assert record["production_promotion_authorized"] is False
    assert record["production_promotion_execution"] is False
    assert "EVIDENCE_CHAIN_INCOMPLETE" in record["conditions_or_reasons"]

    case = copy.deepcopy(load(PILOT / "m26-pa-7-final-decision-cases.json")["cases"][0])
    case["case_id"] = "pa7-test-source-mutation"
    case["protected_mutations"]["source_foundation_release_mutation"] = True
    record = compile_final_decision_record(case, policy)
    assert record["decision_status"] == "rejected_pending_redesign"
    assert record["source_foundation_release_mutation"] is False
    assert "SOURCE_FOUNDATION_RELEASE_MUTATION" in record["conditions_or_reasons"]


def test_pa7_policy_drift_fails_closed() -> None:
    policy = load(PILOT / "m26-pa-7-final-decision-policy.json")
    weakened = copy.deepcopy(policy)
    weakened["authority"]["unbounded_production_promotion"] = True
    weakened = with_self_digest(weakened)
    with pytest.raises(ProductionPromotionClosureError, match="PA7_AUTHORITY_INVALID"):
        validate_final_decision_policy(weakened)

    weakened = copy.deepcopy(policy)
    weakened["decision_policy"]["valid_outcomes"] = ["approved_bounded_production_promotion"]
    weakened = with_self_digest(weakened)
    with pytest.raises(ProductionPromotionClosureError, match="PA7_DECISION_POLICY_INVALID"):
        validate_final_decision_policy(weakened)


def test_pa7_docs_and_workflow_capture_final_reconciliation_boundary() -> None:
    doc = (DOCS / "m26-pa-7-production-promotion-closure.md").read_text(
        encoding="utf-8"
    )
    reconciliation = (DOCS / "m26-pa-7-reconciliation.md").read_text(encoding="utf-8")
    normalized = " ".join(doc.split()).lower()
    assert "Daniel final decision" in doc
    assert "approved_with_conditions" in doc
    assert "production pointer mutation in this repository remains false" in normalized
    assert "m26_pa_7_production_answer_authority_and_closure_accepted" in reconciliation
    assert "formal m26 closure" in reconciliation.lower()

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "secrets." not in workflow
    assert "environment: m23-r3-diagnostic" not in workflow
    assert "src/knowledge_engine/m26_production_promotion_closure.py" in workflow
    assert "tests/test_m26_pa_7_production_promotion_closure.py" in workflow
