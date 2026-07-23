from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m26_answer_evaluation import (
    PASS_STATUSES,
    REFUSAL_STATUSES,
    build_draft_package_for_case,
    evaluate_draft_answer,
    validate_evaluation_package,
)
from .m26_retrieval_envelope import sha256_value, verify_self_digest, with_self_digest

PRESENTATION_POLICY_SCHEMA = "knowledge-engine-m26-answer-presentation-policy/v1"
PRESENTATION_CASES_SCHEMA = "knowledge-engine-m26-answer-presentation-benchmark-cases/v1"
PRESENTATION_PACKAGE_SCHEMA = "knowledge-engine-m26-answer-presentation/v1"
PRESENTATION_BENCHMARK_SCHEMA = "knowledge-engine-m26-answer-presentation-benchmark/v1"
EVALUATION_PACKAGE_SCHEMA = "knowledge-engine-m26-answer-evaluation/v1"

PREVIEW_STATUSES = {
    "non_serving_preview_available",
    "non_serving_preview_with_warnings",
    "non_serving_refusal_preview",
}


class AnswerPresentationError(IntegrityError):
    """Fail-closed M26.7 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def validate_presentation_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    if policy.get("schema_version") != PRESENTATION_POLICY_SCHEMA:
        raise AnswerPresentationError("PRESENTATION_POLICY_INVALID", "schema is incompatible")
    if policy.get("accepted_predecessor_status") != "m26_6_answer_evaluation_refusal_gate_accepted":
        raise AnswerPresentationError("PREDECESSOR_NOT_ACCEPTED", "M26.6 acceptance is not pinned")
    authority = policy.get("authority")
    surface_policy = policy.get("surface_policy")
    status_policy = policy.get("status_policy")
    if not all(isinstance(item, Mapping) for item in (authority, surface_policy, status_policy)):
        raise AnswerPresentationError("PRESENTATION_POLICY_INVALID", "policy sections are missing")
    if authority.get("synthetic_only") is not True:
        raise AnswerPresentationError("PRESENTATION_AUTHORITY_INVALID", "M26.7 must be synthetic")
    if authority.get("presentation_contract") is not True:
        raise AnswerPresentationError("PRESENTATION_AUTHORITY_INVALID", "presentation contract missing")
    if authority.get("non_serving_preview") is not True:
        raise AnswerPresentationError("PRESENTATION_AUTHORITY_INVALID", "non-serving preview missing")
    if authority.get("answer_evaluation_required") is not True:
        raise AnswerPresentationError("PRESENTATION_AUTHORITY_INVALID", "evaluation input not required")
    required_false = (
        "live_provider_calls",
        "credentials",
        "provider_sdk",
        "network_execution",
        "real_corpus_binding",
        "semantic_or_hybrid_serving",
        "production_answer_serving",
        "verified_final_answers",
        "production_pointer_mutation",
        "source_mutation",
        "foundation_mutation",
        "release_mutation",
        "qdrant_or_r2_mutation",
    )
    if any(authority.get(key) is not False for key in required_false):
        raise AnswerPresentationError("PRESENTATION_AUTHORITY_INVALID", "forbidden authority enabled")
    if surface_policy.get("preview_only") is not True:
        raise AnswerPresentationError("PRESENTATION_SURFACE_INVALID", "preview-only is required")
    if surface_policy.get("allow_final_answer_text") is not False:
        raise AnswerPresentationError("PRESENTATION_SURFACE_INVALID", "final answer text is allowed")
    if surface_policy.get("refusals_have_no_claims") is not True:
        raise AnswerPresentationError("PRESENTATION_SURFACE_INVALID", "refusals must not show claims")
    return dict(policy)


def _authority_failures(evaluation: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if evaluation.get("synthetic_only") is not True:
        failures.append("EVALUATION_NOT_SYNTHETIC")
    for key, reason in (
        ("final_answer", "FINAL_ANSWER_ESCALATION"),
        ("verified_final_answer", "VERIFIED_FINAL_ANSWER_ESCALATION"),
        ("production_answer_serving", "PRODUCTION_ANSWER_SERVING_ESCALATION"),
        ("real_corpus_binding", "REAL_CORPUS_BINDING_ESCALATION"),
        ("production_pointer_mutation", "PRODUCTION_POINTER_ESCALATION"),
    ):
        if evaluation.get(key) is not False and key in evaluation:
            failures.append(reason)
    return failures


def _warning_codes(evaluation: Mapping[str, Any]) -> list[str]:
    diagnostics = evaluation.get("diagnostics", {})
    warnings: list[str] = []
    if isinstance(diagnostics, Mapping):
        if diagnostics.get("conflict_warning_preserved"):
            warnings.append("conflict_warning")
        if diagnostics.get("prompt_injection_quarantined"):
            warnings.append("prompt_injection_quarantined")
    return warnings


def _display_claims(evaluation: Mapping[str, Any], policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    max_claims = int(policy["surface_policy"].get("max_preview_claims", 6))
    claim_ids = [str(item) for item in evaluation.get("accepted_claim_ids", [])][:max_claims]
    binding_ids = [str(item) for item in evaluation.get("accepted_binding_ids", [])]
    display: list[dict[str, Any]] = []
    for index, claim_id in enumerate(claim_ids, start=1):
        display.append(
            {
                "display_claim_id": claim_id,
                "ordinal": index,
                "binding_ids": binding_ids,
                "content_redacted": True,
                "text": "",
            }
        )
    return display


def _surface_blocks(
    evaluation: Mapping[str, Any],
    *,
    status: str,
    warning_codes: list[str],
    refusal_codes: list[str],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {
            "block_type": "status_banner",
            "code": status,
            "preview_only": True,
            "text": "",
        },
        {
            "block_type": "non_serving_notice",
            "code": "NON_SERVING_PREVIEW_NOT_FINAL",
            "preview_only": True,
            "text": "",
        },
    ]
    if refusal_codes:
        blocks.append(
            {
                "block_type": "refusal_banner",
                "codes": refusal_codes,
                "preview_only": True,
                "text": "",
            }
        )
    for code in warning_codes:
        blocks.append(
            {
                "block_type": "warning_banner",
                "code": code,
                "preview_only": True,
                "text": "",
            }
        )
    return blocks


def compile_presentation_preview(
    evaluation_package: Mapping[str, Any],
    presentation_policy: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_presentation_policy(presentation_policy)
    evaluation = dict(evaluation_package)
    authority_failures = _authority_failures(evaluation)
    if not authority_failures:
        validate_evaluation_package(evaluation)
    status = str(evaluation.get("status"))
    warning_codes = _warning_codes(evaluation)
    refusal_codes = list(evaluation.get("refusal_reason_codes", []))
    presentation_status: str
    display_claims: list[dict[str, Any]]
    display_bindings: list[str]
    if authority_failures:
        presentation_status = policy["status_policy"]["authority_rejected_status"]
        refusal_codes = sorted(set(authority_failures))
        display_claims = []
        display_bindings = []
    elif status in PASS_STATUSES and evaluation.get("safe_for_m26_7") is True:
        presentation_status = (
            policy["status_policy"]["warning_preview_status"]
            if warning_codes
            else policy["status_policy"]["passed_preview_status"]
        )
        display_claims = _display_claims(evaluation, policy)
        display_bindings = [str(item) for item in evaluation.get("accepted_binding_ids", [])]
    elif status in REFUSAL_STATUSES or evaluation.get("refusal_required") is True:
        presentation_status = policy["status_policy"]["refusal_preview_status"]
        refusal_codes = refusal_codes or [status.upper()]
        display_claims = []
        display_bindings = []
    else:
        presentation_status = policy["status_policy"]["authority_rejected_status"]
        refusal_codes = ["UNSUPPORTED_EVALUATION_STATUS"]
        display_claims = []
        display_bindings = []
    package = with_self_digest(
        {
            "schema_version": PRESENTATION_PACKAGE_SCHEMA,
            "request_id": str(evaluation.get("request_id", "")),
            "evaluation_package_sha256": str(evaluation.get("self_sha256", "")),
            "draft_package_sha256": str(evaluation.get("draft_package_sha256", "")),
            "presentation_status": presentation_status,
            "preview_only": True,
            "non_serving_preview": True,
            "safe_for_m26_8": True,
            "synthetic_only": True,
            "final_answer": False,
            "verified_final_answer": False,
            "production_answer_serving": False,
            "production_pointer_mutation": False,
            "answer_text": "",
            "display_claims": display_claims,
            "display_binding_ids": display_bindings,
            "warning_banners": warning_codes,
            "refusal_reason_codes": refusal_codes,
            "surface_blocks": _surface_blocks(
                evaluation,
                status=presentation_status,
                warning_codes=warning_codes,
                refusal_codes=refusal_codes,
            ),
            "diagnostics": {
                "evaluation_status": status,
                "evaluation_passed": bool(evaluation.get("evaluation_passed")),
                "refusal_required": bool(evaluation.get("refusal_required")),
                "citation_coverage": float(evaluation.get("citation_coverage", 0.0)),
            },
        }
    )
    validate_presentation_package(package)
    return package


def validate_presentation_package(package: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(package)
    if package.get("schema_version") != PRESENTATION_PACKAGE_SCHEMA:
        raise AnswerPresentationError("PRESENTATION_PACKAGE_INVALID", "schema is incompatible")
    for key in ("preview_only", "non_serving_preview", "synthetic_only", "safe_for_m26_8"):
        if package.get(key) is not True:
            raise AnswerPresentationError("PRESENTATION_PACKAGE_INVALID", key)
    for key in ("final_answer", "verified_final_answer", "production_answer_serving"):
        if package.get(key) is not False:
            raise AnswerPresentationError("FINAL_OR_PRODUCTION_FORBIDDEN", key)
    if package.get("production_pointer_mutation") is not False:
        raise AnswerPresentationError("PRODUCTION_POINTER_FORBIDDEN", "pointer mutation enabled")
    if package.get("answer_text"):
        raise AnswerPresentationError("ANSWER_TEXT_FORBIDDEN", "preview contains answer text")
    status = str(package.get("presentation_status"))
    if status not in PREVIEW_STATUSES and status != "presentation_rejected_authority_escalation":
        raise AnswerPresentationError("PRESENTATION_STATUS_INVALID", status)
    display_claims = package.get("display_claims")
    display_bindings = package.get("display_binding_ids")
    if not isinstance(display_claims, list) or not isinstance(display_bindings, list):
        raise AnswerPresentationError("PRESENTATION_PACKAGE_INVALID", "display identities missing")
    if status.startswith("non_serving_preview"):
        if not display_claims or not display_bindings:
            raise AnswerPresentationError("PREVIEW_MISSING_IDENTITIES", status)
        for claim in display_claims:
            if not isinstance(claim, Mapping) or claim.get("content_redacted") is not True:
                raise AnswerPresentationError("DISPLAY_CLAIM_INVALID", "claim content not redacted")
            if claim.get("text"):
                raise AnswerPresentationError("DISPLAY_CLAIM_TEXT_FORBIDDEN", str(claim))
    else:
        if display_claims or display_bindings:
            raise AnswerPresentationError("REFUSAL_PREVIEW_HAS_CLAIMS", status)
        if not package.get("refusal_reason_codes"):
            raise AnswerPresentationError("REFUSAL_CODES_REQUIRED", status)
    return dict(package)


def _case_by_id(cases: Mapping[str, Any], case_id: str, *, label: str) -> Mapping[str, Any]:
    for case in cases.get("cases", []):
        if isinstance(case, Mapping) and case.get("case_id") == case_id:
            return case
    raise AnswerPresentationError(f"{label}_CASE_NOT_FOUND", f"case not found: {case_id}")


def _apply_evaluation_tamper(evaluation: Mapping[str, Any], tamper: object) -> dict[str, Any]:
    result = json.loads(json.dumps(evaluation))
    if not isinstance(tamper, Mapping):
        return result
    if tamper.get("set_final_answer") is True:
        result["final_answer"] = True
    if tamper.get("set_verified_final_answer") is True:
        result["verified_final_answer"] = True
    if tamper.get("set_production_answer_serving") is True:
        result["production_answer_serving"] = True
    if tamper.get("set_real_corpus_binding") is True:
        result["real_corpus_binding"] = True
    unsigned = dict(result)
    unsigned.pop("self_sha256", None)
    result["self_sha256"] = sha256_value(unsigned)
    return result


def build_evaluation_package_for_case(
    presentation_case: Mapping[str, Any],
    *,
    evaluation_cases: Mapping[str, Any],
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
    evaluation_case = _case_by_id(
        evaluation_cases,
        str(presentation_case["m26_6_case_id"]),
        label="EVALUATION",
    )
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
    return _apply_evaluation_tamper(evaluation, presentation_case.get("tamper", {}))


def run_presentation_case(
    presentation_case: Mapping[str, Any],
    *,
    evaluation_cases: Mapping[str, Any],
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
    presentation_policy: Mapping[str, Any],
) -> dict[str, Any]:
    evaluation = build_evaluation_package_for_case(
        presentation_case,
        evaluation_cases=evaluation_cases,
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
    preview = compile_presentation_preview(evaluation, presentation_policy)
    expected = presentation_case["expected"]
    failures: list[str] = []
    if preview["presentation_status"] != expected["status"]:
        failures.append("status")
    if preview["safe_for_m26_8"] is not bool(expected["safe_for_m26_8"]):
        failures.append("safe_for_m26_8")
    if len(preview["display_claims"]) < int(expected.get("min_display_claims", 0)):
        failures.append("min_display_claims")
    if len(preview["display_binding_ids"]) < int(expected.get("min_display_bindings", 0)):
        failures.append("min_display_bindings")
    if expected.get("requires_refusal_preview") and not preview["refusal_reason_codes"]:
        failures.append("refusal_preview")
    if expected.get("requires_conflict_warning") and "conflict_warning" not in preview["warning_banners"]:
        failures.append("conflict_warning")
    if (
        expected.get("requires_prompt_injection_warning")
        and "prompt_injection_quarantined" not in preview["warning_banners"]
    ):
        failures.append("prompt_injection_warning")
    serialized = json.dumps(preview, ensure_ascii=False).casefold()
    for fragment in expected.get("forbidden_text_fragments", []):
        if str(fragment).casefold() in serialized:
            failures.append("forbidden_text_fragment")
    return {
        "case_id": presentation_case["case_id"],
        "m26_6_case_id": presentation_case["m26_6_case_id"],
        "passed": not failures,
        "failures": failures,
        "presentation_status": preview["presentation_status"],
        "safe_for_m26_8": preview["safe_for_m26_8"],
        "presentation_sha256": preview["self_sha256"],
        "evaluation_package_sha256": preview["evaluation_package_sha256"],
        "display_claim_count": len(preview["display_claims"]),
        "display_binding_count": len(preview["display_binding_ids"]),
        "warning_count": len(preview["warning_banners"]),
        "refusal_preview": bool(preview["refusal_reason_codes"]),
        "final_answer": preview["final_answer"],
        "verified_final_answer": preview["verified_final_answer"],
        "production_answer_serving": preview["production_answer_serving"],
        "production_pointer_mutation": preview["production_pointer_mutation"],
    }


def run_presentation_benchmark(
    presentation_cases_artifact: Mapping[str, Any],
    *,
    evaluation_cases: Mapping[str, Any],
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
    presentation_policy: Mapping[str, Any],
) -> dict[str, Any]:
    verify_self_digest(presentation_cases_artifact)
    if presentation_cases_artifact.get("schema_version") != PRESENTATION_CASES_SCHEMA:
        raise AnswerPresentationError("PRESENTATION_CASES_INVALID", "cases schema mismatch")
    results = [
        run_presentation_case(
            case,
            evaluation_cases=evaluation_cases,
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
            presentation_policy=presentation_policy,
        )
        for case in presentation_cases_artifact["cases"]
    ]
    passed = sum(item["passed"] for item in results)
    preview_count = sum(item["presentation_status"].startswith("non_serving_preview") for item in results)
    refusal_count = sum(item["presentation_status"] == "non_serving_refusal_preview" for item in results)
    warning_count = sum(item["warning_count"] > 0 for item in results)
    return with_self_digest(
        {
            "schema_version": PRESENTATION_BENCHMARK_SCHEMA,
            "status": "m26_7_answer_presentation_ready" if passed == len(results) else "repair_required",
            "case_count": len(results),
            "passed_count": passed,
            "failed_count": len(results) - passed,
            "metrics": {
                "case_pass_rate": passed / len(results) if results else 0.0,
                "non_serving_preview_count": preview_count,
                "non_serving_refusal_preview_count": refusal_count,
                "warning_preview_count": warning_count,
                "provider_call_count": 0,
                "credentials_used_count": 0,
                "live_network_call_count": 0,
                "real_corpus_binding_count": 0,
                "semantic_or_hybrid_use_count": 0,
                "production_answer_serving_count": 0,
                "verified_final_answer_count": 0,
                "production_pointer_mutation_count": 0,
            },
            "results": results,
            "authority": {
                "synthetic_only": True,
                "presentation_contract": True,
                "non_serving_preview": True,
                "live_provider_calls": False,
                "production_authority": False,
                "verified_final_answers": False,
                "m26_8_authorized": False,
            },
        }
    )
