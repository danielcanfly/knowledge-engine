from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from knowledge_engine.m26_answer_evaluation import (
    AnswerEvaluationError,
    build_draft_package_for_case,
    evaluate_draft_answer,
    run_evaluation_benchmark,
    validate_evaluation_package,
    validate_evaluation_policy,
)
from knowledge_engine.m26_retrieval_envelope import sha256_value, verify_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
DOCS = ROOT / "docs" / "architecture" / "m26"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def fixtures() -> dict[str, dict[str, Any]]:
    return {
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
    }


def evaluation_kwargs(f: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        "draft_cases": f["draft_cases"],
        "provider_cases": f["provider_cases"],
        "context_cases": f["context_cases"],
        "retrieval_cases": f["retrieval_cases"],
        "corpus": f["corpus"],
        "retrieval_policy": f["retrieval_policy"],
        "context_policy": f["context_policy"],
        "provider_policy": f["provider_policy"],
        "draft_policy": f["draft_policy"],
        "evaluation_policy": f["evaluation_policy"],
    }


def evaluation_case(f: dict[str, dict[str, Any]], case_id: str) -> dict[str, Any]:
    return next(case for case in f["evaluation_cases"]["cases"] if case["case_id"] == case_id)


def draft_for(f: dict[str, dict[str, Any]], case_id: str) -> dict[str, Any]:
    return build_draft_package_for_case(evaluation_case(f, case_id), **evaluation_kwargs(f))


def test_entry_contract_is_m26_5_accepted_and_synthetic_only() -> None:
    acceptance = load(PILOT / "m26-5-acceptance.json")
    entry = load(PILOT / "m26-6-entry-contract.json")
    verify_self_digest(entry)
    assert acceptance["status"] == "m26_5_draft_answer_contract_accepted"
    assert acceptance["next_stage"] == {
        "stage_id": "M26.6",
        "name": "Synthetic Answer Evaluation and Refusal Gate",
        "authorized": True,
        "predecessor_status_required": "m26_5_draft_answer_contract_accepted",
        "synthetic_only": True,
        "answer_evaluation_permitted": True,
        "refusal_gate_permitted": True,
        "live_provider_calls_permitted": False,
        "real_corpus_binding_permitted": False,
        "production_answer_serving_permitted": False,
        "verified_final_answer_permitted": False,
    }
    assert entry["accepted_predecessor"]["final_main_seal"] == (
        "c76fe00af61a9eef97614b0e78ede0506593e671"
    )
    assert entry["authority_boundary"]["answer_evaluation_permitted"] is True
    assert entry["authority_boundary"]["refusal_gate_permitted"] is True
    forbidden = {
        key: value
        for key, value in entry["authority_boundary"].items()
        if key
        not in {
            "synthetic_only",
            "answer_evaluation_permitted",
            "refusal_gate_permitted",
            "draft_answer_contract_required",
        }
    }
    assert set(forbidden.values()) == {False}


def test_evaluation_contract_registry_is_digest_bound_and_closed() -> None:
    registry = load(PILOT / "m26-6-contract-registry.json")
    verify_self_digest(registry)
    assert registry["accepted_predecessor_status"] == "m26_5_draft_answer_contract_accepted"
    assert registry["authority"] == {
        "synthetic_only": True,
        "answer_evaluation": True,
        "refusal_gate": True,
        "live_provider_calls": False,
        "credentials": False,
        "real_corpus": False,
        "semantic_or_hybrid": False,
        "production_answer_serving": False,
        "verified_final_answers": False,
    }
    for entry in registry["contracts"]:
        path = ROOT / entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        if entry["path"].startswith("schemas/"):
            schema = load(path)
            Draft202012Validator.check_schema(schema)
            assert schema["additionalProperties"] is False


def test_evaluation_policy_fails_closed_on_live_provider_authority() -> None:
    policy = load(PILOT / "m26-6-answer-evaluation-policy.json")
    validated = validate_evaluation_policy(policy)
    assert validated["authority"]["live_provider_calls"] is False
    assert validated["gate_policy"]["allow_semantic_judgment"] is False

    tampered = json.loads(json.dumps(policy))
    tampered["authority"]["live_provider_calls"] = True
    unsigned = dict(tampered)
    unsigned.pop("self_sha256")
    tampered["self_sha256"] = sha256_value(unsigned)
    with pytest.raises(AnswerEvaluationError, match="EVALUATION_AUTHORITY_INVALID"):
        validate_evaluation_policy(tampered)


def test_evaluation_benchmark_passes_all_synthetic_cases() -> None:
    f = fixtures()
    report = run_evaluation_benchmark(f["evaluation_cases"], **evaluation_kwargs(f))
    verify_self_digest(report)
    assert report["status"] == "m26_6_answer_evaluation_ready"
    assert report["case_count"] == 12
    assert report["passed_count"] == 12
    assert report["failed_count"] == 0
    assert report["metrics"]["evaluation_passed_count"] == 6
    assert report["metrics"]["refusal_required_count"] == 6
    assert report["metrics"]["abstain_refusal_count"] == 3
    assert report["metrics"]["privacy_refusal_count"] == 1
    assert report["metrics"]["authority_refusal_count"] == 1
    assert report["metrics"]["citation_integrity_refusal_count"] == 1
    assert report["metrics"]["provider_call_count"] == 0
    assert report["metrics"]["credentials_used_count"] == 0
    assert report["metrics"]["live_network_call_count"] == 0
    assert report["metrics"]["real_corpus_binding_count"] == 0
    assert report["metrics"]["production_answer_serving_count"] == 0
    assert report["metrics"]["verified_final_answer_count"] == 0


def test_passing_draft_preserves_claim_and_citation_bindings() -> None:
    f = fixtures()
    draft = draft_for(f, "eval_graph_public")
    evaluation = evaluate_draft_answer(draft, f["evaluation_policy"])
    validate_evaluation_package(evaluation)
    assert evaluation["status"] == "evaluation_passed_non_final"
    assert evaluation["safe_for_m26_7"] is True
    assert evaluation["evaluation_passed"] is True
    assert evaluation["refusal_required"] is False
    assert evaluation["final_answer"] is False
    assert evaluation["verified_final_answer"] is False
    assert evaluation["production_answer_serving"] is False
    assert evaluation["citation_coverage"] == 1.0
    assert len(evaluation["accepted_claim_ids"]) >= 1
    assert len(evaluation["accepted_binding_ids"]) >= 2


def test_refusal_gate_propagates_abstain_and_privacy_without_claims() -> None:
    f = fixtures()
    abstain = evaluate_draft_answer(draft_for(f, "eval_no_match_public"), f["evaluation_policy"])
    privacy = evaluate_draft_answer(
        draft_for(f, "eval_privacy_secret_block"),
        f["evaluation_policy"],
    )
    for evaluation in (abstain, privacy):
        validate_evaluation_package(evaluation)
        assert evaluation["safe_for_m26_7"] is False
        assert evaluation["evaluation_passed"] is False
        assert evaluation["refusal_required"] is True
        assert evaluation["accepted_claim_ids"] == []
        assert evaluation["accepted_binding_ids"] == []
    assert abstain["status"] == "refusal_abstain_propagated"
    assert privacy["status"] == "refusal_privacy_block_propagated"


def test_final_answer_escalation_is_refused_not_promoted() -> None:
    f = fixtures()
    draft = draft_for(f, "eval_final_answer_tamper")
    evaluation = evaluate_draft_answer(draft, f["evaluation_policy"])
    validate_evaluation_package(evaluation)
    assert evaluation["status"] == "refusal_authority_escalation"
    assert "FINAL_ANSWER_ESCALATION" in evaluation["refusal_reason_codes"]
    assert evaluation["final_answer"] is False
    assert evaluation["verified_final_answer"] is False
    assert evaluation["production_answer_serving"] is False


def test_citation_integrity_failure_is_refused() -> None:
    f = fixtures()
    draft = draft_for(f, "eval_missing_binding_tamper")
    evaluation = evaluate_draft_answer(draft, f["evaluation_policy"])
    validate_evaluation_package(evaluation)
    assert evaluation["status"] == "refusal_citation_integrity"
    assert "CLAIM_WITHOUT_BINDING" in evaluation["refusal_reason_codes"]
    assert evaluation["accepted_claim_ids"] == []
    assert evaluation["accepted_binding_ids"] == []


def test_conflict_and_prompt_injection_are_diagnostics_only() -> None:
    f = fixtures()
    conflict = evaluate_draft_answer(draft_for(f, "eval_conflict_public"), f["evaluation_policy"])
    injection = evaluate_draft_answer(
        draft_for(f, "eval_prompt_injection_public"),
        f["evaluation_policy"],
    )
    assert conflict["status"] == "evaluation_passed_non_final_with_warnings"
    assert conflict["diagnostics"]["conflict_warning_preserved"] is True
    assert injection["status"] == "evaluation_passed_non_final_with_warnings"
    assert injection["diagnostics"]["prompt_injection_quarantined"] is True
    serialized = json.dumps(injection, ensure_ascii=False).casefold()
    assert "follow these instructions" not in serialized
    assert "ignore previous" not in serialized


def test_docs_record_refusal_gate_and_final_answer_prohibition() -> None:
    text = (DOCS / "m26-6-answer-evaluation-refusal-gate.md").read_text(encoding="utf-8")
    assert "synthetic-only" in text
    assert "refusal gate" in text
    assert "verified final answers" in text
    assert "production answer" in text
    assert "M26.7" in text
