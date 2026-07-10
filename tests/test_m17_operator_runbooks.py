from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.m17_operator_runbooks import (
    REQUIRED_PHASES,
    load_registry,
    validate_runbook_registry,
    verify_runbook_report,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/operations/m17/runbook-registry.json"


def _write_registry(tmp_path: Path, payload: dict) -> Path:
    docs = tmp_path / "docs/operations/m17"
    docs.mkdir(parents=True)
    for relative in payload["owned_documents"]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Test document\n", encoding="utf-8")
    for step in payload["steps"]:
        target = tmp_path / step["reference"]["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        anchor = step["reference"]["anchor"]
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        if anchor not in existing:
            target.write_text(existing + anchor + "\n", encoding="utf-8")
    path = docs / "runbook-registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_repository_runbook_registry_passes_and_is_tamper_evident() -> None:
    report = validate_runbook_registry(root=ROOT, registry_path=REGISTRY)
    assert report["status"] == "passed"
    assert report["issue_count"] == 0
    assert report["step_count"] == len(REQUIRED_PHASES)
    assert verify_runbook_report(report)
    tampered = dict(report)
    tampered["step_count"] += 1
    assert not verify_runbook_report(tampered)


def test_missing_phase_is_blocked(tmp_path: Path) -> None:
    payload = load_registry(REGISTRY)
    payload["steps"] = payload["steps"][:-1]
    path = _write_registry(tmp_path, payload)
    report = validate_runbook_registry(root=tmp_path, registry_path=path)
    codes = {item["code"] for item in report["issues"]}
    assert report["status"] == "blocked"
    assert "phase_coverage_mismatch" in codes


def test_unsafe_command_is_blocked(tmp_path: Path) -> None:
    payload = load_registry(REGISTRY)
    payload["steps"][0]["command_template"] = "git push --force origin main"
    path = _write_registry(tmp_path, payload)
    report = validate_runbook_registry(root=tmp_path, registry_path=path)
    assert "unsafe_command_template" in {item["code"] for item in report["issues"]}


def test_mutation_without_guards_is_blocked(tmp_path: Path) -> None:
    payload = load_registry(REGISTRY)
    step = next(item for item in payload["steps"] if item["phase"] == "production_promotion")
    step["requires_approval"] = False
    step["requires_operation_id"] = False
    step["requires_expected_previous"] = False
    path = _write_registry(tmp_path, payload)
    report = validate_runbook_registry(root=tmp_path, registry_path=path)
    assert "missing_mutation_guard" in {item["code"] for item in report["issues"]}


def test_broken_evidence_chain_is_blocked(tmp_path: Path) -> None:
    payload = load_registry(REGISTRY)
    payload["steps"][1]["inputs"] = ["unrelated_identity"]
    path = _write_registry(tmp_path, payload)
    report = validate_runbook_registry(root=tmp_path, registry_path=path)
    assert "broken_evidence_chain" in {item["code"] for item in report["issues"]}


def test_missing_reference_anchor_is_blocked(tmp_path: Path) -> None:
    payload = load_registry(REGISTRY)
    payload["steps"][0]["reference"]["anchor"] = "anchor-that-does-not-exist"
    path = _write_registry(tmp_path, payload)
    report = validate_runbook_registry(root=tmp_path, registry_path=path)
    assert "missing_reference_anchor" in {item["code"] for item in report["issues"]}


def test_dynamic_identity_in_owned_document_is_blocked(tmp_path: Path) -> None:
    payload = load_registry(REGISTRY)
    path = _write_registry(tmp_path, payload)
    owned = tmp_path / payload["owned_documents"][0]
    owned.write_text("# Test\n" + "a" * 40 + "\n", encoding="utf-8")
    report = validate_runbook_registry(root=tmp_path, registry_path=path)
    assert "stale_dynamic_identity" in {item["code"] for item in report["issues"]}
