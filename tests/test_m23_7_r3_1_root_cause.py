from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

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


FINAL_REPORT = Path("pilot/m23/m23-7-r3-1-root-cause-report.json")


def _final_report() -> dict[str, object]:
    return json.loads(FINAL_REPORT.read_text(encoding="utf-8"))


def test_final_root_cause_report_digest_and_seal() -> None:
    report = _final_report()
    stated = report.pop("report_sha256")
    canonical = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    assert hashlib.sha256(canonical).hexdigest() == stated
    assert stated == "10a5bd0aa1b141cb508db8781269d2d47ed1cf9309a3065671f3356f7e1d5f7c"
    assert report["status"] == "root_cause_sealed"
    assert report["root_cause"] == {
        "primary": "identifier_humanisation_query_collision",
        "compounding": ["corpus_hubness"],
        "final_seal": True,
        "repair_proposal_included": False,
    }


def test_final_report_binds_live_vector_evidence() -> None:
    report = _final_report()
    evidence = report["evidence"]
    assert evidence["compiler_query_digest_count"] == 8
    assert evidence["query_text_digest_count"] == 4
    assert evidence["all_expected_pairs_collide"] is True
    assert evidence["all_receipt_rankings_match_local_cosine"] is True
    assert evidence["query_norm_max_error"] == 0.0
    assert evidence["point_norm_max_error"] < 2e-8
    assert evidence["maximum_top10_hub_frequency"] == 8
    assert evidence["target_ranks"] == [24, 96, 17, 83, 64, 4, 56, 7]


def test_final_hypothesis_dispositions_are_fail_closed() -> None:
    report = _final_report()
    hypotheses = report["hypotheses"]
    assert hypotheses["H1_identifier_humanisation_query_collision"]["disposition"] == (
        "confirmed_primary"
    )
    assert hypotheses["H4_corpus_hubness"]["disposition"] == "confirmed_compounding"
    assert hypotheses["H7_top_k_request_defect"]["disposition"] == "ruled_out"
    assert hypotheses["H8_batch_mapping_defect"]["disposition"] == "ruled_out"
    assert report["authority"]["production_retrieval"] == "lexical"
    assert report["authority"]["promotion_eligibility_granted"] is False
    assert report["authority"]["qdrant_writes"] == 0
    assert report["remaining_blockers"] == ["blocked_pending_retrieval_quality"]
    assert report["exit"]["r3_1_complete"] is True
    assert report["exit"]["parent_r3_complete"] is False
    assert report["exit"]["issue_474_must_remain_open"] is True


def test_final_report_privacy_surface() -> None:
    encoded = FINAL_REPORT.read_text(encoding="utf-8")
    for forbidden in (
        "What does",
        "What is",
        "How does",
        "Which source",
        "QDRANT_API_KEY",
        "CLOUDFLARE_API_TOKEN",
        "https://",
    ):
        assert forbidden not in encoded
