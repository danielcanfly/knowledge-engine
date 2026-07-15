from __future__ import annotations

import copy
import json

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_r3_1_fixture import canonical_fixture
from knowledge_engine.m23_7_r3_1_root_cause import (
    analyse_redacted_rankings,
    build_preliminary_report,
    reconstruct_query_identities,
)


def test_four_exact_query_text_collision_pairs_are_visible() -> None:
    fixture = canonical_fixture()
    records, collisions = reconstruct_query_identities(fixture["samples"])
    assert len(collisions) == 4
    assert sorted(item["size"] for item in collisions) == [2, 2, 2, 2]
    assert len({item["compiler_query_digest"] for item in records}) == 8
    assert len({item["query_text_sha256"] for item in records}) == 4
    assert all("query_text" not in item for item in records)


def test_redacted_rankings_collapse_by_query_class() -> None:
    evidence = analyse_redacted_rankings(canonical_fixture()["cases"])
    assert evidence["all_same_class_top3_equal"] is True
    assert evidence["maximum_hub_frequency"] == 6


def test_preliminary_report_is_fail_closed_and_non_authoritative() -> None:
    fixture = canonical_fixture()
    report = build_preliminary_report(fixture["samples"], fixture["cases"])
    assert report["status"] == "phase_a_b_complete_vector_diagnostics_pending"
    assert report["root_cause"]["primary"] == "identifier_humanisation_query_collision"
    assert report["root_cause"]["final_seal"] is False
    assert report["query_identity"]["probe_bound_digest_masks_text_collision"] is True
    assert report["exit"]["r3_1_complete"] is False
    assert report["authority"]["production_retrieval"] == "lexical"
    assert report["authority"]["qdrant_write"] == 0
    assert report["remaining_blockers"] == ["blocked_pending_retrieval_quality"]


def test_report_does_not_persist_raw_queries() -> None:
    fixture = canonical_fixture()
    report = build_preliminary_report(fixture["samples"], fixture["cases"])
    encoded = json.dumps(report, sort_keys=True)
    for forbidden in ("What does", "What is", "How does", "Which source", "https://"):
        assert forbidden not in encoded


def test_duplicate_probe_case_fails_closed() -> None:
    cases = copy.deepcopy(canonical_fixture()["cases"])
    cases[1]["probe_id"] = cases[0]["probe_id"]
    with pytest.raises(IntegrityError, match="duplicate probe id"):
        analyse_redacted_rankings(cases)


def test_report_is_deterministic() -> None:
    fixture = canonical_fixture()
    first = build_preliminary_report(fixture["samples"], fixture["cases"])
    second = build_preliminary_report(fixture["samples"], fixture["cases"])
    assert first == second
    assert len(first["report_sha256"]) == 64
