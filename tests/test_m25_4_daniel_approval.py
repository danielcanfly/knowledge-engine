from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledge_engine.m25_identity_benchmark import digest, validate_suite

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m25"

APPROVED_CANDIDATE_HEAD = "cf56bad3b9128020214c3a30100ec741d6842e56"
POLICY_SHA256 = "0e404be34a4dac4816dced3c9db1a0ec9543a83adcae83f01fe85f5a3d822246"
PROVISIONAL_SUITE_SHA256 = "103db6e982e71ed8e4c442eb4f36f48b06eb846fdc3f339fb3cd078215b5ddfc"
PROVISIONAL_BASELINE_SHA256 = "993ab879129db14400603c8a213a82c2437c6b545f998127d7ad19a9153c17d2"
GATE_SHA256 = "0adafb1f42089c98ef76b0b8c3c953e3c83e1bfde8b2fa53a5e8cc91aab7aecb"
APPROVAL_RECORD_SHA256 = "3702168d2ad99e388f1355bd2c2d49089dcf1aaa36731b873d4e95e8b84d2f9f"
FINAL_SUITE_SHA256 = "e52216c4fffd03b5cf4cbd68c049ca2fc688e539743761768d08a3348572a3e6"
FINAL_SPLIT_SHA256 = "409d51ccc425823f77c192d507440956da7adfde0544c3c8a8f647600d30696d"
FINAL_LEDGER_SHA256 = "1fcc42129a0c4f6ec5b7b5b0987e63127026a0b3ab74a159d3c1d83d8fd320fb"
FINAL_BASELINE_SHA256 = "1cf1c8a245d800d7eb091cf15ca4fe203958a1f98969da0fdd570a4bebde83b8"


def load(name: str) -> dict[str, Any]:
    value = json.loads((PILOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def verify_signed(value: dict[str, Any], field: str) -> None:
    unsigned = dict(value)
    claimed = unsigned.pop(field)
    assert claimed == digest(unsigned)


def semantic_item(item: dict[str, Any]) -> dict[str, Any]:
    value = dict(item)
    value.pop("annotation_status")
    value.pop("item_sha256")
    return value


def test_daniel_approval_record_is_exact_and_bounded() -> None:
    approval = load("m25-4-daniel-approval.json")
    verify_signed(approval, "approval_record_sha256")
    assert approval["approval_record_sha256"] == APPROVAL_RECORD_SHA256
    assert approval["approved_candidate_head"] == APPROVED_CANDIDATE_HEAD
    assert approval["authority_actor"] == "huaihsuanbusiness"
    assert approval["authority_comment_id"] == 5053875354
    assert approval["annotation_policy_sha256"] == POLICY_SHA256
    assert approval["approved_provisional_suite_sha256"] == PROVISIONAL_SUITE_SHA256
    assert approval["provisional_baseline_sha256"] == PROVISIONAL_BASELINE_SHA256
    assert approval["gate_sha256"] == GATE_SHA256
    assert approval["decisions"] == {
        "approve_annotation_and_adjudication_policy": True,
        "approve_all_30_provisional_labels": True,
        "confirm_zero_disputed_items": True,
    }
    assert approval["disputed_item_count"] == 0
    assert all(value is False for value in approval["approval_scope"].values())


def test_final_suite_promotes_status_without_semantic_label_drift() -> None:
    provisional = load("m25-4-gold-suite.provisional.json")
    approved = load("m25-4-gold-suite.json")
    validate_suite(approved, require_approval=True)
    assert provisional["suite_sha256"] == PROVISIONAL_SUITE_SHA256
    assert approved["suite_sha256"] == FINAL_SUITE_SHA256
    assert approved["approval_status"] == "approved_by_daniel"
    assert approved["suite_revision"] == "approved-1"
    provisional_root = dict(provisional)
    approved_root = dict(approved)
    for value in (provisional_root, approved_root):
        value.pop("approval_status")
        value.pop("suite_revision")
        value.pop("suite_sha256")
        value.pop("items")
    assert approved_root == provisional_root
    assert [item["item_id"] for item in approved["items"]] == [
        item["item_id"] for item in provisional["items"]
    ]
    for provisional_item, approved_item in zip(
        provisional["items"], approved["items"], strict=True
    ):
        assert provisional_item["annotation_status"] == "provisional_pending_daniel"
        assert approved_item["annotation_status"] == "approved"
        assert semantic_item(approved_item) == semantic_item(provisional_item)
        verify_signed(approved_item, "item_sha256")


def test_accepted_split_manifest_is_bound_and_leak_free() -> None:
    suite = load("m25-4-gold-suite.json")
    manifest = load("m25-4-split-manifest.accepted.json")
    verify_signed(manifest, "manifest_sha256")
    assert manifest["manifest_sha256"] == FINAL_SPLIT_SHA256
    assert manifest["suite_sha256"] == FINAL_SUITE_SHA256
    expected = [
        {
            "item_id": item["item_id"],
            "semantic_family_id": item["semantic_family_id"],
            "class_label": item["class_label"],
            "split": item["split"],
            "item_sha256": item["item_sha256"],
        }
        for item in suite["items"]
    ]
    assert manifest["assignments"] == expected
    families = [item["semantic_family_id"] for item in manifest["assignments"]]
    assert len(families) == len(set(families)) == 30
    assert manifest["final_split_calibration_permitted"] is False


def test_approved_ledger_records_exact_authority_without_m25_5() -> None:
    ledger = load("m25-4-adjudication-ledger.approved.json")
    approval = load("m25-4-daniel-approval.json")
    verify_signed(ledger, "ledger_sha256")
    assert ledger["ledger_sha256"] == FINAL_LEDGER_SHA256
    assert ledger["suite_sha256"] == FINAL_SUITE_SHA256
    assert ledger["policy_status"] == "approved_by_daniel"
    assert ledger["label_decision_status"] == "approved_by_daniel"
    assert ledger["disputed_item_count"] == 0
    assert ledger["disputed_items"] == []
    assert not any(ledger["decision_required"].values())
    assert ledger["decision"]["approved_candidate_head"] == APPROVED_CANDIDATE_HEAD
    assert ledger["decision"]["approval_record_sha256"] == approval["approval_record_sha256"]
    assert ledger["decision"]["m25_5_authorized"] is False


def test_accepted_baseline_changes_status_not_measurement() -> None:
    provisional = load("m25-4-baseline-report.provisional.json")
    accepted = load("m25-4-baseline-report.json")
    verify_signed(accepted, "report_sha256")
    assert provisional["report_sha256"] == PROVISIONAL_BASELINE_SHA256
    assert accepted["report_sha256"] == FINAL_BASELINE_SHA256
    assert accepted["suite_sha256"] == FINAL_SUITE_SHA256
    assert accepted["suite_approval_status"] == "approved_by_daniel"
    assert accepted["baseline_status"] == "accepted_baseline"
    for field in ("denominators", "metrics", "confusion_matrix", "error_taxonomy", "results"):
        assert accepted[field] == provisional[field]
    assert accepted["resolver_threshold_or_code_changed"] is False
    assert accepted["final_split_used_for_calibration"] is False
    assert accepted["m25_5_authorized"] is False
    assert accepted["metrics"]["semantic_decision_accuracy"] == 1.0
    assert accepted["metrics"]["false_merge_count"] == 0
    assert accepted["metrics"]["explanation_signal_coverage"] == 0.6
