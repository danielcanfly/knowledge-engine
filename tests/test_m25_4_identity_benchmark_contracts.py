from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from knowledge_engine.m25_identity_benchmark import digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m25"


def load(name: str) -> dict[str, Any]:
    value = json.loads((PILOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_policy_suite_report_and_gate_identities_are_exact() -> None:
    policy = load("m25-4-annotation-policy.json")
    suite = load("m25-4-gold-suite.provisional.json")
    report = load("m25-4-baseline-report.provisional.json")
    gate = load("m25-4-daniel-annotation-gate.json")
    assert digest(policy) == "0e404be34a4dac4816dced3c9db1a0ec9543a83adcae83f01fe85f5a3d822246"
    assert suite["suite_sha256"] == (
        "103db6e982e71ed8e4c442eb4f36f48b06eb846fdc3f339fb3cd078215b5ddfc"
    )
    assert report["report_sha256"] == (
        "993ab879129db14400603c8a213a82c2437c6b545f998127d7ad19a9153c17d2"
    )
    assert gate["gate_sha256"] == "0adafb1f42089c98ef76b0b8c3c953e3c83e1bfde8b2fa53a5e8cc91aab7aecb"
    assert gate["annotation_policy_sha256"] == digest(policy)
    assert gate["gold_suite_sha256"] == suite["suite_sha256"]
    assert gate["provisional_baseline_report_sha256"] == report["report_sha256"]


def test_daniel_gate_is_pending_and_does_not_authorize_m25_5() -> None:
    gate = load("m25-4-daniel-annotation-gate.json")
    assert gate["status"] == "awaiting_daniel_decision"
    assert gate["disputed_item_count"] == 0
    assert gate["requested_decisions"] == {
        "approve_all_30_provisional_labels": None,
        "approve_annotation_and_adjudication_policy": None,
        "confirm_zero_disputed_items": None,
    }
    assert gate["approval_scope"]["m25_5_authorized_by_this_decision"] is False
    assert all(value is False for value in gate["protected_mutations"].values())


def test_committed_schemas_and_docs_exist() -> None:
    required = [
        "docs/architecture/m25/m25-4-annotation-guide.md",
        "docs/architecture/m25/m25-4-gold-benchmark.md",
        "schemas/m25-identity-adjudication-ledger-v1.schema.json",
        "schemas/m25-identity-baseline-report-v1.schema.json",
        "schemas/m25-identity-gold-item-v1.schema.json",
        "schemas/m25-identity-gold-suite-v1.schema.json",
        "schemas/m25-identity-split-manifest-v1.schema.json",
    ]
    for relative in required:
        path = ROOT / relative
        assert path.is_file(), relative
        assert hashlib.sha256(path.read_bytes()).hexdigest()
