from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError

SCHEMA_VERSION = "knowledge-engine-m23-7-8-final-decision/v1"
REPORT_SCHEMA_VERSION = "knowledge-engine-m23-7-8-final-decision-report/v1"
HANDOFF_SCHEMA_VERSION = "knowledge-engine-m23-7-8-repair-handoff/v1"
ENTRY_ENGINE_SHA = "d8f3790e622a744322953af1019776ad6ccdb5eb"
SOURCE_PR_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
DECISION = "repair"
DECISION_PACKET_SHA256 = (
    "89e5f6c8e748e089d0360ffc6a440b91bbb85a157397c1e6a9aa706f26a10f18"
)
REPORT_SHA256 = "b8d4278dec2c777a2ed3c888ff20f8e5d4e5a80315dc8b15179f4e63045fe92f"
REPAIR_HANDOFF_SHA256 = (
    "7fb6fadf91f1a09110bf1d0e653652f52a298ebc0119aee3743180314e16f0b9"
)

BLOCKERS = (
    "blocked_pending_latency",
    "blocked_pending_retrieval_quality",
)

EVIDENCE_CHAIN = (
    (
        "M23.7.1",
        "contract",
        "7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1",
        "pass",
    ),
    (
        "M23.7.2",
        "offline_retrieval_evaluation",
        "9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce",
        "pass",
    ),
    (
        "M23.7.3",
        "shadow_replay",
        "b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2",
        "pass",
    ),
    (
        "M23.7.4",
        "candidate_answer_composition",
        "6e50c809e777c99d351fb297bef2a672bf8a462dc4b4ebf2a9ff5b4593601ae7",
        "pass",
    ),
    (
        "M23.7.5",
        "bounded_live_observation",
        "c8e7d3d672bc848ab22cdef8ca55b8ed444aacae294c4d662e018bedb7ed4e71",
        "completed_fail_closed",
    ),
    (
        "M23.7.6",
        "failure_rebuild_rollback",
        "a394195ffd207028f9f9606b4c8cfc745687edb593185efbda5cf25dafe452e1",
        "pass",
    ),
    (
        "M23.7.7",
        "operator_closeout",
        "e60e6825d72f8848b90cf55f2c14e8bb70c6cf0dda5990feadb28b013bbedce8",
        "qualified_with_blockers",
    ),
    (
        "M23.7.7",
        "final_readiness_packet",
        "93234c4ce6f225c41563427ce3b2cff7e35bf6f9471f0f9ca47642e79281260a",
        "hold_for_m23_7_8",
    ),
    (
        "M23.7.7",
        "final_readiness_report",
        "c81800a4626ba8c96e201a0bc7a0d0a63f61c3328bde93cb124d0f18aa8aa48f",
        "pass",
    ),
)

PROTECTED_MUTATIONS = (
    "answer_serving",
    "credential_rotation",
    "deployment",
    "graph_neural_retrieval",
    "live_traffic",
    "permanent_ledger",
    "production_pointer",
    "production_query_mirroring",
    "promotion",
    "public_graph_explorer",
    "qdrant_delete",
    "qdrant_write",
    "r2_mutation",
    "source_mutation",
    "source_pr_19_merge",
    "user_sampling",
    "worker_queue_mutation",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7.8-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), 101, f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    _require(
        not isinstance(value, (str, bytes)) and isinstance(value, Sequence),
        102,
        f"{label} must be a list",
    )
    return tuple(value)


def _repair_workstreams() -> list[dict[str, Any]]:
    return [
        {
            "id": "R1",
            "name": "live_probe_semantic_alignment",
            "objective": (
                "align bounded synthetic live probes with the frozen held-out "
                "retrieval intent without user queries"
            ),
            "required_evidence": [
                "versioned_synthetic_probe_manifest",
                "offline_to_live_query_identity_mapping",
                "deterministic_expected_relevance_set",
                "independent_reconciliation",
            ],
            "authority": "offline_and_read_only",
        },
        {
            "id": "R2",
            "name": "latency_path",
            "objective": (
                "reduce provider_and_qdrant_shadow_p95_below_locked_budget_"
                "without_budget_inflation"
            ),
            "required_evidence": [
                "component_latency_receipts",
                "connection_reuse_preserved",
                "regional_or_binding_path_comparison",
                "locked_1200ms_budget",
            ],
            "authority": "non_production_only",
        },
        {
            "id": "R3",
            "name": "bounded_live_reobservation",
            "objective": (
                "repeat_privacy_safe_bounded_live_observation_after_R1_and_R2"
            ),
            "required_evidence": [
                "maximum_8_synthetic_probes",
                "zero_error_acl_and_output_influence_rates",
                "shadow_p95_at_or_below_1200ms",
                "retrieval_quality_blocker_cleared",
                "independent_acceptance_reconciliation",
            ],
            "authority": "read_only_no_output_influence",
        },
    ]


def canonical_decision_packet() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7.8",
        "parent_issue": 408,
        "implementation_issue": 455,
        "entry_engine_sha": ENTRY_ENGINE_SHA,
        "decision": DECISION,
        "decision_options": {
            "promote": {
                "selected": False,
                "available": False,
                "reason": "blocked_by_live_latency_and_retrieval_quality",
            },
            "hold": {
                "selected": False,
                "available": True,
                "reason": "safe_but_non_actionable",
            },
            "repair": {
                "selected": True,
                "available": True,
                "reason": (
                    "positive_offline_and_reliability_evidence_with_two_"
                    "bounded_live_blockers"
                ),
            },
            "reject": {
                "selected": False,
                "available": True,
                "reason": (
                    "disproportionate_to_positive_offline_reliability_and_"
                    "operator_evidence"
                ),
            },
        },
        "evidence_chain": [
            {
                "milestone": milestone,
                "kind": kind,
                "sha256": digest,
                "status": status,
            }
            for milestone, kind, digest, status in EVIDENCE_CHAIN
        ],
        "positive_evidence": {
            "offline_retrieval_metrics_passed": True,
            "offline_security_rates_zero": True,
            "candidate_answer_grounding_passed": True,
            "failure_isolation_passed": True,
            "deterministic_rebuild_passed": True,
            "lexical_rollback_passed": True,
            "operator_qualification": {
                "status": "qualified_with_blockers",
                "tasks_passed": 10,
                "tasks_total": 10,
            },
        },
        "blocking_evidence": {
            "carry_forward_blockers": list(BLOCKERS),
            "latency": {
                "cleared": False,
                "canonical_shadow_p95_budget_ms": 1200,
                "observed_post_repair_shadow_p95_ms": 1731,
                "over_budget_ms": 531,
                "budget_changed": False,
            },
            "retrieval_quality": {
                "cleared": False,
                "live_overlap_at_5_mean": 0.25,
                "live_overlap_drift": -0.7,
            },
        },
        "repair_workstreams": _repair_workstreams(),
        "future_promotion_preconditions": {
            "all_blockers_cleared_by_new_evidence": True,
            "R1_complete": True,
            "R2_complete": True,
            "R3_complete": True,
            "new_explicit_promotion_decision_required": True,
        },
        "source_pr_19": {
            "state": "open",
            "draft": True,
            "merged": False,
            "head_sha": SOURCE_PR_HEAD,
        },
        "production": {
            "retrieval": "lexical",
            "response_authority": "lexical",
            "candidate_mode_enabled": False,
            "semantic_output_served": False,
            "promotion_eligibility_granted": False,
        },
        "phase_closure": {
            "m23_7_status": "complete_with_repair_decision",
            "parent_issue_may_close_after_reconciliation": True,
            "next_legal_action": "open_separately_governed_repair_workstreams",
        },
        "protected_mutations": {key: False for key in PROTECTED_MUTATIONS},
    }


def validate_decision_packet(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(_mapping(payload, "decision packet"))
    expected = canonical_decision_packet()
    _require(set(root) == set(expected), 103, "packet shape drifted")
    _require(root["decision"] == DECISION, 104, "final decision drifted")
    _require(root["entry_engine_sha"] == ENTRY_ENGINE_SHA, 105, "entry SHA drifted")

    options = _mapping(root["decision_options"], "decision options")
    _require(set(options) == {"promote", "hold", "repair", "reject"}, 106, "option set drifted")
    selected = [name for name, item in options.items() if _mapping(item, name)["selected"]]
    _require(selected == ["repair"], 107, "exactly repair must be selected")
    _require(options["promote"]["available"] is False, 108, "promote became available")

    chain = [dict(_mapping(row, "chain row")) for row in _sequence(root["evidence_chain"], "chain")]
    _require(chain == expected["evidence_chain"], 109, "evidence chain drifted")

    blocking = _mapping(root["blocking_evidence"], "blocking evidence")
    _require(tuple(blocking["carry_forward_blockers"]) == BLOCKERS, 110, "blockers changed")
    latency = _mapping(blocking["latency"], "latency evidence")
    _require(latency == expected["blocking_evidence"]["latency"], 111, "latency evidence drifted")
    _require(latency["budget_changed"] is False, 112, "latency budget was inflated")
    retrieval = _mapping(blocking["retrieval_quality"], "retrieval evidence")
    _require(retrieval == expected["blocking_evidence"]["retrieval_quality"], 113, "retrieval evidence drifted")

    workstreams = [dict(_mapping(row, "workstream")) for row in _sequence(root["repair_workstreams"], "workstreams")]
    _require(workstreams == expected["repair_workstreams"], 114, "repair workstreams drifted")
    _require([row["id"] for row in workstreams] == ["R1", "R2", "R3"], 115, "repair order drifted")

    preconditions = _mapping(root["future_promotion_preconditions"], "preconditions")
    _require(preconditions == expected["future_promotion_preconditions"], 116, "promotion preconditions drifted")
    _require(all(preconditions.values()), 117, "promotion prerequisite was removed")

    _require(root["source_pr_19"] == expected["source_pr_19"], 118, "Source PR #19 drifted")
    _require(root["production"] == expected["production"], 119, "production authority drifted")
    protected = _mapping(root["protected_mutations"], "protected mutations")
    _require(set(protected) == set(PROTECTED_MUTATIONS), 120, "protected mutation set drifted")
    _require(all(protected[key] is False for key in PROTECTED_MUTATIONS), 121, "protected mutation dispatched")
    _require(canonical_sha256(root) == DECISION_PACKET_SHA256, 122, "packet digest drifted")
    return root


def build_repair_handoff(payload: Mapping[str, Any]) -> dict[str, Any]:
    packet = validate_decision_packet(payload)
    handoff = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "milestone": "M23.7.8",
        "decision": packet["decision"],
        "decision_packet_sha256": canonical_sha256(packet),
        "carry_forward_blockers": list(BLOCKERS),
        "workstreams": packet["repair_workstreams"],
        "promotion_preconditions": packet["future_promotion_preconditions"],
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "promotion_eligibility_granted": False,
            "source_pr_19_merge_authorized": False,
            "qdrant_write_authorized": False,
            "production_mutation_dispatched": False,
        },
    }
    _require(canonical_sha256(handoff) == REPAIR_HANDOFF_SHA256, 123, "handoff digest drifted")
    return handoff


def build_decision_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    packet = validate_decision_packet(payload)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "milestone": "M23.7.8",
        "status": "pass",
        "decision": packet["decision"],
        "decision_packet_sha256": canonical_sha256(packet),
        "m23_7_status": "complete_with_repair_decision",
        "carry_forward_blockers": list(BLOCKERS),
        "repair_workstream_count": 3,
        "promotion_eligibility_granted": False,
        "candidate_mode_enabled": False,
        "production_authority": False,
        "production_retrieval": "lexical",
        "parent_issue_closure_authorized_after_reconciliation": True,
        "protected_mutations_dispatched": False,
    }
    _require(canonical_sha256(report) == REPORT_SHA256, 124, "report digest drifted")
    return report
