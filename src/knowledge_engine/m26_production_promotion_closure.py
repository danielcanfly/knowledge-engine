from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import IntegrityError
from .m26_retrieval_envelope import verify_self_digest, with_self_digest

POLICY_SCHEMA = "knowledge-engine-m26-pa-7-final-decision-policy/v1"
CASES_SCHEMA = "knowledge-engine-m26-pa-7-final-decision-cases/v1"
RECORD_SCHEMA = "knowledge-engine-m26-pa-7-final-decision-record/v1"
BENCHMARK_SCHEMA = "knowledge-engine-m26-pa-7-production-closure-benchmark/v1"
PREDECESSOR_STATUS = "m26_pa_6_canary_slo_rollback_accepted"

EVIDENCE_CHAIN_STATUSES = (
    "m25_closed",
    "m26_g0_milestone_reconciliation_accepted",
    "m26_pa_1_production_activation_authority_freeze_accepted",
    "m26_pa_2_real_corpus_retrieval_binding_accepted",
    "m26_pa_3_live_provider_execution_accepted",
    "m26_pa_4_verified_answer_citation_gate_accepted",
    "m26_pa_5_controlled_internal_shadow_pilot_accepted",
    "m26_pa_6_canary_slo_rollback_accepted",
)
DECISION_STATUSES = {
    "approved_bounded_production_promotion",
    "approved_with_conditions",
    "governed_defer",
    "rejected_pending_redesign",
}


class ProductionPromotionClosureError(IntegrityError):
    """Fail-closed M26.PA.7 contract error with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def validate_final_decision_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(policy)
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise ProductionPromotionClosureError("PA7_POLICY_INVALID", "schema mismatch")
    if policy.get("accepted_predecessor_status") != PREDECESSOR_STATUS:
        raise ProductionPromotionClosureError("PREDECESSOR_NOT_ACCEPTED", "PA.6 is not pinned")
    authority = policy.get("authority")
    decision_policy = policy.get("decision_policy")
    if not all(isinstance(item, Mapping) for item in (authority, decision_policy)):
        raise ProductionPromotionClosureError("PA7_POLICY_INVALID", "sections are missing")
    required_true = (
        "complete_evidence_chain",
        "daniel_final_decision",
        "bounded_outcome_required",
        "independent_final_reconciliation",
        "formal_m26_closure",
    )
    if any(authority.get(key) is not True for key in required_true):
        raise ProductionPromotionClosureError("PA7_AUTHORITY_INVALID", "required gate disabled")
    required_false = (
        "secret_persistence",
        "unbounded_production_promotion",
        "source_foundation_release_mutation",
        "qdrant_writes_without_approval",
        "r2_writes_without_approval",
    )
    if any(authority.get(key) is not False for key in required_false):
        raise ProductionPromotionClosureError("PA7_AUTHORITY_INVALID", "forbidden authority")
    if set(decision_policy.get("valid_outcomes", [])) != DECISION_STATUSES:
        raise ProductionPromotionClosureError("PA7_DECISION_POLICY_INVALID", "outcomes mismatch")
    return dict(policy)


def _chain_complete(packet: Mapping[str, Any]) -> bool:
    statuses = tuple(str(item.get("status")) for item in packet.get("evidence_chain", []))
    return statuses == EVIDENCE_CHAIN_STATUSES


def compile_final_decision_record(
    decision_packet: Mapping[str, Any],
    final_decision_policy: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_final_decision_policy(final_decision_policy)
    decision = str(decision_packet.get("decision_status", ""))
    protected = decision_packet.get("protected_mutations", {})
    protected_failures: list[str] = []
    if not isinstance(protected, Mapping):
        protected_failures.append("PROTECTED_MUTATION_SECTION_MISSING")
        protected = {}
    for key in (
        "secret_persistence",
        "source_foundation_release_mutation",
        "qdrant_write",
        "r2_write",
        "unbounded_public_traffic",
    ):
        if protected.get(key) is not False:
            protected_failures.append(key.upper())
    chain_complete = _chain_complete(decision_packet)
    if decision not in DECISION_STATUSES:
        final_status = "rejected_pending_redesign"
        reasons = ["DECISION_STATUS_INVALID"]
    elif protected_failures:
        final_status = "rejected_pending_redesign"
        reasons = protected_failures
    elif not chain_complete:
        final_status = "governed_defer"
        reasons = ["EVIDENCE_CHAIN_INCOMPLETE"]
    else:
        final_status = decision
        reasons = [str(item) for item in decision_packet.get("conditions", [])]
    promotion_authorized = final_status in {
        "approved_bounded_production_promotion",
        "approved_with_conditions",
    }
    record = with_self_digest(
        {
            "schema_version": RECORD_SCHEMA,
            "stage_id": "M26.PA.7",
            "case_id": str(decision_packet.get("case_id", "")),
            "predecessor_status": PREDECESSOR_STATUS,
            "decision_status": final_status,
            "decision_maker": str(decision_packet.get("decision_maker", "Daniel Huang")),
            "evidence_chain_complete": chain_complete,
            "evidence_chain_statuses": list(EVIDENCE_CHAIN_STATUSES),
            "bounded_outcome": final_status in DECISION_STATUSES,
            "production_promotion_authorized": promotion_authorized,
            "production_promotion_execution": False,
            "production_pointer_mutation": False,
            "public_traffic_mutation": False,
            "secret_values_persisted": False,
            "source_foundation_release_mutation": False,
            "independent_final_reconciliation_required": True,
            "formal_m26_closure": True,
            "conditions_or_reasons": reasons,
            "closure_status": policy["decision_policy"]["closure_ready_status"],
        }
    )
    validate_final_decision_record(record)
    return record


def validate_final_decision_record(record: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(record)
    if record.get("schema_version") != RECORD_SCHEMA:
        raise ProductionPromotionClosureError("PA7_RECORD_INVALID", "schema mismatch")
    if record.get("stage_id") != "M26.PA.7":
        raise ProductionPromotionClosureError("PA7_RECORD_INVALID", "stage mismatch")
    status = str(record.get("decision_status"))
    if status not in DECISION_STATUSES:
        raise ProductionPromotionClosureError("PA7_DECISION_INVALID", status)
    for key in (
        "production_promotion_execution",
        "production_pointer_mutation",
        "public_traffic_mutation",
        "secret_values_persisted",
        "source_foundation_release_mutation",
    ):
        if record.get(key) is not False:
            raise ProductionPromotionClosureError("PA7_AUTHORITY_ESCALATION", key)
    if record.get("bounded_outcome") is not True:
        raise ProductionPromotionClosureError("PA7_BOUNDED_OUTCOME_REQUIRED", status)
    if record.get("formal_m26_closure") is not True:
        raise ProductionPromotionClosureError("PA7_CLOSURE_REQUIRED", status)
    if record.get("evidence_chain_statuses") != list(EVIDENCE_CHAIN_STATUSES):
        raise ProductionPromotionClosureError("PA7_CHAIN_STATUS_DRIFT", status)
    return dict(record)


def run_production_closure_benchmark(
    decision_cases_artifact: Mapping[str, Any],
    final_decision_policy: Mapping[str, Any],
) -> dict[str, Any]:
    verify_self_digest(decision_cases_artifact)
    if decision_cases_artifact.get("schema_version") != CASES_SCHEMA:
        raise ProductionPromotionClosureError("PA7_CASES_INVALID", "schema mismatch")
    records = []
    results = []
    for case in decision_cases_artifact.get("cases", []):
        if not isinstance(case, Mapping):
            raise ProductionPromotionClosureError("PA7_CASE_INVALID", "case must be an object")
        record = compile_final_decision_record(case, final_decision_policy)
        expected = case.get("expected", {})
        failures: list[str] = []
        if not isinstance(expected, Mapping) or record["decision_status"] != expected.get("status"):
            failures.append("status")
        if (
            expected.get("requires_promotion_authority")
            and record["production_promotion_authorized"] is not True
        ):
            failures.append("promotion_authority")
        records.append(record)
        results.append(
            {
                "case_id": case["case_id"],
                "passed": not failures,
                "failures": failures,
                "decision_status": record["decision_status"],
                "production_promotion_authorized": record["production_promotion_authorized"],
                "record_sha256": record["self_sha256"],
            }
        )
    passed = sum(item["passed"] for item in results)
    return with_self_digest(
        {
            "schema_version": BENCHMARK_SCHEMA,
            "stage_id": "M26.PA.7",
            "status": (
                "m26_pa_7_production_answer_authority_and_closure_ready"
                if passed == len(results)
                else "m26_pa_7_production_answer_authority_and_closure_repair_required"
            ),
            "case_count": len(records),
            "passed_count": passed,
            "failed_count": len(results) - passed,
            "metrics": {
                "approved_bounded_count": sum(
                    record["decision_status"] == "approved_bounded_production_promotion"
                    for record in records
                ),
                "approved_with_conditions_count": sum(
                    record["decision_status"] == "approved_with_conditions"
                    for record in records
                ),
                "governed_defer_count": sum(
                    record["decision_status"] == "governed_defer" for record in records
                ),
                "rejected_pending_redesign_count": sum(
                    record["decision_status"] == "rejected_pending_redesign"
                    for record in records
                ),
                "promotion_authorized_count": sum(
                    record["production_promotion_authorized"] for record in records
                ),
                "production_promotion_execution_count": 0,
                "production_pointer_mutation_count": 0,
                "public_traffic_mutation_count": 0,
            },
            "record_sha256s": [record["self_sha256"] for record in records],
            "results": results,
        }
    )
