from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m25_identity_benchmark import (
    CLASS_LABELS,
    SPLITS,
    build_adjudication_ledger,
    build_provisional_suite,
    build_split_manifest,
    digest,
    run_benchmark,
    validate_suite,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "pilot" / "m25" / "m25-4-annotation-policy.json"
SUITE = ROOT / "pilot" / "m25" / "m25-4-gold-suite.provisional.json"
SPLIT = ROOT / "pilot" / "m25" / "m25-4-split-manifest.json"
LEDGER = ROOT / "pilot" / "m25" / "m25-4-adjudication-ledger.json"
REPORT = ROOT / "pilot" / "m25" / "m25-4-baseline-report.provisional.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_provisional_suite_is_deterministic_evidence_bound_and_uniform() -> None:
    policy = load(POLICY)
    committed = load(SUITE)
    first = build_provisional_suite(digest(policy))
    second = build_provisional_suite(digest(copy.deepcopy(policy)))
    assert first == second == committed
    validated = validate_suite(committed, require_approval=False)
    assert validated["item_count"] == 30
    assert validated["approval_status"] == "pending_daniel"
    assert {item["class_label"] for item in validated["items"]} == set(CLASS_LABELS)
    assert {item["split"] for item in validated["items"]} == set(SPLITS)
    assert all(item["evidence"]["evidence_bound"] is True for item in validated["items"])
    assert all(item["candidate_only"] is True for item in validated["items"])
    assert all(item["canonical_knowledge"] is False for item in validated["items"])


def test_split_manifest_is_frozen_and_leakage_free() -> None:
    suite = load(SUITE)
    manifest = build_split_manifest(suite)
    assert manifest == load(SPLIT)
    assert manifest["final_split_calibration_permitted"] is False
    families = [item["semantic_family_id"] for item in manifest["assignments"]]
    assert len(families) == len(set(families)) == 30
    pairs = {(item["class_label"], item["split"]) for item in manifest["assignments"]}
    assert pairs == {(label, split) for label in CLASS_LABELS for split in SPLITS}


def test_adjudication_ledger_requires_exact_daniel_authority() -> None:
    suite = load(SUITE)
    ledger = build_adjudication_ledger(suite)
    assert ledger == load(LEDGER)
    assert ledger["policy_status"] == "pending_daniel"
    assert ledger["label_decision_status"] == "pending_daniel"
    assert ledger["disputed_item_count"] == 0
    assert ledger["decision_required"] == {
        "approve_annotation_policy": True,
        "approve_all_provisional_labels": True,
        "decide_disputed_labels": False,
    }
    assert ledger["silent_label_changes_permitted"] is False


def test_baseline_is_byte_deterministic_and_does_not_calibrate_resolver() -> None:
    suite = load(SUITE)
    first = run_benchmark(suite)
    second = run_benchmark(copy.deepcopy(suite))
    assert first == second == load(REPORT)
    assert first["resolver_threshold_or_code_changed"] is False
    assert first["final_split_used_for_calibration"] is False
    assert first["baseline_status"] == "provisional_pending_daniel"
    assert first["m25_5_authorized"] is False
    assert first["metrics"]["semantic_decision_accuracy"] == 1.0
    assert first["metrics"]["false_merge_count"] == 0
    assert first["metrics"]["explanation_signal_coverage"] == 0.6
    assert first["error_taxonomy"]["explanation_signal_gap"] == 12


def test_baseline_exposes_expected_explanation_gaps_by_class() -> None:
    report = load(REPORT)
    gaps = {
        item["class_label"]
        for item in report["results"]
        if "explanation_signal_gap" in item["error_codes"]
    }
    assert gaps == {
        "near_match_distinct",
        "parent_child_distinct",
        "polysemy_ambiguous",
        "supersession_without_identity_collapse",
    }
    assert all(item["semantic_pass"] is True for item in report["results"])
    assert all(item["no_false_merge"] is True for item in report["results"])


def test_final_split_is_reported_but_never_used_for_calibration() -> None:
    report = load(REPORT)
    assert report["denominators"]["by_split"] == {
        "calibration": 10,
        "final": 10,
        "train": 10,
    }
    assert report["metrics"]["per_split_semantic_accuracy"] == {
        "calibration": 1.0,
        "final": 1.0,
        "train": 1.0,
    }
    assert report["final_split_used_for_calibration"] is False


def test_tampering_and_leakage_fail_closed() -> None:
    suite = load(SUITE)
    tampered = copy.deepcopy(suite)
    exact = next(item for item in tampered["items"] if item["class_label"] == "exact_match")
    exact["expected"]["resolution_outcomes"] = ["ambiguous"]
    with pytest.raises(IntegrityError, match="suite digest mismatch"):
        validate_suite(tampered, require_approval=False)

    leaked = copy.deepcopy(suite)
    leaked["items"][1]["semantic_family_id"] = leaked["items"][0]["semantic_family_id"]
    item = leaked["items"][1]
    unsigned = dict(item)
    unsigned.pop("item_sha256")
    item["item_sha256"] = digest(unsigned)
    unsigned_suite = dict(leaked)
    unsigned_suite.pop("suite_sha256")
    leaked["suite_sha256"] = digest(unsigned_suite)
    with pytest.raises(IntegrityError, match="semantic-family leakage"):
        validate_suite(leaked, require_approval=False)


def test_daniel_approval_is_required_for_accepted_gold() -> None:
    suite = load(SUITE)
    with pytest.raises(IntegrityError, match="Daniel approval required"):
        validate_suite(suite, require_approval=True)
