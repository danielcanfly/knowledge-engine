from __future__ import annotations

import hashlib
import json
from typing import Any


class FinalAuthorityGateError(ValueError):
    pass


def sha256_value(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_self_digest(value: dict[str, Any]) -> None:
    expected = value.get("self_sha256")
    unsigned = dict(value)
    unsigned.pop("self_sha256", None)
    if expected != sha256_value(unsigned):
        raise FinalAuthorityGateError("SELF_DIGEST_INVALID")


def validate_final_authority_policy(policy: dict[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    authority = policy["authority"]
    if authority.get("synthetic_only") is not True:
        raise FinalAuthorityGateError("SYNTHETIC_ONLY_REQUIRED")
    allowed_true = {"synthetic_only", "baseline_refresh_review", "final_authority_review"}
    if any(value for key, value in authority.items() if key not in allowed_true):
        raise FinalAuthorityGateError("FINAL_AUTHORITY_POLICY_ESCALATION")
    if policy["decision_policy"].get("allow_answer_text") is not False:
        raise FinalAuthorityGateError("ANSWER_TEXT_POLICY_INVALID")
    if policy["decision_policy"].get("execution_forbidden") is not True:
        raise FinalAuthorityGateError("EXECUTION_POLICY_INVALID")
    return policy


def compile_final_authority_review(
    case_id: str,
    qa_record: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    validate_final_authority_policy(policy)
    escalated = bool(
        qa_record.get("answer_text")
        or qa_record.get("baseline_refresh_execution")
        or qa_record.get("production_answer_serving")
        or qa_record.get("production_pointer_mutation")
        or qa_record.get("verified_final_answer")
        or qa_record.get("real_corpus_binding")
    )
    if escalated:
        decision_status = policy["decision_policy"]["rejected_status"]
        claims: list[str] = []
        bindings: list[str] = []
        reasons = ["AUTHORITY_ESCALATION"]
    elif qa_record.get("warning_ids") or qa_record.get("refusal_reason_codes"):
        decision_status = policy["decision_policy"]["held_status"]
        claims = list(qa_record.get("claim_ids", []))
        bindings = list(qa_record.get("binding_ids", []))
        reasons = list(qa_record.get("refusal_reason_codes", []))
    elif qa_record.get("qa_status") == "qa_feedback_ready":
        decision_status = policy["decision_policy"]["approved_status"]
        claims = list(qa_record.get("claim_ids", []))
        bindings = list(qa_record.get("binding_ids", []))
        reasons = []
    else:
        decision_status = policy["decision_policy"]["held_status"]
        claims = []
        bindings = []
        reasons = ["UNRESOLVED_QA_STATE"]

    record: dict[str, Any] = {
        "case_id": case_id,
        "decision_status": decision_status,
        "claim_ids": claims,
        "binding_ids": bindings,
        "warning_ids": list(qa_record.get("warning_ids", [])),
        "refusal_reason_codes": reasons,
        "answer_text": "",
        "baseline_refresh_execution": False,
        "production_answer_serving": False,
        "production_pointer_mutation": False,
        "verified_final_answer": False,
    }
    record["self_sha256"] = sha256_value(record)
    return record


def validate_final_authority_review(record: dict[str, Any]) -> None:
    verify_self_digest(record)
    if record.get("answer_text"):
        raise FinalAuthorityGateError("ANSWER_TEXT_FORBIDDEN")
    for field in (
        "baseline_refresh_execution",
        "production_answer_serving",
        "production_pointer_mutation",
        "verified_final_answer",
    ):
        if record.get(field):
            raise FinalAuthorityGateError(f"{field.upper()}_FORBIDDEN")
    if record["decision_status"] not in {
        "approved_for_future_gate",
        "held_for_repair",
        "rejected_authority_escalation",
    }:
        raise FinalAuthorityGateError("DECISION_STATUS_INVALID")


def run_final_authority_benchmark(
    benchmark_cases: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    verify_self_digest(benchmark_cases)
    validate_final_authority_policy(policy)
    results = []
    for case in benchmark_cases["cases"]:
        record = compile_final_authority_review(case["case_id"], case["input"], policy)
        validate_final_authority_review(record)
        passed = record["decision_status"] == case["expected_status"]
        results.append({"case_id": case["case_id"], "passed": passed, "record": record})

    metrics = {
        "approved_for_future_gate_count": sum(
            item["record"]["decision_status"] == "approved_for_future_gate" for item in results
        ),
        "held_for_repair_count": sum(
            item["record"]["decision_status"] == "held_for_repair" for item in results
        ),
        "rejected_authority_escalation_count": sum(
            item["record"]["decision_status"] == "rejected_authority_escalation"
            for item in results
        ),
        "baseline_refresh_execution_count": 0,
        "provider_call_count": 0,
        "real_corpus_binding_count": 0,
        "production_answer_serving_count": 0,
        "production_pointer_mutation_count": 0,
        "verified_final_answer_count": 0,
    }
    report: dict[str, Any] = {
        "status": "m26_10_synthetic_final_authority_gate_ready",
        "case_count": len(results),
        "passed_count": sum(item["passed"] for item in results),
        "failed_count": sum(not item["passed"] for item in results),
        "metrics": metrics,
        "results": results,
    }
    report["self_sha256"] = sha256_value(report)
    return report
