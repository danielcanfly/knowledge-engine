from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.m26_candidate_qa_feedback import (
    CandidateQAFeedbackError,
    compile_baseline_refresh_plan,
    review_candidate_record,
    run_qa_benchmark,
    validate_baseline_refresh_plan,
    validate_qa_feedback,
    validate_qa_policy,
)
from knowledge_engine.m26_preview_candidate_bundle import (
    build_presentation_package_for_case,
    compile_candidate_record,
)
from knowledge_engine.m26_retrieval_envelope import sha256_value, verify_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def m26_inputs() -> dict[str, dict[str, Any]]:
    return {
        "qa_cases_artifact": load(PILOT / "m26-9-benchmark-cases.json"),
        "candidate_cases": load(PILOT / "m26-8-benchmark-cases.json"),
        "presentation_cases": load(PILOT / "m26-7-benchmark-cases.json"),
        "evaluation_cases": load(PILOT / "m26-6-benchmark-cases.json"),
        "draft_cases": load(PILOT / "m26-5-benchmark-cases.json"),
        "provider_cases": load(PILOT / "m26-4-benchmark-cases.json"),
        "context_cases": load(PILOT / "m26-3-benchmark-cases.json"),
        "retrieval_cases": load(PILOT / "m26-2-benchmark-cases.json"),
        "corpus": load(PILOT / "m26-2-synthetic-corpus.json"),
        "retrieval_policy": load(PILOT / "m26-2-retrieval-policy.json"),
        "context_policy": load(PILOT / "m26-3-context-policy.json"),
        "provider_policy": load(PILOT / "m26-4-provider-policy.json"),
        "draft_policy": load(PILOT / "m26-5-draft-answer-policy.json"),
        "evaluation_policy": load(PILOT / "m26-6-answer-evaluation-policy.json"),
        "presentation_policy": load(PILOT / "m26-7-presentation-policy.json"),
        "candidate_policy": load(PILOT / "m26-8-candidate-bundle-policy.json"),
        "qa_policy": load(PILOT / "m26-9-candidate-qa-policy.json"),
    }


def candidate_record_for_case(case_id: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    data = m26_inputs()
    candidate_case = next(
        case for case in data["candidate_cases"]["cases"] if case["case_id"] == case_id
    )
    preview = build_presentation_package_for_case(
        candidate_case,
        presentation_cases=data["presentation_cases"],
        evaluation_cases=data["evaluation_cases"],
        draft_cases=data["draft_cases"],
        provider_cases=data["provider_cases"],
        context_cases=data["context_cases"],
        retrieval_cases=data["retrieval_cases"],
        corpus=data["corpus"],
        retrieval_policy=data["retrieval_policy"],
        context_policy=data["context_policy"],
        provider_policy=data["provider_policy"],
        draft_policy=data["draft_policy"],
        evaluation_policy=data["evaluation_policy"],
        presentation_policy=data["presentation_policy"],
    )
    record = compile_candidate_record(preview, data["candidate_policy"])
    return record, data


def test_m26_9_entry_contract_and_policy() -> None:
    entry = load(PILOT / "m26-9-entry-contract.json")
    verify_self_digest(entry)
    assert entry["stage_id"] == "M26.9"
    assert entry["accepted_predecessor"]["status"] == (
        "m26_8_preview_evidence_candidate_bundle_accepted"
    )
    assert entry["accepted_predecessor"]["final_main_seal"] == (
        "f75f2a427159b4dedbac032f36df3a47fda42ba5"
    )
    authority = entry["authority_boundary"]
    assert authority["synthetic_only"] is True
    assert authority["candidate_bundle_review_permitted"] is True
    assert authority["baseline_refresh_planning_permitted"] is True
    assert authority["baseline_refresh_execution_permitted"] is False
    policy = validate_qa_policy(load(PILOT / "m26-9-candidate-qa-policy.json"))
    assert policy["feedback_policy"]["planning_only"] is True
    assert policy["feedback_policy"]["allow_answer_text"] is False


def test_m26_9_registry_and_schema_files_exist() -> None:
    registry = load(PILOT / "m26-9-contract-registry.json")
    verify_self_digest(registry)
    assert registry["accepted_predecessor_status"] == (
        "m26_8_preview_evidence_candidate_bundle_accepted"
    )
    for path in (
        SCHEMAS / "m26-candidate-qa-feedback-v1.schema.json",
        SCHEMAS / "m26-baseline-refresh-plan-v1.schema.json",
        DOCS / "m26-9-candidate-qa-feedback-baseline-refresh.md",
    ):
        assert path.exists()


def test_m26_9_qa_benchmark() -> None:
    data = m26_inputs()
    report = run_qa_benchmark(**data)
    verify_self_digest(report)
    assert report["status"] == "m26_9_candidate_qa_ready"
    assert report["case_count"] == 12
    assert report["passed_count"] == 12
    assert report["failed_count"] == 0
    assert report["metrics"]["qa_feedback_ready_count"] == 6
    assert report["metrics"]["qa_refusal_feedback_count"] == 4
    assert report["metrics"]["qa_rejected_feedback_count"] == 2
    assert report["metrics"]["warning_feedback_count"] == 2
    assert report["metrics"]["baseline_refresh_execution_count"] == 0
    assert report["metrics"]["production_answer_serving_count"] == 0
    assert report["metrics"]["production_pointer_mutation_count"] == 0
    assert report["metrics"]["verified_final_answer_count"] == 0


def test_m26_9_feedback_keeps_identity_without_answer_text() -> None:
    record, data = candidate_record_for_case("candidate_direct_public")
    feedback = review_candidate_record(record, data["qa_policy"])
    validate_qa_feedback(feedback, data["qa_policy"])
    assert feedback["qa_feedback_status"] == "qa_feedback_ready"
    assert feedback["answer_text"] == ""
    assert feedback["review_claim_ids"]
    assert feedback["review_binding_ids"]
    assert feedback["baseline_refresh_execution"] is False
    assert feedback["production_answer_serving"] is False
    assert feedback["production_pointer_mutation"] is False


def test_m26_9_refusal_feedback_has_no_claims_or_bindings() -> None:
    record, data = candidate_record_for_case("candidate_no_match_public")
    feedback = review_candidate_record(record, data["qa_policy"])
    assert feedback["qa_feedback_status"] == "qa_refusal_feedback_ready"
    assert feedback["review_claim_ids"] == []
    assert feedback["review_binding_ids"] == []
    assert feedback["refusal_reason_codes"]
    assert feedback["baseline_refresh_plan"]["execution"] is False


def test_m26_9_conflict_and_prompt_warnings_are_identity_only() -> None:
    data = m26_inputs()
    for case_id, warning in (
        ("candidate_conflict_public", "conflict_warning"),
        ("candidate_prompt_injection_public", "prompt_injection_quarantined"),
    ):
        record, _ = candidate_record_for_case(case_id)
        feedback = review_candidate_record(record, data["qa_policy"])
        assert feedback["qa_feedback_status"] == "qa_feedback_ready_with_warnings"
        assert warning in feedback["warning_identities"]
        serialized = json.dumps(feedback, ensure_ascii=False).casefold()
        assert "follow these instructions" not in serialized
        assert "ignore previous" not in serialized


def test_m26_9_baseline_plan_is_planning_only() -> None:
    data = m26_inputs()
    direct, _ = candidate_record_for_case("candidate_direct_public")
    refusal, _ = candidate_record_for_case("candidate_no_match_public")
    feedbacks = [
        review_candidate_record(direct, data["qa_policy"]),
        review_candidate_record(refusal, data["qa_policy"]),
    ]
    plan = compile_baseline_refresh_plan(feedbacks, data["qa_policy"])
    validate_baseline_refresh_plan(plan)
    assert plan["status"] == "m26_9_baseline_refresh_plan_ready"
    assert plan["record_count"] == 2
    assert plan["feedback_ready_count"] == 1
    assert plan["refusal_feedback_count"] == 1
    assert plan["baseline_refresh_execution"] is False
    assert plan["production_pointer_mutation"] is False


def test_m26_9_rejects_candidate_authority_escalation() -> None:
    record, data = candidate_record_for_case("candidate_direct_public")
    tampered = dict(record)
    tampered["production_pointer_mutation"] = True
    tampered.pop("self_sha256", None)
    tampered["self_sha256"] = sha256_value(tampered)
    feedback = review_candidate_record(tampered, data["qa_policy"])
    assert feedback["qa_feedback_status"] == "qa_rejected_authority_escalation"
    assert "PRODUCTION_POINTER_ESCALATION" in feedback["refusal_reason_codes"]


def test_m26_9_validation_rejects_feedback_answer_text() -> None:
    record, data = candidate_record_for_case("candidate_direct_public")
    feedback = review_candidate_record(record, data["qa_policy"])
    tampered = dict(feedback)
    tampered["answer_text"] = "This would look like a final answer."
    tampered.pop("self_sha256", None)
    tampered["self_sha256"] = sha256_value(tampered)
    with pytest.raises(CandidateQAFeedbackError, match="ANSWER_TEXT_FORBIDDEN"):
        validate_qa_feedback(tampered, data["qa_policy"])
