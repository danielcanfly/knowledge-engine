from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m26_retrieval_envelope import verify_self_digest, with_self_digest

POLICY_SCHEMA = "knowledge-engine-m26-pa-4-verified-answer-policy/v1"
CASES_SCHEMA = "knowledge-engine-m26-pa-4-verified-answer-benchmark-cases/v1"
RECORD_SCHEMA = "knowledge-engine-m26-pa-4-verified-answer-record/v1"
BENCHMARK_SCHEMA = "knowledge-engine-m26-pa-4-verified-answer-benchmark/v1"
PREDECESSOR_STATUS = "m26_pa_3_live_provider_execution_accepted"

READY_STATUSES = {
    "verified_answer_ready",
    "verified_answer_ready_after_bounded_repair",
    "verified_answer_ready_with_warnings",
}
TERMINAL_STATUSES = READY_STATUSES | {
    "abstention_required",
    "verified_answer_rejected_authority_escalation",
}


class VerifiedAnswerCitationGateError(IntegrityError):
    """Fail-closed M26.PA.4 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def validate_verified_answer_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise VerifiedAnswerCitationGateError("PA4_POLICY_INVALID", "schema mismatch")
    if policy.get("accepted_predecessor_status") != PREDECESSOR_STATUS:
        raise VerifiedAnswerCitationGateError("PREDECESSOR_NOT_ACCEPTED", "PA.3 is not pinned")
    authority = policy.get("authority")
    gate_policy = policy.get("gate_policy")
    status_policy = policy.get("status_policy")
    if not all(isinstance(item, Mapping) for item in (authority, gate_policy, status_policy)):
        raise VerifiedAnswerCitationGateError("PA4_POLICY_INVALID", "sections are missing")
    required_true = (
        "material_claim_extraction",
        "citation_binding",
        "support_verification",
        "bounded_repair",
        "abstention",
        "deterministic_evidence",
        "complete_denominator",
    )
    if any(authority.get(key) is not True for key in required_true):
        raise VerifiedAnswerCitationGateError("PA4_AUTHORITY_INVALID", "required gate disabled")
    required_false = (
        "live_provider_calls",
        "production_answer_serving",
        "production_pointer_mutation",
        "public_shadow_canary_traffic",
        "verified_final_answers",
        "secret_persistence",
        "raw_text_persistence",
        "r2_writes",
        "qdrant_writes",
        "source_foundation_release_mutation",
    )
    if any(authority.get(key) is not False for key in required_false):
        raise VerifiedAnswerCitationGateError("PA4_AUTHORITY_INVALID", "forbidden authority")
    if gate_policy.get("fail_closed") is not True:
        raise VerifiedAnswerCitationGateError("PA4_GATE_INVALID", "fail closed is required")
    if gate_policy.get("abstain_on_insufficient_support") is not True:
        raise VerifiedAnswerCitationGateError("PA4_GATE_INVALID", "abstention gate missing")
    if int(gate_policy.get("max_repair_attempts", -1)) < 0:
        raise VerifiedAnswerCitationGateError("PA4_GATE_INVALID", "repair bound is invalid")
    if set(status_policy.values()) - TERMINAL_STATUSES:
        raise VerifiedAnswerCitationGateError("PA4_STATUS_POLICY_INVALID", "unknown status")
    return dict(policy)


def _forbidden_text_failures(candidate: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    fragments = policy["gate_policy"].get("forbidden_text_fragments", [])
    serialized = json.dumps(
        {
            "answer_text_sha256": candidate.get("answer_text_sha256", ""),
            "material_claim_ids": candidate.get("material_claim_ids", []),
            "citation_binding_ids": candidate.get("citation_binding_ids", []),
            "diagnostics": candidate.get("diagnostics", {}),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).casefold()
    return [
        "FORBIDDEN_TEXT_FRAGMENT_LEAKED"
        for fragment in fragments
        if str(fragment).casefold() in serialized
    ]


def _authority_failures(candidate: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    authority = candidate.get("authority", {})
    if not isinstance(authority, Mapping):
        failures.append("AUTHORITY_SECTION_MISSING")
        return failures
    for key, reason in (
        ("live_provider_calls", "LIVE_PROVIDER_CALL_ESCALATION"),
        ("production_answer_serving", "PRODUCTION_ANSWER_SERVING_ESCALATION"),
        ("production_pointer_mutation", "PRODUCTION_POINTER_ESCALATION"),
        ("public_shadow_canary_traffic", "PUBLIC_SHADOW_CANARY_TRAFFIC_ESCALATION"),
        ("verified_final_answer", "VERIFIED_FINAL_ANSWER_ESCALATION"),
        ("secret_persistence", "SECRET_PERSISTENCE_ESCALATION"),
        ("raw_text_persistence", "RAW_TEXT_PERSISTENCE_ESCALATION"),
        ("r2_write", "R2_WRITE_ESCALATION"),
        ("qdrant_write", "QDRANT_WRITE_ESCALATION"),
    ):
        if authority.get(key) is not False:
            failures.append(reason)
    failures.extend(_forbidden_text_failures(candidate, policy))
    return failures


def _support_failures(candidate: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    claims = candidate.get("material_claim_ids", [])
    bindings = candidate.get("citation_binding_ids", [])
    verdicts = candidate.get("support_verdicts", [])
    if not isinstance(claims, list) or not isinstance(bindings, list):
        return ["CLAIMS_OR_BINDINGS_MISSING"]
    if not claims or not bindings:
        return ["CLAIMS_OR_BINDINGS_EMPTY"]
    if not isinstance(verdicts, list) or len(verdicts) != len(claims):
        return ["SUPPORT_DENOMINATOR_MISMATCH"]
    if len(bindings) < len(claims):
        return ["CITATION_BINDING_DENOMINATOR_MISMATCH"]
    unsupported = {
        str(verdict)
        for verdict in verdicts
        if str(verdict) not in {"supported", "repairable"}
    }
    if unsupported:
        return [f"SUPPORT_{item.upper()}" for item in sorted(unsupported)]
    repairs = int(candidate.get("repair_attempts", 0))
    if repairs > int(policy["gate_policy"]["max_repair_attempts"]):
        return ["REPAIR_BOUND_EXCEEDED"]
    return []


def compile_verified_answer_record(
    verified_case: Mapping[str, Any],
    verified_answer_policy: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_verified_answer_policy(verified_answer_policy)
    candidate = verified_case.get("candidate")
    if not isinstance(candidate, Mapping):
        raise VerifiedAnswerCitationGateError("PA4_CASE_INVALID", "candidate is missing")
    authority_failures = _authority_failures(candidate, policy)
    support_failures = [] if authority_failures else _support_failures(candidate, policy)
    warnings = [str(item) for item in candidate.get("warning_codes", [])]
    repair_attempts = int(candidate.get("repair_attempts", 0))

    if authority_failures:
        status = policy["status_policy"]["authority_rejected_status"]
        verified_claim_ids: list[str] = []
        verified_binding_ids: list[str] = []
        refusal_codes = sorted(set(authority_failures))
        abstention_required = True
    elif support_failures:
        status = policy["status_policy"]["abstention_status"]
        verified_claim_ids = []
        verified_binding_ids = []
        refusal_codes = sorted(set(support_failures))
        abstention_required = True
    else:
        verified_claim_ids = [str(item) for item in candidate.get("material_claim_ids", [])]
        verified_binding_ids = [str(item) for item in candidate.get("citation_binding_ids", [])]
        refusal_codes = []
        abstention_required = False
        support_verdicts = {str(item) for item in candidate.get("support_verdicts", [])}
        if "repairable" in support_verdicts or repair_attempts:
            status = policy["status_policy"]["repaired_status"]
        elif warnings:
            status = policy["status_policy"]["warning_status"]
        else:
            status = policy["status_policy"]["ready_status"]

    record = with_self_digest(
        {
            "schema_version": RECORD_SCHEMA,
            "stage_id": "M26.PA.4",
            "case_id": str(verified_case.get("case_id", "")),
            "predecessor_status": PREDECESSOR_STATUS,
            "verified_answer_status": status,
            "safe_for_pa5": status in READY_STATUSES,
            "material_claim_extraction": True,
            "citation_binding": True,
            "support_verification": True,
            "complete_denominator_record": True,
            "verified_claim_ids": verified_claim_ids,
            "verified_binding_ids": verified_binding_ids,
            "warning_codes": warnings,
            "refusal_reason_codes": refusal_codes,
            "repair_attempt_count": (
                0
                if refusal_codes and status != policy["status_policy"]["repaired_status"]
                else repair_attempts
            ),
            "abstention_required": abstention_required,
            "production_answer_serving": False,
            "production_pointer_mutation": False,
            "public_shadow_canary_traffic": False,
            "verified_final_answer": False,
            "live_provider_calls": False,
            "secret_values_persisted": False,
            "raw_text_persisted": False,
            "diagnostics": {
                "authority_failure_count": len(authority_failures),
                "support_failure_count": len(support_failures),
                "warning_count": len(warnings),
            },
        }
    )
    validate_verified_answer_record(record)
    return record


def validate_verified_answer_record(record: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(record)
    if record.get("schema_version") != RECORD_SCHEMA:
        raise VerifiedAnswerCitationGateError("PA4_RECORD_INVALID", "schema mismatch")
    if record.get("stage_id") != "M26.PA.4":
        raise VerifiedAnswerCitationGateError("PA4_RECORD_INVALID", "stage mismatch")
    for key in (
        "material_claim_extraction",
        "citation_binding",
        "support_verification",
        "complete_denominator_record",
    ):
        if record.get(key) is not True:
            raise VerifiedAnswerCitationGateError("PA4_RECORD_INVALID", key)
    for key in (
        "production_answer_serving",
        "production_pointer_mutation",
        "public_shadow_canary_traffic",
        "verified_final_answer",
        "live_provider_calls",
        "secret_values_persisted",
        "raw_text_persisted",
    ):
        if record.get(key) is not False:
            raise VerifiedAnswerCitationGateError("PA4_AUTHORITY_ESCALATION", key)
    status = str(record.get("verified_answer_status"))
    if status not in TERMINAL_STATUSES:
        raise VerifiedAnswerCitationGateError("PA4_STATUS_INVALID", status)
    claims = record.get("verified_claim_ids")
    bindings = record.get("verified_binding_ids")
    if not isinstance(claims, list) or not isinstance(bindings, list):
        raise VerifiedAnswerCitationGateError("PA4_RECORD_INVALID", "missing identities")
    if status in READY_STATUSES:
        if not claims or not bindings or record.get("abstention_required") is not False:
            raise VerifiedAnswerCitationGateError("PA4_READY_RECORD_INVALID", status)
        if record.get("refusal_reason_codes"):
            raise VerifiedAnswerCitationGateError("PA4_READY_HAS_REFUSAL", status)
    else:
        if claims or bindings:
            raise VerifiedAnswerCitationGateError("PA4_REFUSAL_HAS_IDENTITIES", status)
        if record.get("abstention_required") is not True:
            raise VerifiedAnswerCitationGateError("PA4_REFUSAL_INVALID", status)
        if not record.get("refusal_reason_codes"):
            raise VerifiedAnswerCitationGateError("PA4_REFUSAL_REASON_REQUIRED", status)
    return dict(record)


def run_verified_answer_benchmark(
    verified_cases_artifact: Mapping[str, Any],
    verified_answer_policy: Mapping[str, Any],
) -> dict[str, Any]:
    verify_self_digest(verified_cases_artifact)
    if verified_cases_artifact.get("schema_version") != CASES_SCHEMA:
        raise VerifiedAnswerCitationGateError("PA4_CASES_INVALID", "schema mismatch")
    records = []
    results = []
    for case in verified_cases_artifact.get("cases", []):
        if not isinstance(case, Mapping):
            raise VerifiedAnswerCitationGateError("PA4_CASE_INVALID", "case must be an object")
        record = compile_verified_answer_record(case, verified_answer_policy)
        expected = case.get("expected", {})
        failures: list[str] = []
        if not isinstance(expected, Mapping):
            failures.append("expected")
        elif record["verified_answer_status"] != expected.get("status"):
            failures.append("status")
        if len(record["verified_claim_ids"]) < int(expected.get("min_verified_claims", 0)):
            failures.append("min_verified_claims")
        if len(record["verified_binding_ids"]) < int(expected.get("min_verified_bindings", 0)):
            failures.append("min_verified_bindings")
        if expected.get("requires_abstention") and record["abstention_required"] is not True:
            failures.append("abstention")
        if expected.get("requires_repair") and record["repair_attempt_count"] <= 0:
            failures.append("bounded_repair")
        records.append(record)
        results.append(
            {
                "case_id": case["case_id"],
                "passed": not failures,
                "failures": failures,
                "verified_answer_status": record["verified_answer_status"],
                "verified_claim_count": len(record["verified_claim_ids"]),
                "verified_binding_count": len(record["verified_binding_ids"]),
                "abstention_required": record["abstention_required"],
                "repair_attempt_count": record["repair_attempt_count"],
                "record_sha256": record["self_sha256"],
            }
        )
    passed = sum(item["passed"] for item in results)
    return with_self_digest(
        {
            "schema_version": BENCHMARK_SCHEMA,
            "stage_id": "M26.PA.4",
            "status": (
                "m26_pa_4_verified_answer_citation_gate_ready"
                if passed == len(results)
                else "m26_pa_4_verified_answer_citation_gate_repair_required"
            ),
            "case_count": len(results),
            "passed_count": passed,
            "failed_count": len(results) - passed,
            "metrics": {
                "verified_answer_ready_count": sum(
                    record["verified_answer_status"] in READY_STATUSES for record in records
                ),
                "bounded_repair_count": sum(
                    record["verified_answer_status"] == "verified_answer_ready_after_bounded_repair"
                    for record in records
                ),
                "abstention_count": sum(record["abstention_required"] for record in records),
                "authority_rejection_count": sum(
                    record["verified_answer_status"]
                    == "verified_answer_rejected_authority_escalation"
                    for record in records
                ),
                "material_claim_denominator": sum(
                    len(record["verified_claim_ids"]) for record in records
                ),
                "citation_binding_denominator": sum(
                    len(record["verified_binding_ids"]) for record in records
                ),
                "production_answer_serving_count": 0,
                "production_pointer_mutation_count": 0,
                "public_shadow_canary_traffic_count": 0,
                "verified_final_answer_count": 0,
            },
            "record_sha256s": [record["self_sha256"] for record in records],
            "results": results,
        }
    )
