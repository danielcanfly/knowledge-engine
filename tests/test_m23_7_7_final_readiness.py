from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_7_final_readiness import (
    PACKET_SHA256,
    REPORT_SHA256,
    build_readiness_report,
    canonical_readiness_packet,
    canonical_sha256,
    validate_readiness_packet,
)


def test_canonical_readiness_packet_and_committed_report_are_stable() -> None:
    packet = canonical_readiness_packet()
    report = build_readiness_report(packet)

    assert canonical_sha256(packet) == PACKET_SHA256
    assert canonical_sha256(report) == REPORT_SHA256
    assert report["readiness_decision"] == "hold_for_m23_7_8"
    assert report["m23_7_8_blocked_promote"] is True
    assert report["carry_forward_blockers"] == [
        "blocked_pending_latency",
        "blocked_pending_retrieval_quality",
    ]

    committed = json.loads(
        Path("pilot/m23/m23-7-7-final-readiness-report.json").read_text()
    )
    assert committed == report


def test_promote_cannot_be_available_while_blockers_remain() -> None:
    packet = canonical_readiness_packet()
    packet["m23_7_8_decision_options"]["promote"]["currently_available"] = True

    with pytest.raises(IntegrityError, match="promote became available"):
        validate_readiness_packet(packet)


def test_blockers_cannot_be_removed_or_reordered() -> None:
    packet = canonical_readiness_packet()
    packet["carry_forward_blockers"] = ["blocked_pending_latency"]

    with pytest.raises(IntegrityError, match="carry-forward blockers changed"):
        validate_readiness_packet(packet)


def test_candidate_mode_cannot_be_enabled() -> None:
    packet = canonical_readiness_packet()
    packet["candidate"]["candidate_mode_enabled"] = True

    with pytest.raises(IntegrityError, match="candidate identity or mode drifted"):
        validate_readiness_packet(packet)


def test_promotion_eligibility_cannot_be_granted() -> None:
    packet = canonical_readiness_packet()
    packet["candidate"]["promotion_eligibility_granted"] = True

    with pytest.raises(IntegrityError, match="candidate identity or mode drifted"):
        validate_readiness_packet(packet)


def test_source_pr_state_is_pinned() -> None:
    packet = canonical_readiness_packet()
    packet["source_pr_19"]["draft"] = False

    with pytest.raises(IntegrityError, match="Source PR #19 state drifted"):
        validate_readiness_packet(packet)


def test_m23_7_6_reliability_pass_does_not_clear_m23_7_5_blockers() -> None:
    packet = canonical_readiness_packet()
    packet["m23_7_5_blocker_evidence"]["latency_budget_passed"] = True

    with pytest.raises(IntegrityError, match="blocker evidence drifted"):
        validate_readiness_packet(packet)


def test_protected_mutation_is_rejected() -> None:
    packet = canonical_readiness_packet()
    packet["protected_mutations"]["production_pointer"] = True

    with pytest.raises(IntegrityError, match="protected mutation was dispatched"):
        validate_readiness_packet(packet)


def test_milestone_identity_cannot_be_missing() -> None:
    packet = canonical_readiness_packet()
    packet["m23_7_chain"] = packet["m23_7_chain"][:-1]

    with pytest.raises(IntegrityError, match="M23.7 evidence chain drifted"):
        validate_readiness_packet(packet)


def test_packet_mutation_changes_digest() -> None:
    packet = canonical_readiness_packet()
    changed = copy.deepcopy(packet)
    changed["readiness_decision"] = "promote"

    assert canonical_sha256(packet) == PACKET_SHA256
    assert canonical_sha256(changed) != PACKET_SHA256
    with pytest.raises(IntegrityError, match="readiness decision drifted"):
        validate_readiness_packet(changed)
