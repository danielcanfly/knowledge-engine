from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.m26_answer_presentation import (
    build_evaluation_package_for_case,
    compile_presentation_preview,
)
from knowledge_engine.m26_preview_candidate_bundle import (
    PreviewCandidateBundleError,
    compile_candidate_bundle,
    compile_candidate_record,
    run_candidate_benchmark,
    validate_candidate_bundle,
    validate_candidate_policy,
    validate_candidate_record,
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
        "candidate_cases_artifact": load(PILOT / "m26-8-benchmark-cases.json"),
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
    }


def preview_for_case(case_id: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    data = m26_inputs()
    presentation_case = next(
        case for case in data["presentation_cases"]["cases"] if case["case_id"] == case_id
    )
    evaluation = build_evaluation_package_for_case(
        presentation_case,
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
    )
    preview = compile_presentation_preview(evaluation, data["presentation_policy"])
    return preview, data


def test_m26_8_entry_contract_and_policy() -> None:
    entry = load(PILOT / "m26-8-entry-contract.json")
    verify_self_digest(entry)
    assert entry["stage_id"] == "M26.8"
    assert entry["accepted_predecessor"]["status"] == (
        "m26_7_answer_presentation_non_serving_preview_accepted"
    )
    assert entry["accepted_predecessor"]["final_main_seal"] == (
        "e532403b3b1f0029b224f77374f5fae83b0f9e09"
    )
    authority = entry["authority_boundary"]
    assert authority["synthetic_only"] is True
    assert authority["preview_evidence_integration_permitted"] is True
    assert authority["candidate_bundle_permitted"] is True
    forbidden = {
        key: value
        for key, value in authority.items()
        if key
        not in {
            "synthetic_only",
            "preview_evidence_integration_permitted",
            "candidate_bundle_permitted",
            "presentation_contract_required",
        }
    }
    assert not any(forbidden.values())
    policy = validate_candidate_policy(load(PILOT / "m26-8-candidate-bundle-policy.json"))
    assert policy["surface_policy"]["candidate_only"] is True
    assert policy["surface_policy"]["allow_answer_text"] is False


def test_m26_8_registry_and_schema_files_exist() -> None:
    registry = load(PILOT / "m26-8-contract-registry.json")
    verify_self_digest(registry)
    assert registry["accepted_predecessor_status"] == (
        "m26_7_answer_presentation_non_serving_preview_accepted"
    )
    for path in (
        SCHEMAS / "m26-8-preview-evidence-integration-v1.schema.json",
        SCHEMAS / "m26-candidate-bundle-v1.schema.json",
        DOCS / "m26-8-preview-evidence-candidate-bundle.md",
    ):
        assert path.exists()


def test_m26_8_candidate_benchmark() -> None:
    data = m26_inputs()
    report = run_candidate_benchmark(**data)
    verify_self_digest(report)
    assert report["status"] == "m26_8_candidate_bundle_ready"
    assert report["case_count"] == 12
    assert report["passed_count"] == 12
    assert report["failed_count"] == 0
    assert report["metrics"]["candidate_preview_count"] == 6
    assert report["metrics"]["candidate_refusal_count"] == 6
    assert report["metrics"]["warning_record_count"] == 2
    assert report["metrics"]["provider_call_count"] == 0
    assert report["metrics"]["production_answer_serving_count"] == 0
    assert report["metrics"]["production_pointer_mutation_count"] == 0
    assert report["metrics"]["verified_final_answer_count"] == 0


def test_m26_8_candidate_preview_keeps_identity_without_answer_text() -> None:
    preview, data = preview_for_case("present_direct_public")
    record = compile_candidate_record(preview, data["candidate_policy"])
    validate_candidate_record(record, data["candidate_policy"])
    assert record["candidate_record_status"] == "candidate_preview_record"
    assert record["answer_text"] == ""
    assert record["candidate_claim_ids"]
    assert record["candidate_binding_ids"]
    assert record["final_answer"] is False
    assert record["production_answer_serving"] is False
    assert record["production_pointer_mutation"] is False


def test_m26_8_refusal_candidate_has_no_claims_or_bindings() -> None:
    preview, data = preview_for_case("present_no_match_public")
    record = compile_candidate_record(preview, data["candidate_policy"])
    assert record["candidate_record_status"] == "candidate_refusal_record"
    assert record["candidate_claim_ids"] == []
    assert record["candidate_binding_ids"] == []
    assert record["refusal_reason_codes"]
    assert record["answer_text"] == ""


def test_m26_8_conflict_and_prompt_warnings_are_identity_only() -> None:
    data = m26_inputs()
    for case_id, warning in (
        ("present_conflict_public", "conflict_warning"),
        ("present_prompt_injection_public", "prompt_injection_quarantined"),
    ):
        preview, _ = preview_for_case(case_id)
        record = compile_candidate_record(preview, data["candidate_policy"])
        assert record["candidate_record_status"] == "candidate_preview_record_with_warnings"
        assert warning in record["warning_banners"]
        serialized = json.dumps(record, ensure_ascii=False).casefold()
        assert "follow these instructions" not in serialized
        assert "ignore previous" not in serialized


def test_m26_8_candidate_bundle_compiles_preview_and_refusal_records() -> None:
    data = m26_inputs()
    direct_preview, _ = preview_for_case("present_direct_public")
    refusal_preview, _ = preview_for_case("present_no_match_public")
    records = [
        compile_candidate_record(direct_preview, data["candidate_policy"]),
        compile_candidate_record(refusal_preview, data["candidate_policy"]),
    ]
    bundle = compile_candidate_bundle(records, data["candidate_policy"])
    validate_candidate_bundle(bundle)
    assert bundle["status"] == "m26_8_candidate_bundle_ready"
    assert bundle["record_count"] == 2
    assert bundle["candidate_preview_count"] == 1
    assert bundle["candidate_refusal_count"] == 1
    assert bundle["production_pointer_mutation"] is False


def test_m26_8_rejects_preview_authority_escalation() -> None:
    preview, data = preview_for_case("present_direct_public")
    tampered = dict(preview)
    tampered["production_pointer_mutation"] = True
    tampered.pop("self_sha256", None)
    tampered["self_sha256"] = sha256_value(tampered)
    record = compile_candidate_record(tampered, data["candidate_policy"])
    assert record["candidate_record_status"] == "candidate_rejected_authority_escalation"
    assert "PRODUCTION_POINTER_ESCALATION" in record["refusal_reason_codes"]


def test_m26_8_validation_rejects_candidate_answer_text() -> None:
    preview, data = preview_for_case("present_direct_public")
    record = compile_candidate_record(preview, data["candidate_policy"])
    tampered = dict(record)
    tampered["answer_text"] = "This would look like a final answer."
    tampered.pop("self_sha256", None)
    tampered["self_sha256"] = sha256_value(tampered)
    with pytest.raises(PreviewCandidateBundleError, match="ANSWER_TEXT_FORBIDDEN"):
        validate_candidate_record(tampered, data["candidate_policy"])
