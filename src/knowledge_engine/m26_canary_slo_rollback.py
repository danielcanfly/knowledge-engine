from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m26_retrieval_envelope import verify_self_digest, with_self_digest

POLICY_SCHEMA = "knowledge-engine-m26-pa-6-canary-policy/v1"
CASES_SCHEMA = "knowledge-engine-m26-pa-6-canary-benchmark-cases/v1"
RECORD_SCHEMA = "knowledge-engine-m26-pa-6-canary-record/v1"
BENCHMARK_SCHEMA = "knowledge-engine-m26-pa-6-canary-benchmark/v1"
PREDECESSOR_STATUS = "m26_pa_5_controlled_internal_shadow_pilot_accepted"

CANARY_STATUSES = {
    "canary_ready",
    "canary_stopped_by_slo",
    "canary_hold_for_rollback",
    "canary_rejected_authority_escalation",
}


class CanarySloRollbackError(IntegrityError):
    """Fail-closed M26.PA.6 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def validate_canary_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise CanarySloRollbackError("PA6_POLICY_INVALID", "schema mismatch")
    if policy.get("accepted_predecessor_status") != PREDECESSOR_STATUS:
        raise CanarySloRollbackError("PREDECESSOR_NOT_ACCEPTED", "PA.5 is not pinned")
    authority = policy.get("authority")
    canary_policy = policy.get("canary_policy")
    status_policy = policy.get("status_policy")
    if not all(isinstance(item, Mapping) for item in (authority, canary_policy, status_policy)):
        raise CanarySloRollbackError("PA6_POLICY_INVALID", "sections are missing")
    required_true = (
        "bounded_canary",
        "audience_allowlist",
        "traffic_allowlist",
        "slo_enforcement",
        "error_budget",
        "kill_switch",
        "automatic_stop_conditions",
        "rollback_plan",
        "rollback_drill_completed",
    )
    if any(authority.get(key) is not True for key in required_true):
        raise CanarySloRollbackError("PA6_AUTHORITY_INVALID", "required gate disabled")
    if authority.get("full_production_promotion") is not False:
        raise CanarySloRollbackError("PA6_AUTHORITY_INVALID", "full production enabled")
    if authority.get("source_foundation_release_mutation") is not False:
        raise CanarySloRollbackError("PA6_AUTHORITY_INVALID", "protected mutation enabled")
    if float(canary_policy.get("max_traffic_percent", 0.0)) <= 0:
        raise CanarySloRollbackError("PA6_TRAFFIC_BOUND_INVALID", "max traffic invalid")
    if len(canary_policy.get("automatic_stop_conditions", [])) < 10:
        raise CanarySloRollbackError("PA6_STOP_CONDITIONS_INCOMPLETE", "too few stops")
    if canary_policy.get("kill_switch", {}).get("enabled") is not True:
        raise CanarySloRollbackError("PA6_KILL_SWITCH_INVALID", "kill switch missing")
    if canary_policy.get("rollback", {}).get("drill_completed") is not True:
        raise CanarySloRollbackError("PA6_ROLLBACK_INVALID", "rollback drill missing")
    if set(status_policy.values()) - CANARY_STATUSES:
        raise CanarySloRollbackError("PA6_STATUS_POLICY_INVALID", "unknown status")
    return dict(policy)


def compile_canary_record(
    canary_case: Mapping[str, Any],
    canary_policy: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_canary_policy(canary_policy)
    canary = canary_case.get("canary")
    if not isinstance(canary, Mapping):
        raise CanarySloRollbackError("PA6_CASE_INVALID", "canary data missing")
    traffic_percent = float(canary.get("traffic_percent", 0.0))
    authority_failures: list[str] = []
    if canary.get("allowlisted_audience") is not True:
        authority_failures.append("AUDIENCE_NOT_ALLOWLISTED")
    if canary.get("allowlisted_route") is not True:
        authority_failures.append("ROUTE_NOT_ALLOWLISTED")
    if canary.get("full_production_traffic") is not False:
        authority_failures.append("FULL_PRODUCTION_TRAFFIC_ESCALATION")
    if traffic_percent > float(policy["canary_policy"]["max_traffic_percent"]):
        authority_failures.append("TRAFFIC_BOUND_EXCEEDED")
    if canary.get("production_pointer_mutation") is not False:
        authority_failures.append("PRODUCTION_POINTER_ESCALATION")
    if authority_failures:
        status = policy["status_policy"]["authority_rejected_status"]
        stop_codes = sorted(set(authority_failures))
    elif (
        canary.get("kill_switch_available") is not True
        or canary.get("rollback_drill_completed") is not True
    ):
        status = policy["status_policy"]["rollback_hold_status"]
        stop_codes = ["ROLLBACK_OR_KILL_SWITCH_MISSING"]
    elif (
        int(canary.get("latency_p95_ms", 0)) > int(policy["canary_policy"]["slo"]["latency_p95_ms"])
        or float(canary.get("error_rate", 0.0))
        > float(policy["canary_policy"]["slo"]["max_error_rate"])
        or float(canary.get("cost_usd", 0.0))
        > float(policy["canary_policy"]["slo"]["max_cost_usd"])
        or int(canary.get("unsupported_claim_count", 0)) > 0
        or canary.get("rollback_required") is True
    ):
        status = policy["status_policy"]["stopped_status"]
        stop_codes = [str(item) for item in canary.get("stop_codes", ["SLO_OR_ROLLBACK_STOP"])]
    else:
        status = policy["status_policy"]["ready_status"]
        stop_codes = []
    record = with_self_digest(
        {
            "schema_version": RECORD_SCHEMA,
            "stage_id": "M26.PA.6",
            "case_id": str(canary_case.get("case_id", "")),
            "predecessor_status": PREDECESSOR_STATUS,
            "canary_status": status,
            "bounded_canary": True,
            "allowlisted_audience": bool(canary.get("allowlisted_audience")),
            "allowlisted_route": bool(canary.get("allowlisted_route")),
            "traffic_percent": traffic_percent,
            "latency_p95_ms": int(canary.get("latency_p95_ms", 0)),
            "error_rate": float(canary.get("error_rate", 0.0)),
            "cost_usd": float(canary.get("cost_usd", 0.0)),
            "unsupported_claim_count": int(canary.get("unsupported_claim_count", 0)),
            "kill_switch_available": bool(canary.get("kill_switch_available")),
            "rollback_drill_completed": bool(canary.get("rollback_drill_completed")),
            "stop_codes": stop_codes,
            "full_production_traffic": False,
            "production_pointer_mutation": False,
            "source_foundation_release_mutation": False,
            "safe_for_pa7": status in {
                policy["status_policy"]["ready_status"],
                policy["status_policy"]["stopped_status"],
            },
        }
    )
    validate_canary_record(record)
    return record


def validate_canary_record(record: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(record)
    if record.get("schema_version") != RECORD_SCHEMA:
        raise CanarySloRollbackError("PA6_RECORD_INVALID", "schema mismatch")
    if record.get("stage_id") != "M26.PA.6":
        raise CanarySloRollbackError("PA6_RECORD_INVALID", "stage mismatch")
    if record.get("bounded_canary") is not True:
        raise CanarySloRollbackError("PA6_RECORD_INVALID", "bounded canary missing")
    for key in (
        "full_production_traffic",
        "production_pointer_mutation",
        "source_foundation_release_mutation",
    ):
        if record.get(key) is not False:
            raise CanarySloRollbackError("PA6_AUTHORITY_ESCALATION", key)
    status = str(record.get("canary_status"))
    if status not in CANARY_STATUSES:
        raise CanarySloRollbackError("PA6_STATUS_INVALID", status)
    if status == "canary_ready" and record.get("stop_codes"):
        raise CanarySloRollbackError("PA6_READY_HAS_STOP_CODES", status)
    if status != "canary_ready" and not record.get("stop_codes"):
        raise CanarySloRollbackError("PA6_STOP_CODES_REQUIRED", status)
    return dict(record)


def run_canary_benchmark(
    canary_cases_artifact: Mapping[str, Any],
    canary_policy: Mapping[str, Any],
) -> dict[str, Any]:
    verify_self_digest(canary_cases_artifact)
    if canary_cases_artifact.get("schema_version") != CASES_SCHEMA:
        raise CanarySloRollbackError("PA6_CASES_INVALID", "schema mismatch")
    policy = validate_canary_policy(canary_policy)
    records = []
    results = []
    for case in canary_cases_artifact.get("cases", []):
        if not isinstance(case, Mapping):
            raise CanarySloRollbackError("PA6_CASE_INVALID", "case must be an object")
        record = compile_canary_record(case, policy)
        expected = case.get("expected", {})
        failures: list[str] = []
        if not isinstance(expected, Mapping) or record["canary_status"] != expected.get("status"):
            failures.append("status")
        records.append(record)
        results.append(
            {
                "case_id": case["case_id"],
                "passed": not failures,
                "failures": failures,
                "canary_status": record["canary_status"],
                "traffic_percent": record["traffic_percent"],
                "record_sha256": record["self_sha256"],
            }
        )
    passed = sum(item["passed"] for item in results)
    authorized_records = [
        record
        for record in records
        if record["canary_status"] != policy["status_policy"]["authority_rejected_status"]
    ]
    return with_self_digest(
        {
            "schema_version": BENCHMARK_SCHEMA,
            "stage_id": "M26.PA.6",
            "status": (
                "m26_pa_6_canary_slo_rollback_ready"
                if passed == len(results)
                else "m26_pa_6_canary_slo_rollback_repair_required"
            ),
            "case_count": len(records),
            "passed_count": passed,
            "failed_count": len(results) - passed,
            "metrics": {
                "canary_ready_count": sum(
                    record["canary_status"] == "canary_ready" for record in records
                ),
                "canary_stopped_count": sum(
                    record["canary_status"] == "canary_stopped_by_slo" for record in records
                ),
                "rollback_hold_count": sum(
                    record["canary_status"] == "canary_hold_for_rollback" for record in records
                ),
                "authority_rejection_count": sum(
                    record["canary_status"] == "canary_rejected_authority_escalation"
                    for record in records
                ),
                "max_attempted_traffic_percent": max(
                    record["traffic_percent"] for record in records
                ),
                "max_authorized_traffic_percent": max(
                    record["traffic_percent"] for record in authorized_records
                ),
                "automatic_stop_condition_count": len(
                    policy["canary_policy"]["automatic_stop_conditions"]
                ),
                "kill_switch_verified": policy["canary_policy"]["kill_switch"]["enabled"] is True,
                "rollback_drill_completed": (
                    policy["canary_policy"]["rollback"]["drill_completed"] is True
                ),
                "full_production_traffic_count": 0,
                "production_pointer_mutation_count": 0,
            },
            "record_sha256s": [record["self_sha256"] for record in records],
            "results": results,
        }
    )
