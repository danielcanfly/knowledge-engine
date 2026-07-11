from __future__ import annotations

import copy
import json
from pathlib import Path

from knowledge_engine.m17_ga_evidence import (
    load_registry,
    validate_ga_evidence,
    verify_report,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/ga/m17/ga-evidence-registry.json"


def _write_registry(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_repository_ga_evidence_registry_passes() -> None:
    report = validate_ga_evidence(ROOT, REGISTRY)
    assert report["status"] == "passed", report["issues"]
    assert report["readiness"] == "ready_for_m17_7"
    assert report["ga_declaration_allowed"] is False
    assert report["capability_count"] == 20
    assert report["evidence_complete_count"] == 20
    assert report["gap_count"] == 0
    assert verify_report(report)


def test_missing_capability_fails_closed(tmp_path: Path) -> None:
    payload = load_registry(REGISTRY)
    payload["capabilities"].pop()
    report = validate_ga_evidence(ROOT, _write_registry(tmp_path, payload))
    assert report["status"] == "failed"
    assert any(issue["code"] == "capability_set" for issue in report["issues"])


def test_narrative_only_claim_is_rejected(tmp_path: Path) -> None:
    payload = load_registry(REGISTRY)
    payload["capabilities"][0]["contract_modules"] = []
    payload["capabilities"][0]["tests"] = []
    payload["capabilities"][0]["workflows"] = []
    report = validate_ga_evidence(ROOT, _write_registry(tmp_path, payload))
    assert report["status"] == "failed"
    assert sum(issue["code"] == "narrative_only" for issue in report["issues"]) == 3


def test_malformed_merge_commit_is_rejected(tmp_path: Path) -> None:
    payload = load_registry(REGISTRY)
    payload["capabilities"][8]["evidence"]["merge_commit"] = "main"
    report = validate_ga_evidence(ROOT, _write_registry(tmp_path, payload))
    assert any(issue["code"] == "merge_commit" for issue in report["issues"])


def test_unresolved_gap_blocks_m17_7_readiness(tmp_path: Path) -> None:
    payload = load_registry(REGISTRY)
    row = payload["capabilities"][13]
    row["state"] = "gap"
    row["gap"] = "freshness evidence missing"
    row["closure_action"] = "restore exact evidence"
    report = validate_ga_evidence(ROOT, _write_registry(tmp_path, payload))
    assert report["status"] == "failed"
    assert report["readiness"] == "blocked"
    assert any(issue["code"] == "not_ready_for_m17_7" for issue in report["issues"])


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    payload = load_registry(REGISTRY)
    payload["capabilities"][0]["contract_modules"] = ["../outside.py"]
    report = validate_ga_evidence(ROOT, _write_registry(tmp_path, payload))
    assert any(issue["code"] == "unsafe_path" for issue in report["issues"])


def test_report_tampering_is_detected() -> None:
    report = validate_ga_evidence(ROOT, REGISTRY)
    tampered = copy.deepcopy(report)
    tampered["evidence_complete_count"] = 19
    assert verify_report(report)
    assert not verify_report(tampered)
