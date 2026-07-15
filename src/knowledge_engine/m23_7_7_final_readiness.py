from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError

SCHEMA_VERSION = "knowledge-engine-m23-7-7-final-readiness/v1"
REPORT_SCHEMA_VERSION = "knowledge-engine-m23-7-7-final-readiness-report/v1"
ENTRY_ENGINE_SHA = "a71d3e0e6f42b8de4f6c370bd988c7505161567f"
SOURCE_PR_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
CANDIDATE_RELEASE = "m23cand-c7fbec7e945e79d05d3263b0"
CANDIDATE_MANIFEST = (
    "3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560"
)
READINESS_DECISION = "hold_for_m23_7_8"
PACKET_SHA256 = "93234c4ce6f225c41563427ce3b2cff7e35bf6f9471f0f9ca47642e79281260a"
REPORT_SHA256 = "c81800a4626ba8c96e201a0bc7a0d0a63f61c3328bde93cb124d0f18aa8aa48f"

CARRY_FORWARD_BLOCKERS = (
    "blocked_pending_latency",
    "blocked_pending_retrieval_quality",
)

CHAIN = (
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
    "promotion_decision",
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
        raise IntegrityError(f"M23.7.7-{code} {message}")


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


def canonical_readiness_packet() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7.7",
        "parent_issue": 408,
        "implementation_issue": 451,
        "entry_engine_sha": ENTRY_ENGINE_SHA,
        "m23_7_chain": [
            {
                "milestone": milestone,
                "kind": kind,
                "sha256": sha256,
                "status": status,
            }
            for milestone, kind, sha256, status in CHAIN
        ],
        "m23_7_6_rebuild_descriptor_sha256": (
            "53e048805c60e9c08d23c67cc96e0b84ae75c0ee9fe121c1776cd28c5053e8e7"
        ),
        "candidate": {
            "release_id": CANDIDATE_RELEASE,
            "manifest_sha256": CANDIDATE_MANIFEST,
            "promotion_eligibility_granted": False,
            "candidate_mode_enabled": False,
        },
        "qdrant": {
            "collection": "llm_wiki_m23_pilot_bge_m3_1024",
            "points": 107,
            "vector_name": "default",
            "vector_dimension": 1024,
            "distance": "Cosine",
            "write_authorized": False,
            "delete_authorized": False,
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
            "semantic_output_served": False,
            "candidate_output_served": False,
        },
        "carry_forward_blockers": list(CARRY_FORWARD_BLOCKERS),
        "m23_7_5_blocker_evidence": {
            "latency_budget_passed": False,
            "retrieval_drift_clear": False,
            "post_repair_shadow_p95_ms": 1731,
            "canonical_shadow_p95_budget_ms": 1200,
            "overlap_at_5_mean": 0.25,
            "overlap_drift": -0.7,
        },
        "readiness_decision": READINESS_DECISION,
        "m23_7_8_decision_options": {
            "promote": {
                "currently_available": False,
                "requires_blockers_cleared": list(CARRY_FORWARD_BLOCKERS),
            },
            "hold": {"currently_available": True},
            "repair": {"currently_available": True},
            "reject": {"currently_available": True},
        },
        "protected_mutations": {key: False for key in PROTECTED_MUTATIONS},
    }


def validate_readiness_packet(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(_mapping(payload, "readiness packet"))
    expected = canonical_readiness_packet()
    _require(set(root) == set(expected), 103, "packet shape drifted")
    _require(root["schema_version"] == SCHEMA_VERSION, 104, "schema drifted")
    _require(root["milestone"] == "M23.7.7", 105, "milestone drifted")
    _require(root["entry_engine_sha"] == ENTRY_ENGINE_SHA, 106, "entry SHA drifted")

    chain = [
        dict(_mapping(row, "chain row"))
        for row in _sequence(root["m23_7_chain"], "chain")
    ]
    expected_chain = expected["m23_7_chain"]
    _require(chain == expected_chain, 107, "M23.7 evidence chain drifted")
    _require(
        [row["milestone"] for row in chain]
        == [
            "M23.7.1",
            "M23.7.2",
            "M23.7.3",
            "M23.7.4",
            "M23.7.5",
            "M23.7.6",
        ],
        108,
        "M23.7 milestone order drifted",
    )

    blockers = tuple(_sequence(root["carry_forward_blockers"], "blockers"))
    _require(blockers == CARRY_FORWARD_BLOCKERS, 109, "carry-forward blockers changed")

    candidate = _mapping(root["candidate"], "candidate")
    _require(candidate == expected["candidate"], 110, "candidate identity or mode drifted")
    _require(candidate["promotion_eligibility_granted"] is False, 111, "promotion was granted")
    _require(candidate["candidate_mode_enabled"] is False, 112, "candidate mode was enabled")

    source = _mapping(root["source_pr_19"], "source_pr_19")
    _require(source == expected["source_pr_19"], 113, "Source PR #19 state drifted")

    production = _mapping(root["production"], "production")
    _require(production == expected["production"], 114, "production authority drifted")

    blocker_evidence = _mapping(root["m23_7_5_blocker_evidence"], "M23.7.5 blockers")
    _require(
        blocker_evidence == expected["m23_7_5_blocker_evidence"],
        115,
        "blocker evidence drifted",
    )
    _require(
        blocker_evidence["latency_budget_passed"] is False,
        116,
        "latency blocker cleared without evidence",
    )
    _require(
        blocker_evidence["retrieval_drift_clear"] is False,
        117,
        "retrieval blocker cleared without evidence",
    )

    decision = root["readiness_decision"]
    _require(decision == READINESS_DECISION, 118, "readiness decision drifted")
    options = _mapping(root["m23_7_8_decision_options"], "decision options")
    _require(
        set(options) == {"promote", "hold", "repair", "reject"},
        119,
        "decision option set drifted",
    )
    promote = _mapping(options["promote"], "promote option")
    _require(
        promote["currently_available"] is False,
        120,
        "promote became available while blockers remain",
    )
    _require(
        tuple(promote["requires_blockers_cleared"]) == CARRY_FORWARD_BLOCKERS,
        121,
        "promote prerequisites drifted",
    )

    protected = _mapping(root["protected_mutations"], "protected mutations")
    _require(set(protected) == set(PROTECTED_MUTATIONS), 122, "protected mutation set drifted")
    _require(
        all(protected[key] is False for key in PROTECTED_MUTATIONS),
        123,
        "protected mutation was dispatched",
    )

    _require(canonical_sha256(root) == PACKET_SHA256, 124, "packet digest drifted")
    return root


def build_readiness_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    packet = validate_readiness_packet(payload)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "milestone": "M23.7.7",
        "status": "pass",
        "readiness_decision": packet["readiness_decision"],
        "packet_sha256": canonical_sha256(packet),
        "m23_7_8_blocked_promote": True,
        "carry_forward_blockers": list(CARRY_FORWARD_BLOCKERS),
        "promotion_eligibility_granted": False,
        "candidate_mode_enabled": False,
        "production_authority": False,
        "protected_mutations_dispatched": False,
    }
    _require(canonical_sha256(report) == REPORT_SHA256, 125, "report digest drifted")
    return report
