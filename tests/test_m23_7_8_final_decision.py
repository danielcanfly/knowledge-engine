from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_8_final_decision import (
    DECISION_PACKET_SHA256,
    REPAIR_HANDOFF_SHA256,
    REPORT_SHA256,
    build_decision_report,
    build_repair_handoff,
    canonical_decision_packet,
    canonical_sha256,
    validate_decision_packet,
)


def test_canonical_decision_report_and_handoff_are_stable() -> None:
    packet = canonical_decision_packet()
    report = build_decision_report(packet)
    handoff = build_repair_handoff(packet)

    assert canonical_sha256(packet) == DECISION_PACKET_SHA256
    assert canonical_sha256(report) == REPORT_SHA256
    assert canonical_sha256(handoff) == REPAIR_HANDOFF_SHA256
    assert report["decision"] == "repair"
    assert report["m23_7_status"] == "complete_with_repair_decision"

    committed_report = json.loads(
        Path("pilot/m23/m23-7-8-final-decision-report.json").read_text()
    )
    committed_handoff = json.loads(
        Path("pilot/m23/m23-7-8-repair-handoff.json").read_text()
    )
    assert committed_report == report
    assert committed_handoff == handoff


def test_promote_decision_is_rejected() -> None:
    packet = canonical_decision_packet()
    packet["decision"] = "promote"

    with pytest.raises(IntegrityError, match="final decision drifted"):
        validate_decision_packet(packet)


def test_promote_cannot_become_available() -> None:
    packet = canonical_decision_packet()
    packet["decision_options"]["promote"]["available"] = True

    with pytest.raises(IntegrityError, match="promote became available"):
        validate_decision_packet(packet)


def test_exactly_repair_must_be_selected() -> None:
    packet = canonical_decision_packet()
    packet["decision_options"]["hold"]["selected"] = True

    with pytest.raises(IntegrityError, match="exactly repair must be selected"):
        validate_decision_packet(packet)


def test_blocker_removal_is_rejected() -> None:
    packet = canonical_decision_packet()
    packet["blocking_evidence"]["carry_forward_blockers"] = [
        "blocked_pending_latency"
    ]

    with pytest.raises(IntegrityError, match="blockers changed"):
        validate_decision_packet(packet)


def test_latency_budget_inflation_is_rejected() -> None:
    packet = canonical_decision_packet()
    packet["blocking_evidence"]["latency"]["canonical_shadow_p95_budget_ms"] = 1800

    with pytest.raises(IntegrityError, match="latency evidence drifted"):
        validate_decision_packet(packet)


def test_retrieval_quality_cannot_be_cleared_without_evidence() -> None:
    packet = canonical_decision_packet()
    packet["blocking_evidence"]["retrieval_quality"]["cleared"] = True

    with pytest.raises(IntegrityError, match="retrieval evidence drifted"):
        validate_decision_packet(packet)


def test_all_three_repair_workstreams_are_required() -> None:
    packet = canonical_decision_packet()
    packet["repair_workstreams"] = packet["repair_workstreams"][:-1]

    with pytest.raises(IntegrityError, match="repair workstreams drifted"):
        validate_decision_packet(packet)


def test_promotion_precondition_cannot_be_removed() -> None:
    packet = canonical_decision_packet()
    packet["future_promotion_preconditions"]["R2_complete"] = False

    with pytest.raises(IntegrityError, match="promotion preconditions drifted"):
        validate_decision_packet(packet)


def test_source_pr_state_is_pinned() -> None:
    packet = canonical_decision_packet()
    packet["source_pr_19"]["draft"] = False

    with pytest.raises(IntegrityError, match="Source PR #19 drifted"):
        validate_decision_packet(packet)


def test_candidate_mode_cannot_be_enabled() -> None:
    packet = canonical_decision_packet()
    packet["production"]["candidate_mode_enabled"] = True

    with pytest.raises(IntegrityError, match="production authority drifted"):
        validate_decision_packet(packet)


def test_protected_mutation_is_rejected() -> None:
    packet = canonical_decision_packet()
    packet["protected_mutations"]["production_pointer"] = True

    with pytest.raises(IntegrityError, match="protected mutation dispatched"):
        validate_decision_packet(packet)


def test_evidence_chain_drift_is_rejected() -> None:
    packet = canonical_decision_packet()
    packet["evidence_chain"] = packet["evidence_chain"][:-1]

    with pytest.raises(IntegrityError, match="evidence chain drifted"):
        validate_decision_packet(packet)


def test_packet_mutation_changes_digest() -> None:
    packet = canonical_decision_packet()
    changed = copy.deepcopy(packet)
    changed["phase_closure"]["m23_7_status"] = "promoted"

    assert canonical_sha256(packet) == DECISION_PACKET_SHA256
    assert canonical_sha256(changed) != DECISION_PACKET_SHA256
    with pytest.raises(IntegrityError, match="packet digest drifted"):
        validate_decision_packet(changed)
