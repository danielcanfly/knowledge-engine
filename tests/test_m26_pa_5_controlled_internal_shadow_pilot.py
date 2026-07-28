from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from knowledge_engine.m26_controlled_internal_shadow_pilot import (
    ControlledShadowPilotError,
    compile_shadow_review_record,
    run_shadow_pilot_benchmark,
    validate_shadow_policy,
)
from knowledge_engine.m26_retrieval_envelope import verify_self_digest, with_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-5-controlled-internal-shadow-pilot.yml"


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


def test_pa5_acceptance_replays_complete_shadow_population() -> None:
    policy = load(PILOT / "m26-pa-5-shadow-policy.json")
    population = load(PILOT / "m26-pa-5-frozen-questions.json")
    acceptance = load(PILOT / "m26-pa-5-acceptance.json")
    for artifact in (policy, population, acceptance):
        verify_self_digest(artifact)

    report = run_shadow_pilot_benchmark(population, policy)
    assert schema_errors("m26-pa-5-shadow-pilot-benchmark-v1.schema.json", report) == []
    assert report["status"] == "m26_pa_5_controlled_internal_shadow_pilot_ready"
    assert report["question_count"] == 200
    assert report["passed_count"] == 200
    assert report["failed_count"] == 0
    assert report["self_sha256"] == acceptance["benchmark"]["report_self_sha256"]
    assert acceptance["status"] == "m26_pa_5_controlled_internal_shadow_pilot_accepted"
    assert acceptance["predecessor"]["status"] == "m26_pa_4_verified_answer_citation_gate_accepted"


def test_pa5_metrics_prove_internal_shadow_only_denominator() -> None:
    report = run_shadow_pilot_benchmark(
        load(PILOT / "m26-pa-5-frozen-questions.json"),
        load(PILOT / "m26-pa-5-shadow-policy.json"),
    )
    metrics = report["metrics"]
    assert metrics["answer_reviewed_count"] == 184
    assert metrics["abstention_reviewed_count"] == 10
    assert metrics["hold_for_repair_count"] == 6
    assert metrics["authority_rejection_count"] == 0
    assert metrics["min_reviewer_count"] >= 3
    assert metrics["latency_p95_ms"] <= 900
    assert metrics["total_cost_usd"] < 1.0
    assert metrics["public_answer_count"] == 0
    assert metrics["public_traffic_count"] == 0
    assert metrics["production_answer_serving_count"] == 0
    assert metrics["production_pointer_mutation_count"] == 0


def test_pa5_public_answer_attempt_is_rejected_and_not_persisted() -> None:
    policy = load(PILOT / "m26-pa-5-shadow-policy.json")
    question = copy.deepcopy(load(PILOT / "m26-pa-5-frozen-questions.json")["questions"][0])
    question["question_id"] = "pa5-test-public-answer-escalation"
    question["public_answer"] = True
    record = compile_shadow_review_record(question, policy)
    assert schema_errors("m26-pa-5-shadow-review-record-v1.schema.json", record) == []
    assert record["shadow_review_status"] == "shadow_rejected_authority_escalation"
    assert record["safe_for_pa6"] is False
    assert record["public_answer"] is False
    assert record["public_traffic"] is False
    assert "PUBLIC_ANSWER_ESCALATION" in record["refusal_reason_codes"]


def test_pa5_population_and_policy_drift_fail_closed() -> None:
    policy = load(PILOT / "m26-pa-5-shadow-policy.json")
    weakened = copy.deepcopy(policy)
    weakened["authority"]["public_answers"] = True
    weakened = with_self_digest(weakened)
    with pytest.raises(ControlledShadowPilotError, match="PA5_AUTHORITY_INVALID"):
        validate_shadow_policy(weakened)

    population = copy.deepcopy(load(PILOT / "m26-pa-5-frozen-questions.json"))
    population["questions"] = population["questions"][:199]
    population = with_self_digest(population)
    with pytest.raises(ControlledShadowPilotError, match="PA5_POPULATION_INVALID"):
        run_shadow_pilot_benchmark(population, policy)


def test_pa5_docs_and_workflow_are_shadow_only() -> None:
    doc = (DOCS / "m26-pa-5-controlled-internal-shadow-pilot.md").read_text(
        encoding="utf-8"
    )
    reconciliation = (DOCS / "m26-pa-5-reconciliation.md").read_text(encoding="utf-8")
    normalized = " ".join(doc.split()).lower()
    assert "200" in doc
    assert "authenticated internal" in normalized
    assert "public answers remain forbidden" in normalized
    assert "m26_pa_5_controlled_internal_shadow_pilot_accepted" in reconciliation
    assert "M26.PA.6" in reconciliation

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "secrets." not in workflow
    assert "environment: m23-r3-diagnostic" not in workflow
    assert "src/knowledge_engine/m26_controlled_internal_shadow_pilot.py" in workflow
    assert "tests/test_m26_pa_5_controlled_internal_shadow_pilot.py" in workflow
