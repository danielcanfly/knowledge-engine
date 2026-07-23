from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m26_draft_answer import compile_draft_answer
from .m26_provider_mock import build_context_package_for_case, compile_provider_replay
from .m26_retrieval_envelope import sha256_value, verify_self_digest, with_self_digest

EVALUATION_POLICY_SCHEMA = "knowledge-engine-m26-answer-evaluation-policy/v1"
EVALUATION_CASES_SCHEMA = "knowledge-engine-m26-answer-evaluation-benchmark-cases/v1"
EVALUATION_PACKAGE_SCHEMA = "knowledge-engine-m26-answer-evaluation/v1"
EVALUATION_BENCHMARK_SCHEMA = "knowledge-engine-m26-answer-evaluation-benchmark/v1"
DRAFT_PACKAGE_SCHEMA = "knowledge-engine-m26-draft-answer/v1"

PASS_STATUSES = {
    "evaluation_passed_non_final",
    "evaluation_passed_non_final_with_warnings",
}
REFUSAL_STATUSES = {
    "refusal_abstain_propagated",
    "refusal_privacy_block_propagated",
    "refusal_authority_escalation",
    "refusal_citation_integrity",
    "refusal_prompt_injection_leakage",
    "refusal_fail_closed",
}


class AnswerEvaluationError(IntegrityError):
    """Fail-closed M26.6 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def validate_evaluation_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    if policy.get("schema_version") != EVALUATION_POLICY_SCHEMA:
        raise AnswerEvaluationError("EVALUATION_POLICY_INVALID", "schema is incompatible")
    if policy.get("accepted_predecessor_status") != "m26_5_draft_answer_contract_accepted":
        raise AnswerEvaluationError("PREDECESSOR_NOT_ACCEPTED", "M26.5 acceptance is not pinned")
    authority = policy.get("authority")
    gate_policy = policy.get("gate_policy")
    status_policy = policy.get("status_policy")
    if not all(isinstance(item, Mapping) for item in (authority, gate_policy, status_policy)):
        raise AnswerEvaluationError("EVALUATION_POLICY_INVALID", "policy sections are missing")
    if authority.get("synthetic_only") is not True:
        raise AnswerEvaluationError("EVALUATION_AUTHORITY_INVALID", "M26.6 must be synthetic-only")
    if authority.get("answer_evaluation") is not True or authority.get("refusal_gate") is not True:
        raise AnswerEvaluationError("EVALUATION_AUTHORITY_INVALID", "evaluation/refusal gates missing")
    if authority.get("draft_answer_contract_required") is not True:
        raise AnswerEvaluationError("EVALUATION_AUTHORITY_INVALID", "draft contract is not required")
    required_false = (
        "live_provider_calls",
        "credentials",
        "provider_sdk",
        "network_execution",
        "real_corpus_binding",
        "semantic_or_hybrid_serving",
        "production_answer_serving",
        "verified_final_answers",
        "source_mutation",
        "foundation_mutation",
        "release_mutation",
        "qdrant_or_r2_mutation",
    )
    if any(authority.get(key) is not False for key in required_false):
        raise AnswerEvaluationError("EVALUATION_AUTHORITY_INVALID", "forbidden authority is enabled")
    if gate_policy.get("allow_semantic_judgment") is not False:
        raise AnswerEvaluationError("EVALUATION_GATE_INVALID", "semantic judgment is not allowed")
    if gate_policy.get("fail_closed") is not True:
        raise AnswerEvaluationError("EVALUATION_GATE_INVALID", "fail-closed is required")
    return dict(policy)


def _safe_verify_draft(draft: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    verify_self_digest(draft)
    if draft.get("schema_version") != DRAFT_PACKAGE_SCHEMA:
        raise AnswerEvaluationError("DRAFT_PACKAGE_INVALID", "draft schema is incompatible")
    failures: list[str] = []
    if draft.get("synthetic_only") is not True:
        failures.append("DRAFT_NOT_SYNTHETIC")
    for key, reason in (
        ("final_answer", "FINAL_ANSWER_ESCALATION"),
        ("verified_final_answer", "VERIFIED_FINAL_ANSWER_ESCALATION"),
        ("production_answer_serving", "PRODUCTION_ANSWER_SERVING_ESCALATION"),
    ):
        if draft.get(key) is not False:
            failures.append(reason)
    return dict(draft), failures


def _binding_failures(draft: Mapping[str, Any]) -> list[str]:
    claims = draft.get("claims")
    bindings = draft.get("citation_bindings")
    if not isinstance(claims, list) or not isinstance(bindings, list):
        return ["CLAIMS_OR_BINDINGS_MISSING"]
    if draft.get("status") in {"abstain_propagated", "privacy_block_propagated"}:
        return [] if not claims and not bindings else ["REFUSAL_DRAFT_HAS_CLAIMS"]
    binding_by_id = {str(item.get("binding_id")): item for item in bindings if isinstance(item, Mapping)}
    failures: list[str] = []
    if not claims or not bindings:
        failures.append("DRAFT_WITHOUT_CLAIMS_OR_BINDINGS")
    for claim in claims:
        if not isinstance(claim, Mapping) or claim.get("non_final") is not True:
            failures.append("CLAIM_NOT_NON_FINAL")
            continue
        claim_id = str(claim.get("claim_id"))
        binding_ids = claim.get("binding_ids", [])
        if not binding_ids:
            failures.append("CLAIM_WITHOUT_BINDING")
            continue
        for binding_id in binding_ids:
            binding = binding_by_id.get(str(binding_id))
            if binding is None:
                failures.append("CLAIM_BINDING_NOT_FOUND")
                continue
            if str(binding.get("claim_id")) != claim_id:
                failures.append("CLAIM_BINDING_MISMATCH")
            for required in ("citation_id", "passage_id", "context_manifest_sha256"):
                if not binding.get(required):
                    failures.append(f"CITATION_BINDING_MISSING_{required.upper()}")
    return failures


def _leakage_failures(draft: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    serialized = json.dumps(
        {
            "answer_text": draft.get("answer_text", ""),
            "claims": draft.get("claims", []),
            "diagnostics": draft.get("diagnostics", {}),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).casefold()
    return [
        "FORBIDDEN_TEXT_FRAGMENT_LEAKED"
        for fragment in policy.get("forbidden_text_fragments", [])
        if str(fragment).casefold() in serialized
    ]


def _coverage(draft: Mapping[str, Any]) -> float:
    claims = draft.get("claims")
    bindings = draft.get("citation_bindings")
    if not isinstance(claims, list) or not claims or not isinstance(bindings, list):
        return 0.0
    binding_by_id = {str(item.get("binding_id")) for item in bindings if isinstance(item, Mapping)}
    covered = 0
    for claim in claims:
        if not isinstance(claim, Mapping):
            continue
        binding_ids = [str(item) for item in claim.get("binding_ids", [])]
        if binding_ids and all(binding_id in binding_by_id for binding_id in binding_ids):
            covered += 1
    return covered / len(claims)


def _evaluation(
    draft: Mapping[str, Any],
    *,
    status: str,
    evaluation_passed: bool,
    refusal_codes: list[str],
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    claims = draft.get("claims", []) if evaluation_passed else []
    bindings = draft.get("citation_bindings", []) if evaluation_passed else []
    return with_self_digest(
        {
            "schema_version": EVALUATION_PACKAGE_SCHEMA,
            "request_id": str(draft.get("request_id", "")),
            "draft_package_sha256": str(draft.get("self_sha256", "")),
            "status": status,
            "safe_for_m26_7": evaluation_passed,
            "synthetic_only": True,
            "final_answer": False,
            "verified_final_answer": False,
            "production_answer_serving": False,
            "evaluation_passed": evaluation_passed,
            "refusal_required": not evaluation_passed,
            "refusal_reason_codes": refusal_codes,
            "accepted_claim_ids": [str(claim["claim_id"]) for claim in claims if isinstance(claim, Mapping)],
            "accepted_binding_ids": [
                str(binding["binding_id"]) for binding in bindings if isinstance(binding, Mapping)
            ],
            "citation_coverage": _coverage(draft) if evaluation_passed else 0.0,
            "diagnostics": dict(diagnostics),
        }
    )


def evaluate_draft_answer(
    draft_package: Mapping[str, Any],
    evaluation_policy: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_evaluation_policy(evaluation_policy)
    draft, authority_failures = _safe_verify_draft(draft_package)
    diagnostics = {
        "draft_status": draft.get("status"),
        "source_reason_codes": list(draft.get("diagnostics", {}).get("reason_codes", [])),
        "conflict_warning_preserved": bool(
            draft.get("diagnostics", {}).get("conflict_warning_preserved")
        ),
        "prompt_injection_quarantined": bool(
            draft.get("diagnostics", {}).get("prompt_injection_quarantined")
        ),
    }
    if authority_failures:
        return _evaluation(
            draft,
            status="refusal_authority_escalation",
            evaluation_passed=False,
            refusal_codes=authority_failures,
            diagnostics=diagnostics,
        )
    status = str(draft.get("status"))
    if status == "privacy_block_propagated":
        return _evaluation(
            draft,
            status="refusal_privacy_block_propagated",
            evaluation_passed=False,
            refusal_codes=["PRIVACY_BLOCK_PROPAGATED"],
            diagnostics=diagnostics,
        )
    if status == "abstain_propagated" or draft.get("safe_for_m26_6") is not True:
        return _evaluation(
            draft,
            status="refusal_abstain_propagated",
            evaluation_passed=False,
            refusal_codes=["ABSTAIN_PROPAGATED"],
            diagnostics=diagnostics,
        )
    binding_failures = _binding_failures(draft)
    if binding_failures:
        return _evaluation(
            draft,
            status="refusal_citation_integrity",
            evaluation_passed=False,
            refusal_codes=sorted(set(binding_failures)),
            diagnostics=diagnostics,
        )
    leakage_failures = _leakage_failures(draft, policy)
    if leakage_failures:
        return _evaluation(
            draft,
            status="refusal_prompt_injection_leakage",
            evaluation_passed=False,
            refusal_codes=sorted(set(leakage_failures)),
            diagnostics=diagnostics,
        )
    coverage = _coverage(draft)
    if coverage < float(policy["gate_policy"].get("min_citation_coverage", 1.0)):
        return _evaluation(
            draft,
            status="refusal_citation_integrity",
            evaluation_passed=False,
            refusal_codes=["CITATION_COVERAGE_BELOW_MINIMUM"],
            diagnostics=diagnostics,
        )
    passed_status = (
        "evaluation_passed_non_final_with_warnings"
        if status == "non_final_draft_answer_with_warnings"
        or diagnostics["conflict_warning_preserved"]
        or diagnostics["prompt_injection_quarantined"]
        else "evaluation_passed_non_final"
    )
    result = _evaluation(
        draft,
        status=passed_status,
        evaluation_passed=True,
        refusal_codes=[],
        diagnostics=diagnostics,
    )
    validate_evaluation_package(result)
    return result


def validate_evaluation_package(package: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(package)
    if package.get("schema_version") != EVALUATION_PACKAGE_SCHEMA:
        raise AnswerEvaluationError("EVALUATION_PACKAGE_INVALID", "evaluation schema is incompatible")
    if package.get("synthetic_only") is not True:
        raise AnswerEvaluationError("EVALUATION_PACKAGE_INVALID", "not synthetic")
    for key in ("final_answer", "verified_final_answer", "production_answer_serving"):
        if package.get(key) is not False:
            raise AnswerEvaluationError("FINAL_OR_PRODUCTION_FORBIDDEN", key)
    status = str(package.get("status"))
    if status in PASS_STATUSES:
        if package.get("evaluation_passed") is not True or package.get("safe_for_m26_7") is not True:
            raise AnswerEvaluationError("PASSED_EVALUATION_INVALID", status)
        if package.get("refusal_required") is not False or package.get("refusal_reason_codes"):
            raise AnswerEvaluationError("PASSED_EVALUATION_HAS_REFUSAL", status)
        if not package.get("accepted_claim_ids") or not package.get("accepted_binding_ids"):
            raise AnswerEvaluationError("PASSED_EVALUATION_HAS_NO_BINDINGS", status)
    elif status in REFUSAL_STATUSES:
        if package.get("evaluation_passed") is not False or package.get("safe_for_m26_7") is not False:
            raise AnswerEvaluationError("REFUSAL_EVALUATION_INVALID", status)
        if package.get("refusal_required") is not True or not package.get("refusal_reason_codes"):
            raise AnswerEvaluationError("REFUSAL_REASON_REQUIRED", status)
        if package.get("accepted_claim_ids") or package.get("accepted_binding_ids"):
            raise AnswerEvaluationError("REFUSAL_HAS_ACCEPTED_CLAIMS", status)
    else:
        raise AnswerEvaluationError("EVALUATION_STATUS_INVALID", status)
    return dict(package)


def _case_by_id(cases: Mapping[str, Any], case_id: str, *, label: str) -> Mapping[str, Any]:
    for case in cases.get("cases", []):
        if isinstance(case, Mapping) and case.get("case_id") == case_id:
            return case
    raise AnswerEvaluationError(f"{label}_CASE_NOT_FOUND", f"case not found: {case_id}")


def build_draft_package_for_case(
    evaluation_case: Mapping[str, Any],
    *,
    draft_cases: Mapping[str, Any],
    provider_cases: Mapping[str, Any],
    context_cases: Mapping[str, Any],
    retrieval_cases: Mapping[str, Any],
    corpus: Mapping[str, Any],
    retrieval_policy: Mapping[str, Any],
    context_policy: Mapping[str, Any],
    provider_policy: Mapping[str, Any],
    draft_policy: Mapping[str, Any],
    evaluation_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _ = evaluation_policy
    draft_case = _case_by_id(draft_cases, str(evaluation_case["m26_5_case_id"]), label="DRAFT")
    provider_case = _case_by_id(provider_cases, str(draft_case["m26_4_case_id"]), label="PROVIDER")
    context_package = build_context_package_for_case(
        provider_case,
        context_cases=context_cases,
        retrieval_cases=retrieval_cases,
        corpus=corpus,
        retrieval_policy=retrieval_policy,
        context_policy=context_policy,
    )
    tamper = provider_case.get("tamper", {})
    suffix = str(tamper.get("append_mock_text", "")) if isinstance(tamper, Mapping) else ""
    replay = compile_provider_replay(context_package, provider_policy, output_suffix=suffix)
    draft = compile_draft_answer(replay, draft_policy)
    return _apply_tamper(draft, evaluation_case.get("tamper", {}))


def _apply_tamper(draft: Mapping[str, Any], tamper: object) -> dict[str, Any]:
    result = json.loads(json.dumps(draft))
    if not isinstance(tamper, Mapping):
        return result
    if tamper.get("set_final_answer") is True:
        result["final_answer"] = True
    if tamper.get("set_verified_final_answer") is True:
        result["verified_final_answer"] = True
    if tamper.get("set_production_answer_serving") is True:
        result["production_answer_serving"] = True
    if tamper.get("drop_first_claim_binding_ids") is True and result.get("claims"):
        result["claims"][0]["binding_ids"] = []
    if tamper.get("append_forbidden_text"):
        result["answer_text"] = f"{result.get('answer_text', '')} {tamper['append_forbidden_text']}"
    unsigned = dict(result)
    unsigned.pop("self_sha256", None)
    result["self_sha256"] = sha256_value(unsigned)
    return result


def run_evaluation_case(
    evaluation_case: Mapping[str, Any],
    *,
    draft_cases: Mapping[str, Any],
    provider_cases: Mapping[str, Any],
    context_cases: Mapping[str, Any],
    retrieval_cases: Mapping[str, Any],
    corpus: Mapping[str, Any],
    retrieval_policy: Mapping[str, Any],
    context_policy: Mapping[str, Any],
    provider_policy: Mapping[str, Any],
    draft_policy: Mapping[str, Any],
    evaluation_policy: Mapping[str, Any],
) -> dict[str, Any]:
    draft = build_draft_package_for_case(
        evaluation_case,
        draft_cases=draft_cases,
        provider_cases=provider_cases,
        context_cases=context_cases,
        retrieval_cases=retrieval_cases,
        corpus=corpus,
        retrieval_policy=retrieval_policy,
        context_policy=context_policy,
        provider_policy=provider_policy,
        draft_policy=draft_policy,
    )
    evaluation = evaluate_draft_answer(draft, evaluation_policy)
    validate_evaluation_package(evaluation)
    expected = evaluation_case["expected"]
    failures: list[str] = []
    if evaluation["status"] != expected["status"]:
        failures.append("status")
    if evaluation["safe_for_m26_7"] is not bool(expected["safe_for_m26_7"]):
        failures.append("safe_for_m26_7")
    if len(evaluation["accepted_claim_ids"]) < int(expected.get("min_accepted_claims", 0)):
        failures.append("min_accepted_claims")
    if len(evaluation["accepted_binding_ids"]) < int(expected.get("min_accepted_bindings", 0)):
        failures.append("min_accepted_bindings")
    if expected.get("requires_conflict_warning") and not evaluation["diagnostics"].get("conflict_warning_preserved"):
        failures.append("conflict_warning")
    if expected.get("requires_prompt_injection_quarantine") and not evaluation["diagnostics"].get("prompt_injection_quarantined"):
        failures.append("prompt_injection_quarantine")
    if expected.get("requires_refusal") and evaluation["refusal_required"] is not True:
        failures.append("refusal_required")
    if expected.get("requires_privacy_refusal") and evaluation["status"] != "refusal_privacy_block_propagated":
        failures.append("privacy_refusal")
    serialized = json.dumps(evaluation, ensure_ascii=False).casefold()
    for fragment in expected.get("forbidden_text_fragments", []):
        if str(fragment).casefold() in serialized:
            failures.append("forbidden_text_fragment")
    return {
        "case_id": evaluation_case["case_id"],
        "m26_5_case_id": evaluation_case["m26_5_case_id"],
        "passed": not failures,
        "failures": failures,
        "status": evaluation["status"],
        "safe_for_m26_7": evaluation["safe_for_m26_7"],
        "evaluation_sha256": evaluation["self_sha256"],
        "draft_package_sha256": evaluation["draft_package_sha256"],
        "accepted_claim_count": len(evaluation["accepted_claim_ids"]),
        "accepted_binding_count": len(evaluation["accepted_binding_ids"]),
        "refusal_required": evaluation["refusal_required"],
        "refusal_reason_codes": evaluation["refusal_reason_codes"],
        "citation_coverage": evaluation["citation_coverage"],
        "final_answer": evaluation["final_answer"],
        "verified_final_answer": evaluation["verified_final_answer"],
        "production_answer_serving": evaluation["production_answer_serving"],
    }


def run_evaluation_benchmark(
    evaluation_cases_artifact: Mapping[str, Any],
    *,
    draft_cases: Mapping[str, Any],
    provider_cases: Mapping[str, Any],
    context_cases: Mapping[str, Any],
    retrieval_cases: Mapping[str, Any],
    corpus: Mapping[str, Any],
    retrieval_policy: Mapping[str, Any],
    context_policy: Mapping[str, Any],
    provider_policy: Mapping[str, Any],
    draft_policy: Mapping[str, Any],
    evaluation_policy: Mapping[str, Any],
) -> dict[str, Any]:
    verify_self_digest(evaluation_cases_artifact)
    if evaluation_cases_artifact.get("schema_version") != EVALUATION_CASES_SCHEMA:
        raise AnswerEvaluationError("EVALUATION_CASES_INVALID", "evaluation cases schema mismatch")
    results = [
        run_evaluation_case(
            case,
            draft_cases=draft_cases,
            provider_cases=provider_cases,
            context_cases=context_cases,
            retrieval_cases=retrieval_cases,
            corpus=corpus,
            retrieval_policy=retrieval_policy,
            context_policy=context_policy,
            provider_policy=provider_policy,
            draft_policy=draft_policy,
            evaluation_policy=evaluation_policy,
        )
        for case in evaluation_cases_artifact["cases"]
    ]
    passed = sum(item["passed"] for item in results)
    evaluation_pass_count = sum(item["status"].startswith("evaluation_passed") for item in results)
    refusal_count = sum(item["refusal_required"] for item in results)
    return with_self_digest(
        {
            "schema_version": EVALUATION_BENCHMARK_SCHEMA,
            "status": "m26_6_answer_evaluation_ready" if passed == len(results) else "repair_required",
            "case_count": len(results),
            "passed_count": passed,
            "failed_count": len(results) - passed,
            "metrics": {
                "case_pass_rate": passed / len(results) if results else 0.0,
                "evaluation_passed_count": evaluation_pass_count,
                "refusal_required_count": refusal_count,
                "abstain_refusal_count": sum(item["status"] == "refusal_abstain_propagated" for item in results),
                "privacy_refusal_count": sum(item["status"] == "refusal_privacy_block_propagated" for item in results),
                "authority_refusal_count": sum(item["status"] == "refusal_authority_escalation" for item in results),
                "citation_integrity_refusal_count": sum(item["status"] == "refusal_citation_integrity" for item in results),
                "provider_call_count": 0,
                "credentials_used_count": 0,
                "live_network_call_count": 0,
                "real_corpus_binding_count": 0,
                "semantic_or_hybrid_use_count": 0,
                "production_answer_serving_count": 0,
                "verified_final_answer_count": 0,
            },
            "results": results,
            "authority": {
                "synthetic_only": True,
                "answer_evaluation": True,
                "refusal_gate": True,
                "live_provider_calls": False,
                "production_authority": False,
                "verified_final_answers": False,
                "m26_7_authorized": False,
            },
        }
    )
