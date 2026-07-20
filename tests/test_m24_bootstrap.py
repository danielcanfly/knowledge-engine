from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

ROADMAP_PATH = Path("pilot/m24/m24-bootstrap-roadmap.json")


def _load_roadmap() -> dict:
    return json.loads(ROADMAP_PATH.read_text(encoding="utf-8"))


def test_m24_bootstrap_roadmap_is_digest_bound() -> None:
    roadmap = _load_roadmap()
    unsigned = dict(roadmap)
    digest = unsigned.pop("roadmap_sha256")

    assert digest != "TO_BE_FILLED"
    assert canonical_sha256(unsigned) == digest


def test_m24_starts_from_m23_7_live_acceptance_without_promotion() -> None:
    roadmap = _load_roadmap()

    assert roadmap["milestone"] == "M24"
    assert roadmap["status"] == "bootstrap_open"
    assert roadmap["source_closure"] == {
        "milestone": "M23.7 R3.8",
        "closure_pr": 963,
        "parent_issue": 474,
        "semantic_live_acceptance_complete": True,
        "engine_sha": "2a24ed38f4d9c5e370417453860314cd60c14ef9",
        "observation_run_id": "29715599032",
        "artifact_id": "8450463481",
        "artifact_zip_sha256": (
            "7f025b28fad8f6574748f58f0de9042cf15c7b93a8fa8070c105a0ba0419311c"
        ),
        "evidence_seal_sha256": (
            "94dad021d947422933fab588b6f0396c249d73516ae27f3533329480edc7e2eb"
        ),
        "reconciliation_sha256": (
            "cb6b7d1b7213da018dd8466c9c43538d616f24f65ece25ef1c28ec1ac4e3094a"
        ),
    }
    assert roadmap["production_state"] == {
        "retrieval": "lexical",
        "semantic_promotion_enabled": False,
        "semantic_answer_serving_enabled": False,
        "hybrid_retrieval_enabled": False,
        "protected_mutations_dispatched": False,
    }


def test_semantic_promotion_decision_is_first_gated_lane() -> None:
    roadmap = _load_roadmap()
    gate = roadmap["gated_lanes"][0]

    assert gate["id"] == "semantic_promotion_decision"
    assert gate["order"] == 1
    assert gate["may_start_now"] is True
    assert gate["gated"] is True
    assert gate["authorizes_on_bootstrap"] == []
    assert gate["required_before"] == [
        "production_retrieval_change",
        "production_hybrid_retrieval",
        "semantic_answer_serving",
        "semantic_promotion",
    ]
    assert set(gate["must_define"]) == {
        "authority_boundary",
        "rollout_plan",
        "rollback_plan",
        "serving_contract",
        "production_metrics",
        "failure_triggers",
        "operator_or_pr_authorization",
    }


def test_parallel_product_lanes_are_not_frozen_by_promotion_gate() -> None:
    roadmap = _load_roadmap()
    lanes = {lane["id"]: lane for lane in roadmap["parallel_product_lanes"]}

    assert set(lanes) == {
        "source_pr_19_review",
        "canonical_source_adoption_plan",
        "sigma_internal_deployment",
        "obsidian_exporter",
        "concept_wiki",
        "lexical_search_ux",
        "provenance_source_viewer",
        "graph_navigation",
    }
    for lane in lanes.values():
        assert lane["may_start_now"] is True
        assert lane["blocked_by_semantic_promotion"] is False
        assert lane["production_serving_authority"] is False


def test_bootstrap_blocks_production_semantic_serving_until_decision() -> None:
    roadmap = _load_roadmap()

    assert roadmap["blocked_until_promotion_decision"] == [
        "production_retrieval_change",
        "production_hybrid_retrieval",
        "semantic_answer_serving",
        "semantic_promotion",
    ]
    assert roadmap["bootstrap_authority"] == {
        "promotion_authorized": False,
        "serving_authorized": False,
        "production_mutation_authorized": False,
        "qdrant_mutation_authorized": False,
        "r2_mutation_authorized": False,
        "source_mutation_authorized": False,
        "pointer_mutation_authorized": False,
        "credential_rotation_authorized": False,
    }
    assert roadmap["next_actions"] == [
        "open_semantic_promotion_decision_issue",
        "open_parallel_product_lane_issues",
        "keep_production_retrieval_lexical_until_explicit_promotion",
        "start_non_serving_product_work_without_waiting_for_promotion",
    ]
