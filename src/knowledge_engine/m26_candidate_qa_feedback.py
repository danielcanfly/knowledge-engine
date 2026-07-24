from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m26_preview_candidate_bundle import (
    build_presentation_package_for_case,
    compile_candidate_record,
    validate_candidate_record,
)
from .m26_retrieval_envelope import sha256_value, verify_self_digest, with_self_digest

QA_POLICY_SCHEMA = "knowledge-engine-m26-candidate-qa-policy/v1"
QA_CASES_SCHEMA = "knowledge-engine-m26-candidate-qa-benchmark-cases/v1"
QA_FEEDBACK_SCHEMA = "knowledge-engine-m26-candidate-qa-feedback/v1"
BASELINE_PLAN_SCHEMA = "knowledge-engine-m26-baseline-refresh-plan/v1"
QA_BENCHMARK_SCHEMA = "knowledge-engine-m26-candidate-qa-benchmark/v1"

QA_STATUSES = {
    "qa_feedback_ready",
    "qa_feedback_ready_with_warnings",
    "qa_refusal_feedback_ready",
    "qa_rejected_authority_escalation",
}


class CandidateQAFeedbackError(IntegrityError):
    """Fail-closed M26.9 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def validate_qa_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    if policy.get("schema_version") != QA_POLICY_SCHEMA:
        raise CandidateQAFeedbackError("QA_POLICY_INVALID", "schema is incompatible")
    if policy.get("accepted_predecessor_status") != "m26_8_preview_evidence_candidate_bundle_accepted":
        raise CandidateQAFeedbackError("PREDECESSOR_NOT_ACCEPTED", "M26.8 is not pinned")
    authority = policy.get("authority")
    feedback_policy = policy.get("feedback_policy")
    status_policy = policy.get("status_policy")
    if not all(isinstance(item, Mapping) for item in (authority, feedback_policy, status_policy)):
        raise CandidateQAFeedbackError("QA_POLICY_INVALID", "sections are missing")
    for key in (
        "synthetic_only",
        "candidate_bundle_review",
        "baseline_refresh_planning",
        "candidate_bundle_required",
    ):
        if authority.get(key) is not True:
            raise CandidateQAFeedbackError("QA_AUTHORITY_INVALID", key)
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
        "baseline_refresh_execution",
        "source_mutation",
        "foundation_mutation",
        "release_mutation",
        "qdrant_or_r2_mutation",
    )
    if any(authority.get(key) is not False for key in required_false):
        raise CandidateQAFeedbackError("QA_AUTHORITY_INVALID", "forbidden authority")
    if feedback_policy.get("planning_only") is not True:
        raise CandidateQAFeedbackError("QA_FEEDBACK_POLICY_INVALID", "planning-only required")
    if feedback_policy.get("allow_answer_text") is not False:
        raise CandidateQAFeedbackError("QA_FEEDBACK_POLICY_INVALID", "answer text allowed")
    if feedback_policy.get("refusals_have_no_claims") is not True:
        raise CandidateQAFeedbackError("QA_FEEDBACK_POLICY_INVALID", "refusal claims allowed")
    return dict(policy)


def _authority_failures(record: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    for key, reason in (
        ("synthetic_only", "CANDIDATE_NOT_SYNTHETIC"),
        ("candidate_only", "CANDIDATE_ONLY_MISSING"),
        ("preview_only", "PREVIEW_ONLY_MISSING"),
        ("non_serving_preview", "NON_SERVING_PREVIEW_MISSING"),
        ("safe_for_m26_9", "CANDIDATE_NOT_SAFE_FOR_M26_9"),
    ):
        if record.get(key) is not True:
            failures.append(reason)
    for key, reason in (
        ("final_answer", "FINAL_ANSWER_ESCALATION"),
        ("verified_final_answer", "VERIFIED_FINAL_ANSWER_ESCALATION"),
        ("production_answer_serving", "PRODUCTION_ANSWER_SERVING_ESCALATION"),
        ("production_pointer_mutation", "PRODUCTION_POINTER_ESCALATION"),
        ("real_corpus_binding", "REAL_CORPUS_BINDING_ESCALATION"),
        ("baseline_refresh_execution", "BASELINE_REFRESH_EXECUTION_ESCALATION"),
    ):
        if key in record and record.get(key) is not False:
            failures.append(reason)
    if record.get("answer_text"):
        failures.append("ANSWER_TEXT_LEAKAGE")
    return failures


def _forbidden_text_failures(feedback: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    serialized = json.dumps(
        {
            "answer_text": feedback.get("answer_text", ""),
            "review_claim_ids": feedback.get("review_claim_ids", []),
            "qa_findings": feedback.get("qa_findings", []),
            "warning_identities": feedback.get("warning_identities", []),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).casefold()
    return [
        "FORBIDDEN_TEXT_FRAGMENT_LEAKED"
        for fragment in policy["feedback_policy"].get("forbidden_text_fragments", [])
        if str(fragment).casefold() in serialized
    ]


def review_candidate_record(
    candidate_record: Mapping[str, Any],
    qa_policy: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_qa_policy(qa_policy)
    record = dict(candidate_record)
    authority_failures = _authority_failures(record)
    if not authority_failures:
        validate_candidate_record(record)
    candidate_status = str(record.get("candidate_record_status"))
    warning_identities = [str(item) for item in record.get("warning_banners", [])]
    refusal_codes = [str(item) for item in record.get("refusal_reason_codes", [])]
    status_policy = policy["status_policy"]
    if authority_failures:
        qa_status = status_policy["authority_rejected_status"]
        review_claim_ids: list[str] = []
        review_binding_ids: list[str] = []
        refusal_codes = sorted(set(authority_failures))
        baseline_action = "block_baseline_refresh_plan"
    elif candidate_status.startswith("candidate_preview_record"):
        qa_status = (
            status_policy["warning_feedback_status"]
            if warning_identities
            else status_policy["feedback_ready_status"]
        )
        max_claims = int(policy["feedback_policy"].get("max_feedback_claims", 6))
        review_claim_ids = [str(item) for item in record.get("candidate_claim_ids", [])][:max_claims]
        review_binding_ids = [str(item) for item in record.get("candidate_binding_ids", [])]
        baseline_action = "plan_synthetic_baseline_refresh_review"
    elif candidate_status == "candidate_refusal_record":
        qa_status = status_policy["refusal_feedback_status"]
        review_claim_ids = []
        review_binding_ids = []
        refusal_codes = refusal_codes or [candidate_status.upper()]
        baseline_action = "preserve_refusal_without_baseline_refresh"
    else:
        qa_status = status_policy["authority_rejected_status"]
        review_claim_ids = []
        review_binding_ids = []
        refusal_codes = ["UNSUPPORTED_CANDIDATE_STATUS"]
        baseline_action = "block_baseline_refresh_plan"
    feedback = with_self_digest(
        {
            "schema_version": QA_FEEDBACK_SCHEMA,
            "request_id": str(record.get("request_id", "")),
            "candidate_record_sha256": str(record.get("self_sha256", "")),
            "presentation_package_sha256": str(record.get("presentation_package_sha256", "")),
            "evaluation_package_sha256": str(record.get("evaluation_package_sha256", "")),
            "draft_package_sha256": str(record.get("draft_package_sha256", "")),
            "qa_feedback_status": qa_status,
            "planning_only": True,
            "candidate_bundle_review": True,
            "baseline_refresh_planning": True,
            "baseline_refresh_execution": False,
            "safe_for_m26_10": True,
            "synthetic_only": True,
            "final_answer": False,
            "verified_final_answer": False,
            "production_answer_serving": False,
            "production_pointer_mutation": False,
            "real_corpus_binding": False,
            "answer_text": "",
            "review_claim_ids": review_claim_ids,
            "review_binding_ids": review_binding_ids,
            "warning_identities": warning_identities,
            "refusal_reason_codes": refusal_codes,
            "qa_findings": [
                "candidate_identity_bound" if review_claim_ids else "no_candidate_claims_accepted",
                "baseline_refresh_planning_only",
            ],
            "baseline_refresh_plan": {
                "plan_status": "planning_only",
                "candidate_record_action": baseline_action,
                "execution": False,
                "planning_only": True,
            },
            "diagnostics": {
                "candidate_record_status": candidate_status,
                "warning_count": len(warning_identities),
                "refusal_count": len(refusal_codes),
                "authority_rejection": bool(authority_failures),
            },
        }
    )
    validate_qa_feedback(feedback, qa_policy)
    return feedback


def validate_qa_feedback(
    feedback: Mapping[str, Any],
    qa_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    verify_self_digest(feedback)
    if feedback.get("schema_version") != QA_FEEDBACK_SCHEMA:
        raise CandidateQAFeedbackError("QA_FEEDBACK_INVALID", "schema is incompatible")
    status = str(feedback.get("qa_feedback_status"))
    if status not in QA_STATUSES:
        raise CandidateQAFeedbackError("QA_FEEDBACK_STATUS_INVALID", status)
    for key in (
        "planning_only",
        "candidate_bundle_review",
        "baseline_refresh_planning",
        "synthetic_only",
        "safe_for_m26_10",
    ):
        if feedback.get(key) is not True:
            raise CandidateQAFeedbackError("QA_FEEDBACK_INVALID", key)
    for key in (
        "baseline_refresh_execution",
        "final_answer",
        "verified_final_answer",
        "production_answer_serving",
        "production_pointer_mutation",
        "real_corpus_binding",
    ):
        if feedback.get(key) is not False:
            raise CandidateQAFeedbackError("QA_AUTHORITY_ESCALATION", key)
    if feedback.get("answer_text"):
        raise CandidateQAFeedbackError("ANSWER_TEXT_FORBIDDEN", "QA feedback contains answer text")
    claim_ids = feedback.get("review_claim_ids")
    binding_ids = feedback.get("review_binding_ids")
    if not isinstance(claim_ids, list) or not isinstance(binding_ids, list):
        raise CandidateQAFeedbackError("QA_IDENTITIES_MISSING", status)
    if status.startswith("qa_feedback_ready"):
        if not claim_ids or not binding_ids:
            raise CandidateQAFeedbackError("QA_FEEDBACK_MISSING_IDENTITIES", status)
        if feedback.get("refusal_reason_codes"):
            raise CandidateQAFeedbackError("QA_FEEDBACK_HAS_REFUSAL", status)
    else:
        if claim_ids or binding_ids:
            raise CandidateQAFeedbackError("QA_REFUSAL_HAS_IDENTITIES", status)
        if not feedback.get("refusal_reason_codes"):
            raise CandidateQAFeedbackError("QA_REFUSAL_CODES_REQUIRED", status)
    plan = feedback.get("baseline_refresh_plan")
    if not isinstance(plan, Mapping) or plan.get("execution") is not False:
        raise CandidateQAFeedbackError("BASELINE_PLAN_INVALID", status)
    if qa_policy is not None:
        policy = validate_qa_policy(qa_policy)
        failures = _forbidden_text_failures(feedback, policy)
        if failures:
            raise CandidateQAFeedbackError("QA_FORBIDDEN_TEXT_LEAKED", ",".join(failures))
    return dict(feedback)


def compile_baseline_refresh_plan(
    feedback_records: list[Mapping[str, Any]],
    qa_policy: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_qa_policy(qa_policy)
    records = [validate_qa_feedback(feedback, policy) for feedback in feedback_records]
    feedback_ready = [r for r in records if str(r["qa_feedback_status"]).startswith("qa_feedback_ready")]
    refusal_ready = [r for r in records if r["qa_feedback_status"] == "qa_refusal_feedback_ready"]
    rejected = [r for r in records if r["qa_feedback_status"] == "qa_rejected_authority_escalation"]
    return with_self_digest(
        {
            "schema_version": BASELINE_PLAN_SCHEMA,
            "status": policy["status_policy"]["baseline_plan_ready_status"],
            "planning_only": True,
            "synthetic_only": True,
            "candidate_bundle_review": True,
            "baseline_refresh_planning": True,
            "baseline_refresh_execution": False,
            "final_answer": False,
            "verified_final_answer": False,
            "production_answer_serving": False,
            "production_pointer_mutation": False,
            "real_corpus_binding": False,
            "record_count": len(records),
            "feedback_ready_count": len(feedback_ready),
            "refusal_feedback_count": len(refusal_ready),
            "rejected_feedback_count": len(rejected),
            "warning_feedback_count": sum(bool(r["warning_identities"]) for r in records),
            "qa_feedback_sha256s": [str(record["self_sha256"]) for record in records],
            "review_claim_ids": sorted(
                {str(claim_id) for record in feedback_ready for claim_id in record["review_claim_ids"]}
            ),
            "review_binding_ids": sorted(
                {str(binding_id) for record in feedback_ready for binding_id in record["review_binding_ids"]}
            ),
        }
    )


def validate_baseline_refresh_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(plan)
    if plan.get("schema_version") != BASELINE_PLAN_SCHEMA:
        raise CandidateQAFeedbackError("BASELINE_PLAN_INVALID", "schema is incompatible")
    if plan.get("status") != "m26_9_baseline_refresh_plan_ready":
        raise CandidateQAFeedbackError("BASELINE_PLAN_STATUS_INVALID", str(plan.get("status")))
    for key in (
        "planning_only",
        "synthetic_only",
        "candidate_bundle_review",
        "baseline_refresh_planning",
    ):
        if plan.get(key) is not True:
            raise CandidateQAFeedbackError("BASELINE_PLAN_INVALID", key)
    for key in (
        "baseline_refresh_execution",
        "final_answer",
        "verified_final_answer",
        "production_answer_serving",
        "production_pointer_mutation",
        "real_corpus_binding",
    ):
        if plan.get(key) is not False:
            raise CandidateQAFeedbackError("BASELINE_PLAN_AUTHORITY_ESCALATION", key)
    if int(plan.get("record_count", 0)) <= 0:
        raise CandidateQAFeedbackError("BASELINE_PLAN_EMPTY", "no records")
    return dict(plan)


def _case_by_id(cases: Mapping[str, Any], case_id: str, *, label: str) -> Mapping[str, Any]:
    for case in cases.get("cases", []):
        if isinstance(case, Mapping) and case.get("case_id") == case_id:
            return case
    raise CandidateQAFeedbackError(f"{label}_CASE_NOT_FOUND", f"case not found: {case_id}")


def _apply_candidate_tamper(record: Mapping[str, Any], tamper: object) -> dict[str, Any]:
    result = json.loads(json.dumps(record))
    if not isinstance(tamper, Mapping):
        return result
    if tamper.get("set_final_answer") is True:
        result["final_answer"] = True
    if tamper.get("set_verified_final_answer") is True:
        result["verified_final_answer"] = True
    if tamper.get("set_production_answer_serving") is True:
        result["production_answer_serving"] = True
    if tamper.get("set_production_pointer_mutation") is True:
        result["production_pointer_mutation"] = True
    if tamper.get("set_real_corpus_binding") is True:
        result["real_corpus_binding"] = True
    if tamper.get("set_baseline_refresh_execution") is True:
        result["baseline_refresh_execution"] = True
    if tamper.get("append_answer_text"):
        result["answer_text"] = f"{result.get('answer_text', '')} {tamper['append_answer_text']}"
    unsigned = dict(result)
    unsigned.pop("self_sha256", None)
    result["self_sha256"] = sha256_value(unsigned)
    return result


def build_candidate_record_for_qa_case(
    qa_case: Mapping[str, Any],
    *,
    candidate_cases: Mapping[str, Any],
    presentation_cases: Mapping[str, Any],
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
    candidate_policy: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_case = _case_by_id(candidate_cases, str(qa_case["m26_8_case_id"]), label="CANDIDATE")
    preview = build_presentation_package_for_case(
        candidate_case,
        presentation_cases=presentation_cases,
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
    record = compile_candidate_record(preview, candidate_policy)
    return _apply_candidate_tamper(record, qa_case.get("tamper", {}))


def run_qa_case(
    qa_case: Mapping[str, Any],
    *,
    candidate_cases: Mapping[str, Any],
    presentation_cases: Mapping[str, Any],
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
    candidate_policy: Mapping[str, Any],
    qa_policy: Mapping[str, Any],
) -> dict[str, Any]:
    record = build_candidate_record_for_qa_case(
        qa_case,
        candidate_cases=candidate_cases,
        presentation_cases=presentation_cases,
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
        candidate_policy=candidate_policy,
    )
    feedback = review_candidate_record(record, qa_policy)
    expected = qa_case["expected"]
    failures: list[str] = []
    if feedback["qa_feedback_status"] != expected["status"]:
        failures.append("status")
    if feedback["safe_for_m26_10"] is not bool(expected.get("safe_for_m26_10", True)):
        failures.append("safe_for_m26_10")
    if len(feedback["review_claim_ids"]) < int(expected.get("min_feedback_claims", 0)):
        failures.append("min_feedback_claims")
    if len(feedback["review_binding_ids"]) < int(expected.get("min_feedback_bindings", 0)):
        failures.append("min_feedback_bindings")
    if expected.get("requires_refusal_feedback") and not feedback["refusal_reason_codes"]:
        failures.append("refusal_feedback")
    if expected.get("requires_conflict_warning") and "conflict_warning" not in feedback["warning_identities"]:
        failures.append("conflict_warning")
    if (
        expected.get("requires_prompt_injection_warning")
        and "prompt_injection_quarantined" not in feedback["warning_identities"]
    ):
        failures.append("prompt_injection_warning")
    serialized = json.dumps(feedback, ensure_ascii=False).casefold()
    for fragment in expected.get("forbidden_text_fragments", []):
        if str(fragment).casefold() in serialized:
            failures.append("forbidden_text_fragment")
    return {
        "case_id": qa_case["case_id"],
        "m26_8_case_id": qa_case["m26_8_case_id"],
        "passed": not failures,
        "failures": failures,
        "qa_feedback_status": feedback["qa_feedback_status"],
        "safe_for_m26_10": feedback["safe_for_m26_10"],
        "qa_feedback_sha256": feedback["self_sha256"],
        "candidate_record_sha256": feedback["candidate_record_sha256"],
        "review_claim_count": len(feedback["review_claim_ids"]),
        "review_binding_count": len(feedback["review_binding_ids"]),
        "warning_count": len(feedback["warning_identities"]),
        "refusal_feedback": bool(feedback["refusal_reason_codes"]),
        "baseline_refresh_execution": feedback["baseline_refresh_execution"],
        "production_answer_serving": feedback["production_answer_serving"],
        "production_pointer_mutation": feedback["production_pointer_mutation"],
        "verified_final_answer": feedback["verified_final_answer"],
    }


def run_qa_benchmark(
    qa_cases_artifact: Mapping[str, Any],
    *,
    candidate_cases: Mapping[str, Any],
    presentation_cases: Mapping[str, Any],
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
    candidate_policy: Mapping[str, Any],
    qa_policy: Mapping[str, Any],
) -> dict[str, Any]:
    verify_self_digest(qa_cases_artifact)
    if qa_cases_artifact.get("schema_version") != QA_CASES_SCHEMA:
        raise CandidateQAFeedbackError("QA_CASES_INVALID", "cases schema mismatch")
    feedbacks = []
    results = []
    for case in qa_cases_artifact["cases"]:
        record = build_candidate_record_for_qa_case(
            case,
            candidate_cases=candidate_cases,
            presentation_cases=presentation_cases,
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
            candidate_policy=candidate_policy,
        )
        feedbacks.append(review_candidate_record(record, qa_policy))
        results.append(
            run_qa_case(
                case,
                candidate_cases=candidate_cases,
                presentation_cases=presentation_cases,
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
                candidate_policy=candidate_policy,
                qa_policy=qa_policy,
            )
        )
    plan = compile_baseline_refresh_plan(feedbacks, qa_policy)
    validate_baseline_refresh_plan(plan)
    passed = sum(item["passed"] for item in results)
    return with_self_digest(
        {
            "schema_version": QA_BENCHMARK_SCHEMA,
            "status": "m26_9_candidate_qa_ready" if passed == len(results) else "repair_required",
            "case_count": len(results),
            "passed_count": passed,
            "failed_count": len(results) - passed,
            "baseline_refresh_plan_sha256": plan["self_sha256"],
            "metrics": {
                "case_pass_rate": passed / len(results) if results else 0.0,
                "qa_feedback_ready_count": plan["feedback_ready_count"],
                "qa_refusal_feedback_count": plan["refusal_feedback_count"],
                "qa_rejected_feedback_count": plan["rejected_feedback_count"],
                "warning_feedback_count": plan["warning_feedback_count"],
                "provider_call_count": 0,
                "credentials_used_count": 0,
                "live_network_call_count": 0,
                "real_corpus_binding_count": 0,
                "semantic_or_hybrid_use_count": 0,
                "production_answer_serving_count": 0,
                "production_pointer_mutation_count": 0,
                "verified_final_answer_count": 0,
                "baseline_refresh_execution_count": 0,
            },
            "results": results,
            "authority": {
                "synthetic_only": True,
                "candidate_bundle_review": True,
                "baseline_refresh_planning": True,
                "baseline_refresh_execution": False,
                "live_provider_calls": False,
                "production_authority": False,
                "production_pointer_mutation": False,
                "verified_final_answers": False,
                "m26_10_authorized": False,
            },
        }
    )
