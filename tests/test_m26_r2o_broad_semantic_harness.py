from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.m26_r2o_broad_semantic_harness import (
    HOSTILE_SEMANTIC_REVIEW_REQUIRED,
    REQUIRED_LIVE_FAMILIES,
    audit_captured_result,
    canonical_bank_sha,
    live_matrix_summary,
    load_bank,
    pool_id_sha,
    select_frozen_live_matrix,
)

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "evals" / "m26_broad_semantic"
FROZEN_MATRIX = BANK / "LIVE_MATRIX.jsonl"


def test_r2o_bank_sha_and_pool_id_hashes_are_stable() -> None:
    records = load_bank(BANK)
    sha_doc = (BANK / "BANK_SHA256.md").read_text()

    assert f"bank_sha256={canonical_bank_sha(BANK)}" in sha_doc
    assert f"primary_ids_sha256={pool_id_sha(records, 'primary')}" in sha_doc
    assert f"holdout_ids_sha256={pool_id_sha(records, 'holdout')}" in sha_doc
    assert f"sentinel_ids_sha256={pool_id_sha(records, 'sentinel')}" in sha_doc


def test_r2o_live_matrix_selection_is_deterministic_and_stratified() -> None:
    records = load_bank(BANK)
    frozen = [
        json.loads(line)
        for line in FROZEN_MATRIX.read_text().splitlines()
        if line
    ]
    candidate_head = frozen[0]["candidate_head"]
    bank_sha = canonical_bank_sha(BANK)
    regenerated = select_frozen_live_matrix(
        bank_records=records,
        candidate_head=candidate_head,
        bank_sha=bank_sha,
    )
    summary = live_matrix_summary(frozen)

    assert frozen == regenerated
    assert summary["total"] == 55
    assert summary["sentinels"] == 7
    assert summary["broad_primary"] == 48
    assert summary["control_count"] >= 12
    assert set(summary["families"]) >= REQUIRED_LIVE_FAMILIES


def test_r2o_audit_harness_reports_structural_result_without_nli_scoring() -> None:
    case = next(record for record in load_bank(BANK) if record["expected_behavior"] == "answer")
    support = case["gold_support"][0]
    result = {
        "terminal_status": case["expected_terminal_set"][0],
        "answer_text": support["exact_support_snippet"],
        "material_claims": [
            {
                "claim_id": "claim_1",
                "support_refs": [
                    {
                        "exact_quote": support["exact_support_snippet"],
                        "source_identity": support["source_identity"],
                    }
                ],
            }
        ],
        "citations": [
            {
                "source_identity": support["source_identity"],
                "exact_quote": support["exact_support_snippet"],
            }
        ],
        "unsupported_accepted_claims": 0,
    }

    report = audit_captured_result(case, result)

    assert report["verdict"] == "PASS"
    assert report["required_proposition_coverage"] == HOSTILE_SEMANTIC_REVIEW_REQUIRED
    assert report["forbidden_inference_violations"] == []


def test_r2o_audit_harness_fails_missing_partial_unanswered_dimension() -> None:
    case = next(record for record in load_bank(BANK) if record["expected_behavior"] == "partial")
    support = case["gold_support"][0]
    result = {
        "terminal_status": case["expected_terminal_set"][0],
        "answer_text": support["exact_support_snippet"],
        "citations": [{"source_identity": support["source_identity"]}],
        "unsupported_accepted_claims": 0,
        "unanswered_dimensions": [],
    }

    report = audit_captured_result(case, result)

    assert report["verdict"] == "FAIL"
    assert report["partial_unanswered_dimension_check"] is False
