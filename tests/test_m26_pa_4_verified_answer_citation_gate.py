from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m26_retrieval_envelope import verify_self_digest, with_self_digest
from knowledge_engine.m26_verified_answer_citation_gate import (
    READY_STATUSES,
    VerifiedAnswerCitationGateError,
    compile_verified_answer_record,
    run_verified_answer_benchmark,
    validate_verified_answer_policy,
    validate_verified_answer_record,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-4-verified-answer-citation-gate.yml"


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


def test_pa4_acceptance_replays_verified_answer_benchmark() -> None:
    policy = load(PILOT / "m26-pa-4-verified-answer-policy.json")
    cases = load(PILOT / "m26-pa-4-benchmark-cases.json")
    acceptance = load(PILOT / "m26-pa-4-acceptance.json")
    for artifact in (policy, cases, acceptance):
        verify_self_digest(artifact)

    report = run_verified_answer_benchmark(cases, policy)
    assert schema_errors("m26-pa-4-verified-answer-benchmark-v1.schema.json", report) == []
    assert report["status"] == "m26_pa_4_verified_answer_citation_gate_ready"
    assert report["case_count"] == 12
    assert report["passed_count"] == 12
    assert report["failed_count"] == 0
    assert report["self_sha256"] == acceptance["benchmark"]["report_self_sha256"]
    assert acceptance["status"] == "m26_pa_4_verified_answer_citation_gate_accepted"
    assert acceptance["predecessor"]["status"] == "m26_pa_3_live_provider_execution_accepted"


def test_pa4_metrics_cover_claims_citations_repairs_and_abstention() -> None:
    report = run_verified_answer_benchmark(
        load(PILOT / "m26-pa-4-benchmark-cases.json"),
        load(PILOT / "m26-pa-4-verified-answer-policy.json"),
    )
    metrics = report["metrics"]
    assert metrics["verified_answer_ready_count"] == 6
    assert metrics["bounded_repair_count"] == 1
    assert metrics["abstention_count"] == 6
    assert metrics["authority_rejection_count"] == 1
    assert metrics["material_claim_denominator"] == 7
    assert metrics["citation_binding_denominator"] == 7
    assert metrics["production_answer_serving_count"] == 0
    assert metrics["production_pointer_mutation_count"] == 0
    assert metrics["public_shadow_canary_traffic_count"] == 0
    assert metrics["verified_final_answer_count"] == 0


def test_pa4_authority_escalation_fails_closed_to_refusal() -> None:
    policy = load(PILOT / "m26-pa-4-verified-answer-policy.json")
    case = copy.deepcopy(load(PILOT / "m26-pa-4-benchmark-cases.json")["cases"][0])
    case["case_id"] = "pa4-test-production-escalation"
    case["candidate"]["authority"]["production_answer_serving"] = True
    record = compile_verified_answer_record(case, policy)
    assert schema_errors("m26-pa-4-verified-answer-record-v1.schema.json", record) == []
    assert record["verified_answer_status"] == "verified_answer_rejected_authority_escalation"
    assert record["safe_for_pa5"] is False
    assert record["abstention_required"] is True
    assert record["verified_claim_ids"] == []
    assert "PRODUCTION_ANSWER_SERVING_ESCALATION" in record["refusal_reason_codes"]
    assert record["production_answer_serving"] is False


def test_pa4_policy_tamper_and_ready_record_drift_are_rejected() -> None:
    policy = load(PILOT / "m26-pa-4-verified-answer-policy.json")
    tampered = dict(policy)
    tampered["self_sha256"] = "0" * 64
    with pytest.raises(IntegrityError, match="SELF_DIGEST_MISMATCH"):
        validate_verified_answer_policy(tampered)

    case = copy.deepcopy(load(PILOT / "m26-pa-4-benchmark-cases.json")["cases"][0])
    record = compile_verified_answer_record(case, policy)
    assert record["verified_answer_status"] in READY_STATUSES
    drifted = dict(record)
    drifted["verified_final_answer"] = True
    drifted = with_self_digest(drifted)
    with pytest.raises(VerifiedAnswerCitationGateError, match="PA4_AUTHORITY_ESCALATION"):
        validate_verified_answer_record(drifted)


def test_pa4_docs_and_workflow_are_non_live_and_bounded() -> None:
    doc = (DOCS / "m26-pa-4-verified-answer-citation-gate.md").read_text(
        encoding="utf-8"
    )
    reconciliation = (DOCS / "m26-pa-4-reconciliation.md").read_text(encoding="utf-8")
    assert "material claim extraction" in doc
    assert "citation binding" in doc
    assert "abstention" in doc
    assert "m26_pa_4_verified_answer_citation_gate_accepted" in reconciliation
    assert "M26.PA.5" in reconciliation

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "secrets." not in workflow
    assert "environment: m23-r3-diagnostic" not in workflow
    assert "MINIMAX_API_KEY" not in workflow
    assert "src/knowledge_engine/m26_verified_answer_citation_gate.py" in workflow
    assert "tests/test_m26_pa_4_verified_answer_citation_gate.py" in workflow
