from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.m26_final_authority_gate import (
    FinalAuthorityGateError,
    compile_final_authority_review,
    run_final_authority_benchmark,
    validate_final_authority_policy,
    validate_final_authority_review,
    verify_self_digest,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        load(PILOT / "m26-10-benchmark-cases.json"),
        load(PILOT / "m26-10-final-authority-policy.json"),
    )


def test_m26_10_entry_contract_and_policy() -> None:
    acceptance = load(PILOT / "m26-9-acceptance.json")
    entry = load(PILOT / "m26-10-entry-contract.json")
    verify_self_digest(entry)
    assert acceptance["status"] == "m26_9_candidate_qa_feedback_baseline_refresh_accepted"
    assert entry["accepted_predecessor"]["final_main_seal"] == (
        "7976e0fcf9f44c72c9b0a39f9887ca0558a82a54"
    )
    authority = entry["authority_boundary"]
    assert authority["synthetic_only"] is True
    assert authority["baseline_refresh_review_permitted"] is True
    assert authority["final_authority_review_permitted"] is True
    forbidden = {
        key: value
        for key, value in authority.items()
        if key
        not in {
            "synthetic_only",
            "baseline_refresh_review_permitted",
            "final_authority_review_permitted",
        }
    }
    assert not any(forbidden.values())
    validate_final_authority_policy(load(PILOT / "m26-10-final-authority-policy.json"))


def test_m26_10_registry_and_schema_files_exist() -> None:
    registry = load(PILOT / "m26-10-contract-registry.json")
    verify_self_digest(registry)
    assert registry["accepted_predecessor_status"] == (
        "m26_9_candidate_qa_feedback_baseline_refresh_accepted"
    )
    for path in (
        SCHEMAS / "m26-10-final-authority-review-v1.schema.json",
        SCHEMAS / "m26-10-synthetic-closure-v1.schema.json",
        DOCS / "m26-10-synthetic-final-authority-gate.md",
    ):
        assert path.exists()


def test_m26_10_benchmark() -> None:
    cases, policy = inputs()
    report = run_final_authority_benchmark(cases, policy)
    verify_self_digest(report)
    assert report["status"] == "m26_10_synthetic_final_authority_gate_ready"
    assert report["case_count"] == 12
    assert report["passed_count"] == 12
    assert report["failed_count"] == 0
    assert report["metrics"]["approved_for_future_gate_count"] == 2
    assert report["metrics"]["held_for_repair_count"] == 6
    assert report["metrics"]["rejected_authority_escalation_count"] == 4
    assert report["metrics"]["baseline_refresh_execution_count"] == 0
    assert report["metrics"]["production_answer_serving_count"] == 0
    assert report["metrics"]["verified_final_answer_count"] == 0


def test_m26_10_safe_record_is_review_only() -> None:
    _, policy = inputs()
    record = compile_final_authority_review(
        "safe",
        {
            "qa_status": "qa_feedback_ready",
            "claim_ids": ["claim-1"],
            "binding_ids": ["binding-1"],
            "warning_ids": [],
            "refusal_reason_codes": [],
            "answer_text": "",
        },
        policy,
    )
    validate_final_authority_review(record)
    assert record["decision_status"] == "approved_for_future_gate"
    assert record["answer_text"] == ""
    assert record["baseline_refresh_execution"] is False
    assert record["production_answer_serving"] is False
    assert record["verified_final_answer"] is False


def test_m26_10_warning_and_refusal_are_held() -> None:
    _, policy = inputs()
    warning = compile_final_authority_review(
        "warning",
        {
            "qa_status": "qa_feedback_ready_with_warnings",
            "claim_ids": ["claim"],
            "binding_ids": ["binding"],
            "warning_ids": ["conflict_warning"],
            "refusal_reason_codes": [],
        },
        policy,
    )
    refusal = compile_final_authority_review(
        "refusal",
        {
            "qa_status": "qa_refusal_feedback_ready",
            "claim_ids": [],
            "binding_ids": [],
            "warning_ids": [],
            "refusal_reason_codes": ["NO_MATCH"],
        },
        policy,
    )
    assert warning["decision_status"] == "held_for_repair"
    assert refusal["decision_status"] == "held_for_repair"


def test_m26_10_authority_escalation_is_rejected() -> None:
    _, policy = inputs()
    record = compile_final_authority_review(
        "escalated",
        {
            "qa_status": "qa_feedback_ready",
            "claim_ids": ["claim"],
            "binding_ids": ["binding"],
            "warning_ids": [],
            "refusal_reason_codes": [],
            "answer_text": "forbidden",
        },
        policy,
    )
    assert record["decision_status"] == "rejected_authority_escalation"
    assert record["claim_ids"] == []
    assert record["binding_ids"] == []


def test_m26_10_validation_rejects_mutated_execution() -> None:
    _, policy = inputs()
    record = compile_final_authority_review(
        "safe",
        {
            "qa_status": "qa_feedback_ready",
            "claim_ids": ["claim"],
            "binding_ids": ["binding"],
            "warning_ids": [],
            "refusal_reason_codes": [],
        },
        policy,
    )
    tampered = dict(record)
    tampered["baseline_refresh_execution"] = True
    tampered.pop("self_sha256")
    from knowledge_engine.m26_final_authority_gate import sha256_value

    tampered["self_sha256"] = sha256_value(tampered)
    with pytest.raises(FinalAuthorityGateError, match="BASELINE_REFRESH_EXECUTION_FORBIDDEN"):
        validate_final_authority_review(tampered)
