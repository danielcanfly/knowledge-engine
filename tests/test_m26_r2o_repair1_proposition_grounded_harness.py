from __future__ import annotations

import hashlib
import json
from collections import Counter

from knowledge_engine.m26_r2o_repair1_proposition_grounded_harness import (
    BANK_DIR,
    HOSTILE_SEMANTIC_REVIEW_REQUIRED,
    audit_captured_result,
    canonical_bank_sha,
    live_matrix_summary,
    load_bank,
    pool_id_sha,
    select_holdout_live_matrix,
    select_primary_live_matrix,
    validate_bank,
    validate_case_structure,
)

RUNTIME_SHA = "8942859bbe3491de084dda09326fe03fec82989f"


def _rows(name: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (BANK_DIR / name).read_text().splitlines()
        if line
    ]


def test_bank_structure_counts_and_disjointness() -> None:
    rows = load_bank()
    primary = [row for row in rows if row["pool"] == "primary"]
    holdout = [row for row in rows if row["pool"] == "holdout"]
    sentinels = [row for row in rows if row["pool"] == "sentinel"]

    assert len(primary) == 72
    assert len(holdout) == 41
    assert len(sentinels) == 7
    assert len(rows) == 120

    families = Counter(row["family"] for row in rows)
    assert len(families) == 32
    assert all(count >= 2 for count in Counter(row["family"] for row in primary).values())
    assert all(count >= 1 for count in Counter(row["family"] for row in holdout).values())

    prim_pairs = {
        (support["source_identity"], support["section_id"])
        for row in primary
        for support in row["gold_support"]
    }
    hold_pairs = {
        (support["source_identity"], support["section_id"])
        for row in holdout
        for support in row["gold_support"]
    }
    assert prim_pairs.isdisjoint(hold_pairs)

    placeholder_hits = [
        row["case_id"]
        for row in rows
        if "stay within the proposition supported by the exact snippet"
        in json.dumps(row["required_propositions"], sort_keys=True).lower()
    ]
    assert placeholder_hits == []
    assert validate_bank(BANK_DIR) == []


def test_support_refs_and_gold_supports_are_structured() -> None:
    rows = load_bank()
    for row in rows:
        gold_ids = {support["support_id"] for support in row["gold_support"]}
        assert len(gold_ids) == len(row["gold_support"])
        for support in row["gold_support"]:
            assert support["exact_support_snippet"].strip()
            assert support["source_identity"].strip()
            assert support["section_id"].strip()
            assert "authority_for" in support
        for proposition in row["required_propositions"]:
            assert set(proposition["support_refs"]) <= gold_ids
            assert proposition["proposition_text"].strip()
            assert proposition["entailment_note"].strip()
            assert proposition["relation_type"].strip()
            assert proposition["gold_mode"] in {
                "extractive",
                "structural",
                "sentinel_synthesis",
                "context_only",
            }
        for forbidden in row["forbidden_inferences"]:
            assert forbidden["inference_id"].strip()
            assert forbidden["forbidden_text_or_relation"].strip()
            assert forbidden["reason"].strip()
            assert forbidden["forbidden_text_or_relation"].strip() != row["question"].strip()
        if row["expected_behavior"] == "abstain":
            assert row["required_propositions"][0]["relation_type"] == "context_only"
        if row["graph_edge_required"]:
            assert row["graph_certificate"]["graph_edge_id"].strip()
            assert row["graph_certificate"]["primary_concept_id"].strip()
        if row["provenance_required"]:
            assert row["provenance_certificate"]["provenance_record_id"].strip()
            assert row["provenance_certificate"]["provenance_subject_concept_id"].strip()
            assert "subject_match" in row["provenance_certificate"]
        if row["family"] == "temporal_version":
            assert row["temporal_certificate"]["temporal_evidence_mode"] == "insufficient"
            assert row["temporal_certificate"]["observed_temporal_record_count"] == 1
            assert row["temporal_versions_required"] == 0


def test_certificate_subjects_and_edges_are_claim_local() -> None:
    rows = load_bank()
    for row in rows:
        primary = next(s for s in row["gold_support"] if s["support_role"] == "primary")
        primary_concept = primary["section_id"].split("#", 1)[0]
        if row["provenance_required"]:
            certificate = row["provenance_certificate"]
            assert certificate["primary_concept_id"] == primary_concept
            assert certificate["subject_match"] is True
        if row["graph_edge_required"]:
            certificate = row["graph_certificate"]
            assert certificate["primary_concept_id"] == primary_concept
            assert certificate["graph_edge_id"].startswith("edge_")
        if row["family"] == "temporal_version":
            certificate = row["temporal_certificate"]
            assert certificate["primary_concept_id"] == primary_concept
            assert certificate["minimum_required_for_positive"] == 2


def test_bank_sha_and_diversity_metrics_are_stable() -> None:
    rows = load_bank()
    sha_doc = (BANK_DIR / "BANK_SHA256.md").read_text()
    manifest = json.loads((BANK_DIR / "broad_bank_manifest.json").read_text())
    summary = json.loads((BANK_DIR / "bank_summary.json").read_text())

    bank_sha = canonical_bank_sha(BANK_DIR)
    assert f"bank_sha256={bank_sha}" in sha_doc
    assert manifest["bank_sha256"] == bank_sha
    assert summary["TOTAL_CASES"] == 120
    assert summary["PRIMARY_CASES"] == 72
    assert summary["HOLDOUT_CASES"] == 41
    assert summary["SENTINELS"] == 7
    assert summary["UNIQUE_SOURCE_IDENTITIES"] >= 20
    assert summary["UNIQUE_SOURCE_FILES"] >= 20
    assert summary["SOURCE_FAMILY_COUNT"] >= 8
    assert pool_id_sha(rows, "primary") == manifest["primary_ids_sha256"]
    assert pool_id_sha(rows, "holdout") == manifest["holdout_ids_sha256"]
    assert pool_id_sha(rows, "sentinel") == manifest["sentinel_ids_sha256"]


def test_known_sentinels_are_exact_and_repeated_as_required() -> None:
    sentinels = _rows("broad_bank.sentinels.jsonl")
    questions = Counter(row["question"] for row in sentinels)
    case_ids = {row["case_id"] for row in sentinels}

    assert questions == Counter(
        {
            "What kind of skill does a Product Manager need?": 3,
            "What is a skill in an AI agent architecture?": 3,
            "What is the role of user research in product management?": 1,
        }
    )
    assert case_ids == {
        "SENTINEL-Q1-A",
        "SENTINEL-Q1-B",
        "SENTINEL-Q1-C",
        "SENTINEL-Q2-A",
        "SENTINEL-Q2-B",
        "SENTINEL-Q2-C",
        "SENTINEL-Q3-CONTROL",
    }
    q2 = next(row for row in sentinels if row["case_id"] == "SENTINEL-Q2-A")
    assert q2["required_propositions"][0]["gold_mode"] == "sentinel_synthesis"
    assert (
        "Skill | What method should the agent follow for this class of task?"
        in q2["required_propositions"][0]["proposition_text"]
    )
    assert q2["required_propositions"][0]["support_refs"] == ["SENTINEL-Q2-A-SUP01"]
    assert all(
        "atlas-of-agent" not in ref.lower()
        for prop in q2["required_propositions"]
        for ref in prop["support_refs"]
    )
    q1 = next(row for row in sentinels if row["case_id"] == "SENTINEL-Q1-A")
    assert (
        q1["gold_support"][0]["source_identity"]
        == "daniel_blog_en__pm-product-data-and-experimentation-07"
    )
    q1_required_refs = {
        ref for prop in q1["required_propositions"] for ref in prop["support_refs"]
    }
    q1_required_sources = {
        support["source_identity"]
        for support in q1["gold_support"]
        if support["support_id"] in q1_required_refs
    }
    assert all("pm-" in source for source in q1_required_sources)
    assert all("atlas-of-agent" not in source for source in q1_required_sources)
    assert any(
        support["support_role"] == "negative_distractor"
        for support in q1["gold_support"]
    )
    q3 = next(row for row in sentinels if row["case_id"] == "SENTINEL-Q3-CONTROL")
    assert q3["required_propositions"][0]["support_refs"] == ["SENTINEL-Q3-CONTROL-SUP01"]


def test_known_broad_defects_are_extractively_grounded() -> None:
    rows = load_bank()
    h043 = next(row for row in rows if row["case_id"] == "R2O-PG-H043")
    h043_text = h043["required_propositions"][0]["proposition_text"]
    assert "expected outputs" in h043_text
    assert "delegation, outputs" not in h043_text
    assert h043_text in h043["gold_support"][0]["exact_support_snippet"]

    h036 = next(row for row in rows if row["case_id"] == "R2O-PG-H036")
    h036_text = h036["required_propositions"][0]["proposition_text"]
    assert "1. keep deterministic work in fixed logic" in h036_text
    assert h036_text in h036["gold_support"][0]["exact_support_snippet"]

    h032 = next(row for row in rows if row["case_id"] == "R2O-PG-H032")
    h032_text = h032["required_propositions"][0]["proposition_text"]
    assert "durable evidence rather than a model claim" in h032_text
    assert h032_text in h032["gold_support"][0]["exact_support_snippet"]

    p062 = next(row for row in rows if row["case_id"] == "R2O-PG-P062")
    p062_text = p062["required_propositions"][0]["proposition_text"]
    assert p062["required_propositions"][0]["gold_mode"] == "structural"
    assert "concepts/agent-execution-paths" in p062_text
    assert "agent-planning-strategies provenance record" not in p062_text


def test_harness_rejects_corrupted_authority_and_structural_fixtures() -> None:
    q1 = next(row for row in load_bank() if row["case_id"] == "SENTINEL-Q1-A")
    corrupt_q1 = json.loads(json.dumps(q1))
    corrupt_q1["required_propositions"][0]["support_refs"].append("SENTINEL-Q1-A-SUP04")
    corrupt_q1["gold_support"][3]["authority_for"] = [
        corrupt_q1["required_propositions"][0]["proposition_id"]
    ]
    errors = validate_case_structure(corrupt_q1)
    assert "NEGATIVE_DISTRACTOR_USED_AS_AUTHORITY" in errors
    assert "SENTINEL_UNRELATED_AUTHORITY" in errors

    q2 = next(row for row in load_bank() if row["case_id"] == "SENTINEL-Q2-A")
    corrupt_q2 = json.loads(json.dumps(q2))
    corrupt_q2["required_propositions"][0]["support_refs"].append("SENTINEL-Q2-A-SUP02")
    corrupt_q2["gold_support"][1]["authority_for"] = [
        corrupt_q2["required_propositions"][0]["proposition_id"]
    ]
    assert "CONTEXT_SUPPORT_USED_AS_REQUIRED_AUTHORITY" in validate_case_structure(corrupt_q2)

    h043 = next(row for row in load_bank() if row["case_id"] == "R2O-PG-H043")
    corrupt_h043 = json.loads(json.dumps(h043))
    corrupt_h043["required_propositions"][0]["proposition_text"] = (
        "Plan-and-Execute creates a global task structure before carrying out individual "
        "steps and exposes requirements, ordering, dependencies, delegation, outputs, "
        "and completion state."
    )
    assert "EXTRACTIVE_PROP_NOT_IN_SUPPORT" in validate_case_structure(corrupt_h043)

    p062 = next(row for row in load_bank() if row["case_id"] == "R2O-PG-P062")
    corrupt_p062 = json.loads(json.dumps(p062))
    corrupt_p062["required_propositions"][0]["proposition_text"] = (
        "concepts/agent-planning-strategies is bound to provenance record "
        f"{corrupt_p062['provenance_certificate']['provenance_record_id']} whose subject is "
        "concepts/agent-planning-strategies."
    )
    errors = validate_case_structure(corrupt_p062)
    assert "PROVENANCE_PROP_CERT_MISMATCH" in errors
    assert "STRUCTURAL_PROP_CERT_MISMATCH" in errors


def test_matrix_freeze_is_deterministic_and_runtime_sha_bound() -> None:
    rows = load_bank()
    bank_sha = canonical_bank_sha(BANK_DIR)
    primary_matrix = select_primary_live_matrix(
        bank_records=rows,
        runtime_candidate_sha=RUNTIME_SHA,
        bank_sha=bank_sha,
    )
    holdout_matrix = select_holdout_live_matrix(
        bank_records=rows,
        runtime_candidate_sha=RUNTIME_SHA,
        bank_sha=bank_sha,
    )
    frozen_primary = _rows("LIVE_MATRIX.jsonl")
    frozen_holdout = _rows("HOLDOUT_LIVE_MATRIX.jsonl")

    assert primary_matrix == frozen_primary
    assert holdout_matrix == frozen_holdout
    assert live_matrix_summary(primary_matrix) == json.loads(
        (BANK_DIR / "LIVE_MATRIX_SUMMARY.json").read_text()
    )
    assert len(primary_matrix) == 55
    assert len(holdout_matrix) == 24
    assert sum(1 for row in primary_matrix if row["pool"] == "sentinel") == 7
    assert sum(1 for row in primary_matrix if row["pool"] == "primary") == 48
    assert (
        sum(
            1
            for row in primary_matrix
            if row["expected_behavior"] in {"abstain", "partial", "clarify-compatible"}
        )
        >= 18
    )
    assert (
        sum(
            1
            for row in holdout_matrix
            if row["expected_behavior"] in {"abstain", "partial", "clarify-compatible"}
        )
        >= 8
    )
    seed = hashlib.sha256(f"{RUNTIME_SHA}:{bank_sha}".encode()).hexdigest()
    assert all(
        row["runtime_candidate_sha"] == RUNTIME_SHA
        for row in [*primary_matrix, *holdout_matrix]
    )
    assert all(row["selection_seed"] == seed for row in [*primary_matrix, *holdout_matrix])


def test_audit_harness_passes_answer_partial_abstain_and_clarify() -> None:
    rows = load_bank()

    answer_case = next(
        row for row in rows if row["expected_behavior"] == "answer" and row["pool"] == "primary"
    )
    answer_support = answer_case["gold_support"][0]
    answer_result = {
        "terminal_status": answer_case["expected_terminal_set"][0],
        "answer_text": answer_support["exact_support_snippet"],
        "citations": [
            {
                "source_identity": answer_support["source_identity"],
                "support_id": answer_support["support_id"],
                "exact_quote": answer_support["exact_support_snippet"],
            }
        ],
        "unsupported_accepted_claims": 0,
    }
    answer_report = audit_captured_result(answer_case, answer_result)
    assert answer_report["verdict"] == "PASS"
    assert answer_report["required_proposition_coverage"] == HOSTILE_SEMANTIC_REVIEW_REQUIRED

    partial_case = next(row for row in rows if row["expected_behavior"] == "partial")
    partial_support = partial_case["gold_support"][0]
    partial_result = {
        "terminal_status": partial_case["expected_terminal_set"][0],
        "answer_text": partial_support["exact_support_snippet"],
        "citations": [
            {
                "source_identity": partial_support["source_identity"],
                "support_id": partial_support["support_id"],
                "exact_quote": partial_support["exact_support_snippet"],
            }
        ],
        "unsupported_accepted_claims": 0,
        "unanswered_dimensions": list(partial_case["unanswered_dimensions_expected"]),
    }
    partial_report = audit_captured_result(partial_case, partial_result)
    assert partial_report["verdict"] == "PASS"
    assert partial_report["partial_unanswered_dimension_check"] is True

    abstain_case = next(row for row in rows if row["expected_behavior"] == "abstain")
    abstain_result = {
        "terminal_status": abstain_case["expected_terminal_set"][0],
        "answer_text": "",
        "citations": [],
        "unsupported_accepted_claims": 0,
    }
    abstain_report = audit_captured_result(abstain_case, abstain_result)
    assert abstain_report["verdict"] == "PASS"
    assert abstain_report["required_proposition_coverage"] == "DETERMINISTICALLY_AUDITED"

    clarify_case = next(row for row in rows if row["expected_behavior"] == "clarify-compatible")
    clarify_support = clarify_case["gold_support"][0]
    clarify_result = {
        "terminal_status": "clarify",
        "answer_text": clarify_support["exact_support_snippet"],
        "citations": [
            {
                "source_identity": clarify_support["source_identity"],
                "support_id": clarify_support["support_id"],
                "exact_quote": clarify_support["exact_support_snippet"],
            }
        ],
        "unsupported_accepted_claims": 0,
        "unanswered_dimensions": list(clarify_case["unanswered_dimensions_expected"]),
    }
    clarify_report = audit_captured_result(clarify_case, clarify_result)
    assert clarify_report["verdict"] == "PASS"
    assert clarify_report["required_proposition_coverage"] == HOSTILE_SEMANTIC_REVIEW_REQUIRED
