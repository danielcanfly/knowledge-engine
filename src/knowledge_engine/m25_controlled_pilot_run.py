from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

from .errors import AuthorizationError, IntegrityError
from .m25_controlled_pilot_common import (
    FAILURE_DRILLS,
    LIVE_COMPLETE_STATUS,
    M25_8_LIVE_STATUS,
    RECEIPT_SCHEMA,
    RUN_SCHEMA,
    SOURCE_STATES,
    STAGES,
    TEST_COMPLETE_STATUS,
    _hex,
    _nonnegative_int,
    _number,
    _positive_int,
    sign,
    verify_signed,
)
from .m25_controlled_pilot_inventory import validate_authority, validate_inventory


def _validate_predecessor(value: Any, mode: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityError("M25-PILOT-043 predecessor must be an object")
    required_status = (
        M25_8_LIVE_STATUS
        if mode == "live"
        else "m25_8_test_only_adoption_simulation_passed"
    )
    if (
        value.get("status") != required_status
        or value.get("production_pointer_unchanged") is not True
        or value.get("production_release_unchanged") is not True
    ):
        raise AuthorizationError("M25-PILOT-044 M25.8 predecessor is not accepted")
    _hex(value.get("evidence_sha256"), 64, "M25.8 evidence digest")
    _hex(value.get("engine_merge_sha"), 40, "M25.8 Engine merge SHA")
    return dict(value)


def _validate_stages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(STAGES):
        raise IntegrityError("M25-PILOT-045 exact M25.9A stage population required")
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"stage", "status", "checkpoint_sha256"}:
            raise IntegrityError("M25-PILOT-046 malformed stage checkpoint")
        stage = item.get("stage")
        if stage not in STAGES or stage in seen or item.get("status") != "pass":
            raise IntegrityError("M25-PILOT-047 invalid stage checkpoint")
        _hex(item.get("checkpoint_sha256"), 64, "checkpoint digest")
        seen.add(stage)
        clean.append(dict(item))
    if tuple(item["stage"] for item in clean) != STAGES:
        raise IntegrityError("M25-PILOT-048 stage order mismatch")
    return clean


def _validate_population(
    value: Any,
    inventory: Mapping[str, Any],
    max_failed_sources: int,
) -> tuple[list[dict[str, Any]], Counter[str], int]:
    if not isinstance(value, list) or len(value) != inventory["source_count"]:
        raise IntegrityError("M25-PILOT-049 full population record count mismatch")
    expected_ids = [item["source_id"] for item in inventory["sources"]]
    records_by_id: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    total_candidates = 0
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "source_id",
            "terminal_state",
            "candidate_count",
            "source_receipt_sha256",
        }:
            raise IntegrityError("M25-PILOT-050 malformed population record")
        source_id = item.get("source_id")
        if source_id in records_by_id or source_id not in expected_ids:
            raise IntegrityError("M25-PILOT-051 duplicate or unknown source population record")
        state = item.get("terminal_state")
        if state not in SOURCE_STATES:
            raise IntegrityError("M25-PILOT-052 invalid source terminal state")
        candidate_count = _nonnegative_int(item.get("candidate_count"), "candidate_count")
        if state != "candidate_ready" and candidate_count != 0:
            raise IntegrityError("M25-PILOT-053 non-candidate state cannot claim candidates")
        _hex(item.get("source_receipt_sha256"), 64, "source receipt digest")
        counts[state] += 1
        total_candidates += candidate_count
        records_by_id[source_id] = dict(item)
    if list(records_by_id) != expected_ids:
        raise IntegrityError("M25-PILOT-054 population ordering or accounting mismatch")
    if counts["failed_technical"] > max_failed_sources:
        raise IntegrityError("M25-PILOT-055 failed source threshold exceeded")
    return [records_by_id[source_id] for source_id in expected_ids], counts, total_candidates


def _validate_failure_drills(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(FAILURE_DRILLS):
        raise IntegrityError("M25-PILOT-056 exact failure drill population required")
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"drill", "status", "evidence_sha256"}:
            raise IntegrityError("M25-PILOT-057 malformed failure drill")
        drill = item.get("drill")
        if drill not in FAILURE_DRILLS or drill in seen or item.get("status") != "pass":
            raise IntegrityError("M25-PILOT-058 failure drill did not pass")
        _hex(item.get("evidence_sha256"), 64, "failure drill digest")
        seen.add(drill)
        clean.append(dict(item))
    if tuple(item["drill"] for item in clean) != FAILURE_DRILLS:
        raise IntegrityError("M25-PILOT-059 failure drill order mismatch")
    return clean


def _validate_metrics(
    value: Any,
    *,
    source_count: int,
    total_candidates: int,
    max_cost: float,
) -> dict[str, Any]:
    required = {
        "cost_usd",
        "wall_clock_ms",
        "p50_source_latency_ms",
        "p95_source_latency_ms",
        "source_count",
        "candidate_count",
        "reviewer_minutes",
        "security_failures",
        "unaccounted_sources",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise IntegrityError("M25-PILOT-060 malformed metrics")
    cost = _number(value["cost_usd"], "cost_usd")
    if cost > max_cost:
        raise AuthorizationError("M25-PILOT-061 pilot cost ceiling exceeded")
    wall_clock = _positive_int(value["wall_clock_ms"], "wall_clock_ms")
    p50 = _positive_int(value["p50_source_latency_ms"], "p50_source_latency_ms")
    p95 = _positive_int(value["p95_source_latency_ms"], "p95_source_latency_ms")
    if p95 < p50 or p95 > wall_clock:
        raise IntegrityError("M25-PILOT-062 invalid latency ordering")
    if value["source_count"] != source_count or value["candidate_count"] != total_candidates:
        raise IntegrityError("M25-PILOT-063 metric population mismatch")
    _nonnegative_int(value["reviewer_minutes"], "reviewer_minutes")
    if value["security_failures"] != 0 or value["unaccounted_sources"] != 0:
        raise AuthorizationError("M25-PILOT-064 hard safety metric failed")
    return json.loads(json.dumps(value))


def _validate_boundaries(value: Any) -> dict[str, Any]:
    required = {
        "benchmark_fixture_adopted",
        "source_write",
        "source_merge",
        "candidate_deployment",
        "qdrant_mutation",
        "r2_production_mutation",
        "production_release_mutation",
        "production_pointer_mutation",
        "traffic_mutation",
        "credential_mutation",
        "m25_9b_authorized",
        "m25_9c_authorized",
        "m25_10_authorized",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise AuthorizationError("M25-PILOT-065 malformed protected boundaries")
    if any(value[field] is not False for field in required):
        raise AuthorizationError("M25-PILOT-066 protected mutation boundary drift")
    return dict(value)


def build_run_receipt(evidence: Mapping[str, Any]) -> dict[str, Any]:
    if evidence.get("schema_version") != RUN_SCHEMA:
        raise IntegrityError("M25-PILOT-067 unsupported run evidence schema")
    evidence_sha = verify_signed(
        evidence,
        "evidence_sha256",
        "M25-PILOT-068 run evidence digest mismatch",
    )
    mode = evidence.get("mode")
    if mode not in {"live", "test_only"}:
        raise IntegrityError("M25-PILOT-069 invalid run mode")
    predecessor = _validate_predecessor(evidence.get("predecessor"), mode)
    inventory_raw = evidence.get("inventory")
    authority_raw = evidence.get("authority")
    if not isinstance(inventory_raw, dict) or not isinstance(authority_raw, dict):
        raise IntegrityError("M25-PILOT-070 inventory and authority objects required")
    inventory = validate_inventory(inventory_raw)
    if inventory["mode"] != mode:
        raise IntegrityError("M25-PILOT-071 run and inventory mode mismatch")
    authority = validate_authority(authority_raw, inventory)
    execution = evidence.get("execution")
    if not isinstance(execution, dict) or set(execution) != {"run_id", "runner_sha", "stages"}:
        raise IntegrityError("M25-PILOT-072 malformed execution record")
    run_id = execution.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 128:
        raise IntegrityError("M25-PILOT-073 invalid run_id")
    _hex(execution.get("runner_sha"), 40, "runner SHA")
    stages = _validate_stages(execution.get("stages"))
    population, counts, total_candidates = _validate_population(
        evidence.get("population"),
        inventory,
        authority["stop_thresholds"]["max_failed_sources"],
    )
    candidate_population = evidence.get("candidate_population")
    if not isinstance(candidate_population, dict) or set(candidate_population) != {
        "candidate_count",
        "candidate_packet_sha256",
        "candidate_ids_sha256",
    }:
        raise IntegrityError("M25-PILOT-074 malformed candidate population")
    if candidate_population["candidate_count"] != total_candidates:
        raise IntegrityError("M25-PILOT-075 candidate count mismatch")
    _hex(candidate_population["candidate_packet_sha256"], 64, "candidate packet digest")
    _hex(candidate_population["candidate_ids_sha256"], 64, "candidate IDs digest")
    metrics = _validate_metrics(
        evidence.get("metrics"),
        source_count=inventory["source_count"],
        total_candidates=total_candidates,
        max_cost=float(authority["max_cost_usd"]),
    )
    drills = _validate_failure_drills(evidence.get("failure_drills"))
    boundaries = _validate_boundaries(evidence.get("boundary"))
    status = TEST_COMPLETE_STATUS if mode == "test_only" else LIVE_COMPLETE_STATUS
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": status,
        "mode": mode,
        "run_id": run_id,
        "predecessor_status": predecessor["status"],
        "inventory_sha256": inventory["inventory_sha256"],
        "authority_sha256": authority["authority_sha256"],
        "evidence_sha256": evidence_sha,
        "source_count": inventory["source_count"],
        "accounted_source_count": len(population),
        "unaccounted_source_count": 0,
        "terminal_state_counts": dict(sorted(counts.items())),
        "candidate_count": total_candidates,
        "stage_count": len(stages),
        "failure_drill_count": len(drills),
        "full_population_accounted": True,
        "hidden_exclusions": False,
        "hard_safety_gates_passed": True,
        "cost_usd": metrics["cost_usd"],
        "production_mutation": False,
        "source_mutation": False,
        "m25_9b_authorized": boundaries["m25_9b_authorized"],
        "m25_9c_authorized": boundaries["m25_9c_authorized"],
        "m25_10_authorized": boundaries["m25_10_authorized"],
        "next_legal_action": "present_full_population_candidate_packets_for_daniel_decision_gate",
    }
    return sign(receipt, "receipt_sha256")
