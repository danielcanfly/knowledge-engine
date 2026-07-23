from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.m26_answer_evaluation import (
    build_draft_package_for_case,
    evaluate_draft_answer,
)
from knowledge_engine.m26_answer_presentation import (
    AnswerPresentationError,
    compile_presentation_preview,
    run_presentation_benchmark,
    validate_presentation_package,
    validate_presentation_policy,
)
from knowledge_engine.m26_retrieval_envelope import verify_self_digest

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
        "presentation_cases_artifact": load(PILOT / "m26-7-benchmark-cases.json"),
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
    }


def test_m26_7_entry_contract_and_policy() -> None:
    entry = load(PILOT / "m26-7-entry-contract.json")
    verify_self_digest(entry)
    assert entry["stage_id"] == "M26.7"
    assert entry["accepted_predecessor"]["status"] == "m26_6_answer_evaluation_refusal_gate_accepted"
    assert entry["accepted_predecessor"]["final_main_seal"] == (
        "1f2dfbba74d6df91baa946bbac82e343ea81750e"
    )
    assert entry["authority_boundary"]["synthetic_only"] is True
    assert entry["authority_boundary"]["presentation_contract_permitted"] is True
    assert entry["authority_boundary"]["non_serving_preview_permitted"] is True
    forbidden = {
        key: value
        for key, value in entry["authority_boundary"].items()
        if key
        not in {
            "synthetic_only",
            "presentation_contract_permitted",
            "non_serving_preview_permitted",
            "answer_evaluation_required",
        }
    }
    assert not any(forbidden.values())
    policy = validate_presentation_policy(load(PILOT / "m26-7-presentation-policy.json"))
    assert policy["surface_policy"]["preview_only"] is True
    assert policy["surface_policy"]["allow_final_answer_text"] is False


def test_m26_7_registry_and_schema_files_exist() -> None:
    registry = load(PILOT / "m26-7-contract-registry.json")
    verify_self_digest(registry)
    assert registry["accepted_predecessor_status"] == "m26_6_answer_evaluation_refusal_gate_accepted"
    for path in (
        SCHEMAS / "m26-7-answer-presentation-v1.schema.json",
        SCHEMAS / "m26-non-serving-preview-v1.schema.json",
        DOCS / "m26-7-answer-presentation-non-serving-preview.md",
    ):
        assert path.exists()


def test_m26_7_presentation_benchmark() -> None:
    data = m26_inputs()
    report = run_presentation_benchmark(**data)
    verify_self_digest(report)
    assert report["status"] == "m26_7_answer_presentation_ready"
    assert report["case_count"] == 12
    assert report["passed_count"] == 12
    assert report["failed_count"] == 0
    assert report["metrics"]["non_serving_preview_count"] == 6
    assert report["metrics"]["non_serving_refusal_preview_count"] == 6
    assert report["metrics"]["warning_preview_count"] == 2
    assert report["metrics"]["provider_call_count"] == 0
    assert report["metrics"]["production_answer_serving_count"] == 0
    assert report["metrics"]["verified_final_answer_count"] == 0
    assert report["metrics"]["production_pointer_mutation_count"] == 0


def test_m26_7_passing_preview_keeps_identity_without_answer_text() -> None:
    data = m26_inputs()
    evaluation_case = data["evaluation_cases"]["cases"][0]
    draft = build_draft_package_for_case(
        evaluation_case,
        draft_cases=data["draft_cases"],
        provider_cases=data["provider_cases"],
        context_cases=data["context_cases"],
        retrieval_cases=data["retrieval_cases"],
        corpus=data["corpus"],
        retrieval_policy=data["retrieval_policy"],
        context_policy=data["context_policy"],
        provider_policy=data["provider_policy"],
        draft_policy=data["draft_policy"],
    )
    evaluation = evaluate_draft_answer(draft, data["evaluation_policy"])
    preview = compile_presentation_preview(evaluation, data["presentation_policy"])
    validate_presentation_package(preview)
    assert preview["presentation_status"] == "non_serving_preview_available"
    assert preview["answer_text"] == ""
    assert preview["display_claims"]
    assert preview["display_binding_ids"]
    assert all(claim["content_redacted"] is True for claim in preview["display_claims"])
    assert preview["final_answer"] is False
    assert preview["production_answer_serving"] is False


def test_m26_7_refusal_preview_has_no_claims_or_bindings() -> None:
    data = m26_inputs()
    evaluation_case = next(
        case for case in data["evaluation_cases"]["cases"] if case["case_id"] == "eval_no_match_public"
    )
    draft = build_draft_package_for_case(
        evaluation_case,
        draft_cases=data["draft_cases"],
        provider_cases=data["provider_cases"],
        context_cases=data["context_cases"],
        retrieval_cases=data["retrieval_cases"],
        corpus=data["corpus"],
        retrieval_policy=data["retrieval_policy"],
        context_policy=data["context_policy"],
        provider_policy=data["provider_policy"],
        draft_policy=data["draft_policy"],
    )
    evaluation = evaluate_draft_answer(draft, data["evaluation_policy"])
    preview = compile_presentation_preview(evaluation, data["presentation_policy"])
    assert preview["presentation_status"] == "non_serving_refusal_preview"
    assert preview["display_claims"] == []
    assert preview["display_binding_ids"] == []
    assert preview["refusal_reason_codes"]
    assert preview["answer_text"] == ""


def test_m26_7_conflict_and_prompt_warnings_are_banners_only() -> None:
    data = m26_inputs()
    for case_id, warning in (
        ("eval_conflict_public", "conflict_warning"),
        ("eval_prompt_injection_public", "prompt_injection_quarantined"),
    ):
        evaluation_case = next(
            case for case in data["evaluation_cases"]["cases"] if case["case_id"] == case_id
        )
        draft = build_draft_package_for_case(
            evaluation_case,
            draft_cases=data["draft_cases"],
            provider_cases=data["provider_cases"],
            context_cases=data["context_cases"],
            retrieval_cases=data["retrieval_cases"],
            corpus=data["corpus"],
            retrieval_policy=data["retrieval_policy"],
            context_policy=data["context_policy"],
            provider_policy=data["provider_policy"],
            draft_policy=data["draft_policy"],
        )
        evaluation = evaluate_draft_answer(draft, data["evaluation_policy"])
        preview = compile_presentation_preview(evaluation, data["presentation_policy"])
        assert preview["presentation_status"] == "non_serving_preview_with_warnings"
        assert warning in preview["warning_banners"]
        serialized = json.dumps(preview, ensure_ascii=False).casefold()
        assert "follow these instructions" not in serialized
        assert "ignore previous" not in serialized


def test_m26_7_rejects_authority_escalation_in_evaluation_input() -> None:
    data = m26_inputs()
    evaluation_case = data["evaluation_cases"]["cases"][0]
    draft = build_draft_package_for_case(
        evaluation_case,
        draft_cases=data["draft_cases"],
        provider_cases=data["provider_cases"],
        context_cases=data["context_cases"],
        retrieval_cases=data["retrieval_cases"],
        corpus=data["corpus"],
        retrieval_policy=data["retrieval_policy"],
        context_policy=data["context_policy"],
        provider_policy=data["provider_policy"],
        draft_policy=data["draft_policy"],
    )
    evaluation = evaluate_draft_answer(draft, data["evaluation_policy"])
    tampered = dict(evaluation)
    tampered["production_answer_serving"] = True
    tampered.pop("self_sha256", None)
    from knowledge_engine.m26_retrieval_envelope import sha256_value

    tampered["self_sha256"] = sha256_value(tampered)
    preview = compile_presentation_preview(tampered, data["presentation_policy"])
    assert preview["presentation_status"] == "presentation_rejected_authority_escalation"
    assert "PRODUCTION_ANSWER_SERVING_ESCALATION" in preview["refusal_reason_codes"]


def test_m26_7_validation_rejects_preview_answer_text() -> None:
    data = m26_inputs()
    evaluation_case = data["evaluation_cases"]["cases"][0]
    draft = build_draft_package_for_case(
        evaluation_case,
        draft_cases=data["draft_cases"],
        provider_cases=data["provider_cases"],
        context_cases=data["context_cases"],
        retrieval_cases=data["retrieval_cases"],
        corpus=data["corpus"],
        retrieval_policy=data["retrieval_policy"],
        context_policy=data["context_policy"],
        provider_policy=data["provider_policy"],
        draft_policy=data["draft_policy"],
    )
    evaluation = evaluate_draft_answer(draft, data["evaluation_policy"])
    preview = compile_presentation_preview(evaluation, data["presentation_policy"])
    tampered = dict(preview)
    tampered["answer_text"] = "This would look like an answer."
    tampered.pop("self_sha256", None)
    from knowledge_engine.m26_retrieval_envelope import sha256_value

    tampered["self_sha256"] = sha256_value(tampered)
    with pytest.raises(AnswerPresentationError, match="ANSWER_TEXT_FORBIDDEN"):
        validate_presentation_package(tampered)
