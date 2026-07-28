from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m26_retrieval_envelope import verify_self_digest, with_self_digest

POLICY_SCHEMA = "knowledge-engine-m26-pa-5-shadow-policy/v1"
CASES_SCHEMA = "knowledge-engine-m26-pa-5-shadow-question-population/v1"
RECORD_SCHEMA = "knowledge-engine-m26-pa-5-shadow-review-record/v1"
BENCHMARK_SCHEMA = "knowledge-engine-m26-pa-5-shadow-pilot-benchmark/v1"
PREDECESSOR_STATUS = "m26_pa_4_verified_answer_citation_gate_accepted"

SHADOW_STATUSES = {
    "shadow_answer_reviewed",
    "shadow_abstention_reviewed",
    "shadow_hold_for_repair",
    "shadow_rejected_authority_escalation",
}


class ControlledShadowPilotError(IntegrityError):
    """Fail-closed M26.PA.5 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def validate_shadow_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise ControlledShadowPilotError("PA5_POLICY_INVALID", "schema mismatch")
    if policy.get("accepted_predecessor_status") != PREDECESSOR_STATUS:
        raise ControlledShadowPilotError("PREDECESSOR_NOT_ACCEPTED", "PA.4 is not pinned")
    authority = policy.get("authority")
    pilot_policy = policy.get("pilot_policy")
    status_policy = policy.get("status_policy")
    if not all(isinstance(item, Mapping) for item in (authority, pilot_policy, status_policy)):
        raise ControlledShadowPilotError("PA5_POLICY_INVALID", "sections are missing")
    required_true = (
        "controlled_internal_shadow",
        "authenticated_internal_only",
        "multiple_reviewers",
        "complete_denominator",
        "quality_evidence",
        "citation_evidence",
        "abstention_evidence",
        "latency_evidence",
        "cost_evidence",
    )
    if any(authority.get(key) is not True for key in required_true):
        raise ControlledShadowPilotError("PA5_AUTHORITY_INVALID", "required authority disabled")
    required_false = (
        "public_answers",
        "public_traffic",
        "production_answer_serving",
        "production_pointer_mutation",
        "source_foundation_release_mutation",
        "r2_writes",
        "qdrant_writes",
        "secret_persistence",
    )
    if any(authority.get(key) is not False for key in required_false):
        raise ControlledShadowPilotError("PA5_AUTHORITY_INVALID", "forbidden authority")
    minimum = int(pilot_policy.get("population_min", 0))
    maximum = int(pilot_policy.get("population_max", 0))
    if minimum < 200 or maximum > 500 or minimum > maximum:
        raise ControlledShadowPilotError("PA5_POPULATION_INVALID", "population bounds invalid")
    if int(pilot_policy.get("min_reviewer_count", 0)) < 2:
        raise ControlledShadowPilotError(
            "PA5_REVIEWER_POLICY_INVALID",
            "multiple reviewers required",
        )
    if set(status_policy.values()) - SHADOW_STATUSES:
        raise ControlledShadowPilotError("PA5_STATUS_POLICY_INVALID", "unknown status")
    return dict(policy)


def compile_shadow_review_record(
    question: Mapping[str, Any],
    shadow_policy: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_shadow_policy(shadow_policy)
    pilot_policy = policy["pilot_policy"]
    reviewer_ids = [str(item) for item in question.get("reviewer_ids", [])]
    verified_status = str(question.get("verified_answer_status", ""))
    quality_score = float(question.get("quality_score", 0.0))
    citation_precision = float(question.get("citation_precision", 0.0))
    latency_ms = int(question.get("latency_ms", 0))
    cost_usd = float(question.get("cost_usd", 0.0))
    authority_failures: list[str] = []
    if question.get("internal_authenticated") is not True:
        authority_failures.append("INTERNAL_AUTHENTICATION_MISSING")
    if question.get("public_answer") is not False:
        authority_failures.append("PUBLIC_ANSWER_ESCALATION")
    if question.get("public_traffic") is not False:
        authority_failures.append("PUBLIC_TRAFFIC_ESCALATION")
    if len(set(reviewer_ids)) < int(pilot_policy["min_reviewer_count"]):
        authority_failures.append("REVIEWER_DENOMINATOR_MISSING")
    if authority_failures:
        status = policy["status_policy"]["authority_rejected_status"]
        refusal_codes = sorted(set(authority_failures))
    elif verified_status == "abstention_required":
        status = policy["status_policy"]["abstention_status"]
        refusal_codes = [str(item) for item in question.get("refusal_reason_codes", ["ABSTENTION"])]
    elif (
        verified_status not in {
            "verified_answer_ready",
            "verified_answer_ready_after_bounded_repair",
            "verified_answer_ready_with_warnings",
        }
        or quality_score < float(pilot_policy["min_quality_score"])
        or citation_precision < float(pilot_policy["min_citation_precision"])
        or latency_ms > int(pilot_policy["latency_p95_ms"])
        or cost_usd > float(pilot_policy["max_cost_usd_per_question"])
    ):
        status = policy["status_policy"]["hold_status"]
        refusal_codes = [
            str(item)
            for item in question.get("refusal_reason_codes", ["SHADOW_REPAIR"])
        ]
    else:
        status = policy["status_policy"]["answer_status"]
        refusal_codes = []
    record = with_self_digest(
        {
            "schema_version": RECORD_SCHEMA,
            "stage_id": "M26.PA.5",
            "question_id": str(question.get("question_id", "")),
            "predecessor_status": PREDECESSOR_STATUS,
            "shadow_review_status": status,
            "authenticated_internal_only": True,
            "controlled_shadow": True,
            "complete_denominator_record": True,
            "reviewer_ids": reviewer_ids,
            "reviewer_count": len(set(reviewer_ids)),
            "verified_answer_status": verified_status,
            "quality_score": quality_score,
            "citation_precision": citation_precision,
            "abstention_appropriate": bool(question.get("abstention_appropriate", False)),
            "latency_ms": latency_ms,
            "cost_usd": cost_usd,
            "reviewer_agreement": float(question.get("reviewer_agreement", 0.0)),
            "refusal_reason_codes": refusal_codes,
            "public_answer": False,
            "public_traffic": False,
            "production_answer_serving": False,
            "production_pointer_mutation": False,
            "safe_for_pa6": status in {
                policy["status_policy"]["answer_status"],
                policy["status_policy"]["abstention_status"],
            },
        }
    )
    validate_shadow_review_record(record)
    return record


def validate_shadow_review_record(record: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(record)
    if record.get("schema_version") != RECORD_SCHEMA:
        raise ControlledShadowPilotError("PA5_RECORD_INVALID", "schema mismatch")
    if record.get("stage_id") != "M26.PA.5":
        raise ControlledShadowPilotError("PA5_RECORD_INVALID", "stage mismatch")
    for key in ("authenticated_internal_only", "controlled_shadow", "complete_denominator_record"):
        if record.get(key) is not True:
            raise ControlledShadowPilotError("PA5_RECORD_INVALID", key)
    for key in (
        "public_answer",
        "public_traffic",
        "production_answer_serving",
        "production_pointer_mutation",
    ):
        if record.get(key) is not False:
            raise ControlledShadowPilotError("PA5_AUTHORITY_ESCALATION", key)
    if int(record.get("reviewer_count", 0)) < 2:
        raise ControlledShadowPilotError("PA5_REVIEWER_DENOMINATOR_MISSING", "reviewers")
    status = str(record.get("shadow_review_status"))
    if status not in SHADOW_STATUSES:
        raise ControlledShadowPilotError("PA5_STATUS_INVALID", status)
    if status == "shadow_answer_reviewed" and record.get("refusal_reason_codes"):
        raise ControlledShadowPilotError("PA5_ANSWER_HAS_REFUSAL", status)
    if status != "shadow_answer_reviewed" and not record.get("refusal_reason_codes"):
        raise ControlledShadowPilotError("PA5_REFUSAL_REASON_REQUIRED", status)
    return dict(record)


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    index = max(0, math.ceil(len(values) * 0.95) - 1)
    return sorted(values)[index]


def run_shadow_pilot_benchmark(
    question_population: Mapping[str, Any],
    shadow_policy: Mapping[str, Any],
) -> dict[str, Any]:
    verify_self_digest(question_population)
    if question_population.get("schema_version") != CASES_SCHEMA:
        raise ControlledShadowPilotError("PA5_POPULATION_INVALID", "schema mismatch")
    policy = validate_shadow_policy(shadow_policy)
    questions = question_population.get("questions", [])
    if not isinstance(questions, list):
        raise ControlledShadowPilotError("PA5_POPULATION_INVALID", "questions missing")
    minimum = int(policy["pilot_policy"]["population_min"])
    maximum = int(policy["pilot_policy"]["population_max"])
    if not minimum <= len(questions) <= maximum:
        raise ControlledShadowPilotError("PA5_POPULATION_INVALID", "population outside bounds")
    records = []
    results = []
    for question in questions:
        if not isinstance(question, Mapping):
            raise ControlledShadowPilotError("PA5_QUESTION_INVALID", "question must be an object")
        record = compile_shadow_review_record(question, policy)
        expected = question.get("expected", {})
        failures: list[str] = []
        if (
            not isinstance(expected, Mapping)
            or record["shadow_review_status"] != expected.get("status")
        ):
            failures.append("status")
        if expected.get("requires_public_answer_zero") and record["public_answer"] is not False:
            failures.append("public_answer")
        records.append(record)
        results.append(
            {
                "question_id": question["question_id"],
                "passed": not failures,
                "failures": failures,
                "shadow_review_status": record["shadow_review_status"],
                "reviewer_count": record["reviewer_count"],
                "latency_ms": record["latency_ms"],
                "cost_usd": record["cost_usd"],
                "record_sha256": record["self_sha256"],
            }
        )
    passed = sum(item["passed"] for item in results)
    latencies = [int(record["latency_ms"]) for record in records]
    return with_self_digest(
        {
            "schema_version": BENCHMARK_SCHEMA,
            "stage_id": "M26.PA.5",
            "status": (
                "m26_pa_5_controlled_internal_shadow_pilot_ready"
                if passed == len(results)
                else "m26_pa_5_controlled_internal_shadow_pilot_repair_required"
            ),
            "question_count": len(records),
            "passed_count": passed,
            "failed_count": len(results) - passed,
            "complete_denominator": True,
            "metrics": {
                "answer_reviewed_count": sum(
                    record["shadow_review_status"] == "shadow_answer_reviewed"
                    for record in records
                ),
                "abstention_reviewed_count": sum(
                    record["shadow_review_status"] == "shadow_abstention_reviewed"
                    for record in records
                ),
                "hold_for_repair_count": sum(
                    record["shadow_review_status"] == "shadow_hold_for_repair"
                    for record in records
                ),
                "authority_rejection_count": sum(
                    record["shadow_review_status"] == "shadow_rejected_authority_escalation"
                    for record in records
                ),
                "min_reviewer_count": min(record["reviewer_count"] for record in records),
                "latency_p95_ms": _p95(latencies),
                "total_cost_usd": round(sum(float(record["cost_usd"]) for record in records), 6),
                "min_reviewer_agreement": round(
                    min(float(record["reviewer_agreement"]) for record in records), 6
                ),
                "public_answer_count": 0,
                "public_traffic_count": 0,
                "production_answer_serving_count": 0,
                "production_pointer_mutation_count": 0,
            },
            "record_sha256s": [record["self_sha256"] for record in records],
            "results": results,
        }
    )
