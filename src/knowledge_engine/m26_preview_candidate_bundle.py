from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m26_answer_presentation import (
    build_evaluation_package_for_case,
    compile_presentation_preview,
    validate_presentation_package,
)
from .m26_retrieval_envelope import sha256_value, verify_self_digest, with_self_digest

CANDIDATE_POLICY_SCHEMA = "knowledge-engine-m26-preview-candidate-policy/v1"
CANDIDATE_CASES_SCHEMA = "knowledge-engine-m26-preview-candidate-benchmark-cases/v1"
CANDIDATE_RECORD_SCHEMA = "knowledge-engine-m26-preview-candidate-record/v1"
CANDIDATE_BUNDLE_SCHEMA = "knowledge-engine-m26-preview-candidate-bundle/v1"
CANDIDATE_BENCHMARK_SCHEMA = "knowledge-engine-m26-preview-candidate-benchmark/v1"
PRESENTATION_PACKAGE_SCHEMA = "knowledge-engine-m26-answer-presentation/v1"

CANDIDATE_RECORD_STATUSES = {
    "candidate_preview_record",
    "candidate_preview_record_with_warnings",
    "candidate_refusal_record",
    "candidate_rejected_authority_escalation",
}


class PreviewCandidateBundleError(IntegrityError):
    """Fail-closed M26.8 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def validate_candidate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    if policy.get("schema_version") != CANDIDATE_POLICY_SCHEMA:
        raise PreviewCandidateBundleError("CANDIDATE_POLICY_INVALID", "schema is incompatible")
    if policy.get("accepted_predecessor_status") != (
        "m26_7_answer_presentation_non_serving_preview_accepted"
    ):
        raise PreviewCandidateBundleError("PREDECESSOR_NOT_ACCEPTED", "M26.7 is not pinned")
    authority = policy.get("authority")
    surface_policy = policy.get("surface_policy")
    status_policy = policy.get("status_policy")
    if not all(isinstance(item, Mapping) for item in (authority, surface_policy, status_policy)):
        raise PreviewCandidateBundleError("CANDIDATE_POLICY_INVALID", "sections are missing")
    for key in (
        "synthetic_only",
        "preview_evidence_integration",
        "candidate_bundle",
        "presentation_contract_required",
    ):
        if authority.get(key) is not True:
            raise PreviewCandidateBundleError("CANDIDATE_AUTHORITY_INVALID", key)
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
        raise PreviewCandidateBundleError("CANDIDATE_AUTHORITY_INVALID", "forbidden authority")
    for key in ("candidate_only", "preview_only", "non_serving_preview"):
        if surface_policy.get(key) is not True:
            raise PreviewCandidateBundleError("CANDIDATE_SURFACE_INVALID", key)
    if surface_policy.get("allow_answer_text") is not False:
        raise PreviewCandidateBundleError("CANDIDATE_SURFACE_INVALID", "answer text allowed")
    if surface_policy.get("refusals_have_no_claims") is not True:
        raise PreviewCandidateBundleError("CANDIDATE_SURFACE_INVALID", "refusal claims allowed")
    return dict(policy)


def _authority_failures(preview: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    for key, reason in (
        ("synthetic_only", "PREVIEW_NOT_SYNTHETIC"),
        ("preview_only", "PREVIEW_ONLY_MISSING"),
        ("non_serving_preview", "NON_SERVING_PREVIEW_MISSING"),
        ("safe_for_m26_8", "PREVIEW_NOT_SAFE_FOR_M26_8"),
    ):
        if preview.get(key) is not True:
            failures.append(reason)
    for key, reason in (
        ("final_answer", "FINAL_ANSWER_ESCALATION"),
        ("verified_final_answer", "VERIFIED_FINAL_ANSWER_ESCALATION"),
        ("production_answer_serving", "PRODUCTION_ANSWER_SERVING_ESCALATION"),
        ("production_pointer_mutation", "PRODUCTION_POINTER_ESCALATION"),
        ("real_corpus_binding", "REAL_CORPUS_BINDING_ESCALATION"),
    ):
        if key in preview and preview.get(key) is not False:
            failures.append(reason)
    if preview.get("answer_text"):
        failures.append("ANSWER_TEXT_LEAKAGE")
    return failures


def _candidate_claim_ids(preview: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    max_claims = int(policy["surface_policy"].get("max_candidate_claims", 6))
    claims = preview.get("display_claims", [])
    result: list[str] = []
    if not isinstance(claims, list):
        return result
    for claim in claims[:max_claims]:
        if isinstance(claim, Mapping):
            result.append(str(claim.get("display_claim_id", "")))
    return [claim_id for claim_id in result if claim_id]


def _forbidden_text_failures(record: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    serialized = json.dumps(
        {
            "answer_text": record.get("answer_text", ""),
            "candidate_claim_ids": record.get("candidate_claim_ids", []),
            "diagnostics": record.get("diagnostics", {}),
            "warning_banners": record.get("warning_banners", []),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).casefold()
    return [
        "FORBIDDEN_TEXT_FRAGMENT_LEAKED"
        for fragment in policy.get("forbidden_text_fragments", [])
        if str(fragment).casefold() in serialized
    ]


def compile_candidate_record(
    presentation_package: Mapping[str, Any],
    candidate_policy: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_candidate_policy(candidate_policy)
    preview = dict(presentation_package)
    authority_failures = _authority_failures(preview)
    if not authority_failures:
        validate_presentation_package(preview)
    preview_status = str(preview.get("presentation_status"))
    candidate_status: str
    candidate_claim_ids: list[str]
    candidate_binding_ids: list[str]
    refusal_codes = [str(item) for item in preview.get("refusal_reason_codes", [])]
    if authority_failures:
        candidate_status = policy["status_policy"]["authority_rejected_status"]
        candidate_claim_ids = []
        candidate_binding_ids = []
        refusal_codes = sorted(set(authority_failures))
    elif preview_status.startswith("non_serving_preview"):
        candidate_status = (
            policy["status_policy"]["warning_record_status"]
            if preview.get("warning_banners")
            else policy["status_policy"]["preview_record_status"]
        )
        candidate_claim_ids = _candidate_claim_ids(preview, policy)
        candidate_binding_ids = [str(item) for item in preview.get("display_binding_ids", [])]
    elif preview_status == "non_serving_refusal_preview":
        candidate_status = policy["status_policy"]["refusal_record_status"]
        candidate_claim_ids = []
        candidate_binding_ids = []
        refusal_codes = refusal_codes or [preview_status.upper()]
    else:
        candidate_status = policy["status_policy"]["authority_rejected_status"]
        candidate_claim_ids = []
        candidate_binding_ids = []
        refusal_codes = ["UNSUPPORTED_PREVIEW_STATUS"]
    record = with_self_digest(
        {
            "schema_version": CANDIDATE_RECORD_SCHEMA,
            "request_id": str(preview.get("request_id", "")),
            "presentation_package_sha256": str(preview.get("self_sha256", "")),
            "evaluation_package_sha256": str(preview.get("evaluation_package_sha256", "")),
            "draft_package_sha256": str(preview.get("draft_package_sha256", "")),
            "candidate_record_status": candidate_status,
            "candidate_only": True,
            "preview_only": True,
            "non_serving_preview": True,
            "safe_for_m26_9": True,
            "synthetic_only": True,
            "final_answer": False,
            "verified_final_answer": False,
            "production_answer_serving": False,
            "production_pointer_mutation": False,
            "real_corpus_binding": False,
            "answer_text": "",
            "candidate_claim_ids": candidate_claim_ids,
            "candidate_binding_ids": candidate_binding_ids,
            "warning_banners": [str(item) for item in preview.get("warning_banners", [])],
            "refusal_reason_codes": refusal_codes,
            "evidence_summary": {
                "preview_status": preview_status,
                "surface_block_count": len(preview.get("surface_blocks", [])),
                "claim_count": len(candidate_claim_ids),
                "binding_count": len(candidate_binding_ids),
                "warning_count": len(preview.get("warning_banners", [])),
                "refusal_count": len(refusal_codes),
            },
            "provenance": {
                "m26_7_presentation_status": preview_status,
                "presentation_package_sha256": str(preview.get("self_sha256", "")),
                "evaluation_package_sha256": str(preview.get("evaluation_package_sha256", "")),
            },
            "diagnostics": {
                "source_preview_status": preview_status,
                "source_preview_safe_for_m26_8": bool(preview.get("safe_for_m26_8")),
                "authority_rejection": bool(authority_failures),
                "candidate_bundle_only": True,
            },
        }
    )
    validate_candidate_record(record, candidate_policy)
    return record


def validate_candidate_record(
    record: Mapping[str, Any],
    candidate_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    verify_self_digest(record)
    if record.get("schema_version") != CANDIDATE_RECORD_SCHEMA:
        raise PreviewCandidateBundleError("CANDIDATE_RECORD_INVALID", "schema is incompatible")
    for key in (
        "candidate_only",
        "preview_only",
        "non_serving_preview",
        "synthetic_only",
        "safe_for_m26_9",
    ):
        if record.get(key) is not True:
            raise PreviewCandidateBundleError("CANDIDATE_RECORD_INVALID", key)
    for key in (
        "final_answer",
        "verified_final_answer",
        "production_answer_serving",
        "production_pointer_mutation",
        "real_corpus_binding",
    ):
        if record.get(key) is not False:
            raise PreviewCandidateBundleError("CANDIDATE_AUTHORITY_ESCALATION", key)
    if record.get("answer_text"):
        raise PreviewCandidateBundleError("ANSWER_TEXT_FORBIDDEN", "candidate contains answer text")
    status = str(record.get("candidate_record_status"))
    if status not in CANDIDATE_RECORD_STATUSES:
        raise PreviewCandidateBundleError("CANDIDATE_STATUS_INVALID", status)
    claim_ids = record.get("candidate_claim_ids")
    binding_ids = record.get("candidate_binding_ids")
    if not isinstance(claim_ids, list) or not isinstance(binding_ids, list):
        raise PreviewCandidateBundleError("CANDIDATE_IDENTITIES_MISSING", status)
    if status.startswith("candidate_preview_record"):
        if not claim_ids or not binding_ids:
            raise PreviewCandidateBundleError("CANDIDATE_PREVIEW_MISSING_IDENTITIES", status)
        if record.get("refusal_reason_codes"):
            raise PreviewCandidateBundleError("CANDIDATE_PREVIEW_HAS_REFUSAL", status)
    else:
        if claim_ids or binding_ids:
            raise PreviewCandidateBundleError("CANDIDATE_REFUSAL_HAS_IDENTITIES", status)
        if not record.get("refusal_reason_codes"):
            raise PreviewCandidateBundleError("CANDIDATE_REFUSAL_CODES_REQUIRED", status)
    if candidate_policy is not None:
        policy = validate_candidate_policy(candidate_policy)
        failures = _forbidden_text_failures(record, policy)
        if failures:
            raise PreviewCandidateBundleError("CANDIDATE_FORBIDDEN_TEXT_LEAKED", ",".join(failures))
    return dict(record)


def _case_by_id(cases: Mapping[str, Any], case_id: str, *, label: str) -> Mapping[str, Any]:
    for case in cases.get("cases", []):
        if isinstance(case, Mapping) and case.get("case_id") == case_id:
            return case
    raise PreviewCandidateBundleError(f"{label}_CASE_NOT_FOUND", f"case not found: {case_id}")


def _apply_preview_tamper(preview: Mapping[str, Any], tamper: object) -> dict[str, Any]:
    result = json.loads(json.dumps(preview))
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
    if tamper.get("set_safe_for_m26_8_false") is True:
        result["safe_for_m26_8"] = False
    if tamper.get("append_answer_text"):
        result["answer_text"] = f"{result.get('answer_text', '')} {tamper['append_answer_text']}"
    unsigned = dict(result)
    unsigned.pop("self_sha256", None)
    result["self_sha256"] = sha256_value(unsigned)
    return result


def build_presentation_package_for_case(
    candidate_case: Mapping[str, Any],
    *,
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
) -> dict[str, Any]:
    presentation_case = _case_by_id(
        presentation_cases,
        str(candidate_case["m26_7_case_id"]),
        label="PRESENTATION",
    )
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
    return _apply_preview_tamper(preview, candidate_case.get("tamper", {}))


def run_candidate_case(
    candidate_case: Mapping[str, Any],
    *,
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
    expected = candidate_case["expected"]
    failures: list[str] = []
    if record["candidate_record_status"] != expected["status"]:
        failures.append("status")
    if record["safe_for_m26_9"] is not bool(expected.get("safe_for_candidate_bundle", True)):
        failures.append("safe_for_candidate_bundle")
    if len(record["candidate_claim_ids"]) < int(expected.get("min_candidate_claims", 0)):
        failures.append("min_candidate_claims")
    if len(record["candidate_binding_ids"]) < int(expected.get("min_candidate_bindings", 0)):
        failures.append("min_candidate_bindings")
    if expected.get("requires_refusal_record") and not record["refusal_reason_codes"]:
        failures.append("refusal_record")
    if expected.get("requires_conflict_warning") and "conflict_warning" not in record["warning_banners"]:
        failures.append("conflict_warning")
    if (
        expected.get("requires_prompt_injection_warning")
        and "prompt_injection_quarantined" not in record["warning_banners"]
    ):
        failures.append("prompt_injection_warning")
    serialized = json.dumps(record, ensure_ascii=False).casefold()
    for fragment in expected.get("forbidden_text_fragments", []):
        if str(fragment).casefold() in serialized:
            failures.append("forbidden_text_fragment")
    return {
        "case_id": candidate_case["case_id"],
        "m26_7_case_id": candidate_case["m26_7_case_id"],
        "passed": not failures,
        "failures": failures,
        "candidate_record_status": record["candidate_record_status"],
        "safe_for_m26_9": record["safe_for_m26_9"],
        "candidate_record_sha256": record["self_sha256"],
        "presentation_package_sha256": record["presentation_package_sha256"],
        "candidate_claim_count": len(record["candidate_claim_ids"]),
        "candidate_binding_count": len(record["candidate_binding_ids"]),
        "warning_count": len(record["warning_banners"]),
        "refusal_record": bool(record["refusal_reason_codes"]),
        "final_answer": record["final_answer"],
        "verified_final_answer": record["verified_final_answer"],
        "production_answer_serving": record["production_answer_serving"],
        "production_pointer_mutation": record["production_pointer_mutation"],
    }


def compile_candidate_bundle(
    records: list[Mapping[str, Any]],
    candidate_policy: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_candidate_policy(candidate_policy)
    valid_records = [validate_candidate_record(record, policy) for record in records]
    preview_records = [
        record
        for record in valid_records
        if str(record["candidate_record_status"]).startswith("candidate_preview_record")
    ]
    refusal_records = [
        record for record in valid_records if record["candidate_record_status"] == "candidate_refusal_record"
    ]
    rejected_records = [
        record
        for record in valid_records
        if record["candidate_record_status"] == "candidate_rejected_authority_escalation"
    ]
    return with_self_digest(
        {
            "schema_version": CANDIDATE_BUNDLE_SCHEMA,
            "status": policy["status_policy"]["bundle_ready_status"],
            "bundle_kind": policy["candidate_bundle_policy"]["bundle_kind"],
            "candidate_only": True,
            "preview_only": True,
            "non_serving_preview": True,
            "synthetic_only": True,
            "final_answer": False,
            "verified_final_answer": False,
            "production_answer_serving": False,
            "production_pointer_mutation": False,
            "real_corpus_binding": False,
            "record_count": len(valid_records),
            "candidate_preview_count": len(preview_records),
            "candidate_refusal_count": len(refusal_records),
            "candidate_rejected_count": len(rejected_records),
            "warning_record_count": sum(bool(record["warning_banners"]) for record in valid_records),
            "candidate_record_sha256s": [str(record["self_sha256"]) for record in valid_records],
            "candidate_claim_ids": sorted(
                {str(claim_id) for record in preview_records for claim_id in record["candidate_claim_ids"]}
            ),
            "candidate_binding_ids": sorted(
                {str(binding_id) for record in preview_records for binding_id in record["candidate_binding_ids"]}
            ),
        }
    )


def validate_candidate_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(bundle)
    if bundle.get("schema_version") != CANDIDATE_BUNDLE_SCHEMA:
        raise PreviewCandidateBundleError("CANDIDATE_BUNDLE_INVALID", "schema is incompatible")
    if bundle.get("status") != "m26_8_candidate_bundle_ready":
        raise PreviewCandidateBundleError("CANDIDATE_BUNDLE_STATUS_INVALID", str(bundle.get("status")))
    for key in ("candidate_only", "preview_only", "non_serving_preview", "synthetic_only"):
        if bundle.get(key) is not True:
            raise PreviewCandidateBundleError("CANDIDATE_BUNDLE_INVALID", key)
    for key in (
        "final_answer",
        "verified_final_answer",
        "production_answer_serving",
        "production_pointer_mutation",
        "real_corpus_binding",
    ):
        if bundle.get(key) is not False:
            raise PreviewCandidateBundleError("CANDIDATE_BUNDLE_AUTHORITY_ESCALATION", key)
    if int(bundle.get("record_count", 0)) <= 0:
        raise PreviewCandidateBundleError("CANDIDATE_BUNDLE_EMPTY", "no records")
    return dict(bundle)


def run_candidate_benchmark(
    candidate_cases_artifact: Mapping[str, Any],
    *,
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
    verify_self_digest(candidate_cases_artifact)
    if candidate_cases_artifact.get("schema_version") != CANDIDATE_CASES_SCHEMA:
        raise PreviewCandidateBundleError("CANDIDATE_CASES_INVALID", "cases schema mismatch")
    records = []
    results = []
    for case in candidate_cases_artifact["cases"]:
        preview = build_presentation_package_for_case(
            case,
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
        records.append(compile_candidate_record(preview, candidate_policy))
        results.append(
            run_candidate_case(
                case,
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
        )
    bundle = compile_candidate_bundle(records, candidate_policy)
    validate_candidate_bundle(bundle)
    passed = sum(item["passed"] for item in results)
    return with_self_digest(
        {
            "schema_version": CANDIDATE_BENCHMARK_SCHEMA,
            "status": "m26_8_candidate_bundle_ready" if passed == len(results) else "repair_required",
            "case_count": len(results),
            "passed_count": passed,
            "failed_count": len(results) - passed,
            "candidate_bundle_sha256": bundle["self_sha256"],
            "metrics": {
                "case_pass_rate": passed / len(results) if results else 0.0,
                "candidate_preview_count": bundle["candidate_preview_count"],
                "candidate_refusal_count": bundle["candidate_refusal_count"],
                "candidate_rejected_count": bundle["candidate_rejected_count"],
                "warning_record_count": bundle["warning_record_count"],
                "provider_call_count": 0,
                "credentials_used_count": 0,
                "live_network_call_count": 0,
                "real_corpus_binding_count": 0,
                "semantic_or_hybrid_use_count": 0,
                "production_answer_serving_count": 0,
                "production_pointer_mutation_count": 0,
                "verified_final_answer_count": 0,
            },
            "results": results,
            "authority": {
                "synthetic_only": True,
                "preview_evidence_integration": True,
                "candidate_bundle": True,
                "live_provider_calls": False,
                "production_authority": False,
                "production_pointer_mutation": False,
                "verified_final_answers": False,
                "m26_9_authorized": False,
            },
        }
    )
