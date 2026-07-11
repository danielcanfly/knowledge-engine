from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.m17_failure_atlas import (
    REQUIRED_CATEGORIES,
    REQUIRED_PLANES,
    REQUIRED_STATES,
    load_registry,
    validate_failure_registry,
    verify_failure_report,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/troubleshooting/m17/failure-registry.json"


def _copy_payload() -> dict:
    return json.loads(json.dumps(load_registry(REGISTRY)))


def _write_registry(
    tmp_path: Path,
    payload: dict,
    *,
    omit_anchor: tuple[str, str] | None = None,
) -> Path:
    docs = tmp_path / "docs/troubleshooting/m17"
    docs.mkdir(parents=True)
    for relative in payload["owned_documents"]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Test troubleshooting document\n", encoding="utf-8")
    for entry in payload["entries"]:
        for field in ("reference", "recovery_reference"):
            reference = entry[field]
            target = tmp_path / reference["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            if omit_anchor == (entry["failure_id"], field):
                continue
            anchor = reference["anchor"]
            if anchor not in existing:
                target.write_text(existing + anchor + "\n", encoding="utf-8")
    path = docs / "failure-registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_repository_failure_registry_passes_and_is_tamper_evident() -> None:
    report = validate_failure_registry(root=ROOT, registry_path=REGISTRY)
    assert report["status"] == "passed"
    assert report["issue_count"] == 0
    assert report["entry_count"] == 20
    assert report["signal_count"] >= 40
    assert set(report["covered_planes"]) == REQUIRED_PLANES
    assert set(report["covered_categories"]) == REQUIRED_CATEGORIES
    assert set(report["covered_states"]) == REQUIRED_STATES
    assert verify_failure_report(report)
    tampered = dict(report)
    tampered["entry_count"] += 1
    assert not verify_failure_report(tampered)


def test_missing_category_coverage_is_blocked(tmp_path: Path) -> None:
    payload = _copy_payload()
    identity = next(item for item in payload["entries"] if item["category"] == "identity")
    identity["category"] = "approval"
    path = _write_registry(tmp_path, payload)
    report = validate_failure_registry(root=tmp_path, registry_path=path)
    assert report["status"] == "blocked"
    assert {item["code"] for item in report["issues"]} == {"category_coverage_mismatch"}


def test_duplicate_signal_is_blocked(tmp_path: Path) -> None:
    payload = _copy_payload()
    payload["entries"][1]["signals"][0] = payload["entries"][0]["signals"][0]
    path = _write_registry(tmp_path, payload)
    report = validate_failure_registry(root=tmp_path, registry_path=path)
    assert {item["code"] for item in report["issues"]} == {"duplicate_signal_code"}


def test_unsafe_diagnostic_command_is_blocked(tmp_path: Path) -> None:
    payload = _copy_payload()
    payload["entries"][0]["diagnostic_command"] = (
        "knowledge-m13 status --observed-at <UTC_TIME> --force"
    )
    path = _write_registry(tmp_path, payload)
    report = validate_failure_registry(root=tmp_path, registry_path=path)
    assert {item["code"] for item in report["issues"]} == {"unsafe_diagnostic_command"}


def test_missing_reference_anchor_is_blocked(tmp_path: Path) -> None:
    payload = _copy_payload()
    payload["entries"][0]["reference"]["anchor"] = "anchor-that-does-not-exist"
    path = _write_registry(tmp_path, payload, omit_anchor=("F001", "reference"))
    report = validate_failure_registry(root=tmp_path, registry_path=path)
    assert {item["code"] for item in report["issues"]} == {"missing_reference_anchor"}


def test_privacy_unsafe_owned_document_is_blocked(tmp_path: Path) -> None:
    payload = _copy_payload()
    path = _write_registry(tmp_path, payload)
    owned = tmp_path / payload["owned_documents"][0]
    owned.write_text("# Test\nauthorization: redacted-value\n", encoding="utf-8")
    report = validate_failure_registry(root=tmp_path, registry_path=path)
    assert {item["code"] for item in report["issues"]} == {"privacy_unsafe_content"}


def test_security_escalation_drift_is_blocked(tmp_path: Path) -> None:
    payload = _copy_payload()
    security = next(item for item in payload["entries"] if item["failure_id"] == "F014")
    security["escalation"] = "engine_maintainer"
    path = _write_registry(tmp_path, payload)
    report = validate_failure_registry(root=tmp_path, registry_path=path)
    assert {item["code"] for item in report["issues"]} == {"security_escalation_invalid"}
