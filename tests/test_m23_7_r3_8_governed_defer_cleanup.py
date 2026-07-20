from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256
from scripts.m23_7_r3_8_run_authorization import load_authorization

DECISION_PATH = Path(
    ".github/evidence/m23-7-r3-8-governed-defer/"
    "governed-defer-decision-29712598908-29713148161.json"
)
AUTHORIZATION_PATHS = (
    Path("pilot/m23/r3-8/authorizations/29712598908.json"),
    Path("pilot/m23/r3-8/authorizations/29713148161.json"),
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_self_digest(value: dict, key: str) -> None:
    expected = value[key]
    unsigned = dict(value)
    unsigned.pop(key)
    assert canonical_sha256(unsigned) == expected


def test_governed_defer_records_stop_line_and_authority_boundaries() -> None:
    decision = _load(DECISION_PATH)
    _assert_self_digest(decision, "decision_sha256")

    policy = decision["attempt_policy"]
    assert policy["post_reset_primary_attempt_run_id"] == "29712598908"
    assert policy["bounded_repair_confirmation_run_id"] == "29713148161"
    assert policy["additional_live_attempts_authorized"] is False

    assert decision["primary_attempt"]["failure_stage"] == "worker_readiness"
    assert decision["confirmation_attempt"]["failure_stage"] == "live_observation"
    assert decision["confirmation_attempt"]["failure_code"] == (
        "latency_repair_worker_http_500"
    )
    assert decision["live_blocker"] == {
        "class": "worker_live_observation_http_500",
        "service_available": True,
        "application_ready": True,
        "readiness_not_blocking_after_repair": True,
        "requires_future_harness_reset": True,
    }
    assert decision["product_state"] == {
        "production_retrieval": "lexical",
        "semantic_promotion_enabled": False,
        "semantic_answer_serving_enabled": False,
        "offline_candidate_evidence_retained": True,
        "protected_mutations_dispatched": False,
        "blockers_cleared": False,
    }
    assert decision["authority"] == {
        "m23_7_closure_authorized": False,
        "semantic_live_acceptance_complete": False,
        "production_mutation_authorized": False,
        "qdrant_mutation_authorized": False,
        "r2_mutation_authorized": False,
        "source_mutation_authorized": False,
        "blocker_clearance_authorized": False,
    }


def test_cleanup_recovery_manifests_are_data_bound_and_read_only() -> None:
    for path in AUTHORIZATION_PATHS:
        value = load_authorization(
            path,
            requested_action="recovery_probe",
            actual_head="0" * 40,
        )
        run_id = path.stem
        assert value["affected_run_id"] == run_id
        assert value["worker_name"] == f"knowledge-engine-r3-8-{run_id}"
        assert value["allowed_actions"] == ["recovery_probe"]
        assert value["production_mutation_authorized"] is False
        assert value["qdrant_mutation_authorized"] is False
        assert value["r2_mutation_authorized"] is False
        assert value["source_mutation_authorized"] is False
        assert value["blocker_clearance_authorized"] is False
