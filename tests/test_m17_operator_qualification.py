from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.m17_operator_qualification import (
    assess_submission,
    build_training_plan,
    validate_training_registry,
    verify_report,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/operations/m17/training-registry.json"


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _submission() -> dict:
    registry = _registry()
    results = []
    for exercise in registry["exercises"]:
        minimum = exercise["minimum_evidence_items"]
        evidence = [
            {"name": f"evidence-{index}", "sha256": f"{index + 1:064x}"}
            for index in range(minimum)
        ]
        results.append(
            {
                "exercise_id": exercise["id"],
                "status": "passed",
                "score": exercise["weight"],
                "evidence": evidence,
            }
        )
    return {
        "operator_id": "operator-17",
        "evaluator_id": "evaluator-04",
        "attempt": 1,
        "results": results,
    }


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_registry_and_plan_pass() -> None:
    report = validate_training_registry(ROOT, REGISTRY)
    assert report["status"] == "passed", report["issues"]
    assert report["exercise_count"] == 7
    assert report["weight_total"] == 100
    assert verify_report(report)
    plan = build_training_plan(REGISTRY)
    assert plan["exercise_count"] == 7
    assert verify_report(plan)


def test_complete_independent_assessment_qualifies(tmp_path: Path) -> None:
    path = _write(tmp_path / "submission.json", _submission())
    report = assess_submission(REGISTRY, path)
    assert report["status"] == "qualified", report["issues"]
    assert report["total_score"] == 100
    assert report["critical_failures"] == []
    assert verify_report(report)


def test_self_assessment_is_rejected(tmp_path: Path) -> None:
    payload = _submission()
    payload["evaluator_id"] = payload["operator_id"]
    report = assess_submission(REGISTRY, _write(tmp_path / "submission.json", payload))
    assert report["status"] == "not_qualified"
    assert any(item["code"] == "self_assessment_forbidden" for item in report["issues"])


def test_missing_critical_exercise_is_rejected(tmp_path: Path) -> None:
    payload = _submission()
    payload["results"] = payload["results"][:-1]
    report = assess_submission(REGISTRY, _write(tmp_path / "submission.json", payload))
    assert report["status"] == "not_qualified"
    assert "closeout_package" in report["critical_failures"]


def test_blocked_exercise_blocks_qualification(tmp_path: Path) -> None:
    payload = _submission()
    payload["results"][5]["status"] = "blocked"
    payload["results"][5]["score"] = 0
    report = assess_submission(REGISTRY, _write(tmp_path / "submission.json", payload))
    assert report["status"] == "blocked"
    assert "rollback_drill" in report["blocking_states"]


def test_score_inflation_and_bad_digest_are_rejected(tmp_path: Path) -> None:
    payload = _submission()
    payload["results"][0]["score"] = 999
    payload["results"][1]["evidence"][0]["sha256"] = "bad"
    report = assess_submission(REGISTRY, _write(tmp_path / "submission.json", payload))
    codes = {item["code"] for item in report["issues"]}
    assert "score_out_of_range" in codes
    assert "evidence_digest_invalid" in codes
    assert report["qualified"] is False


def test_registry_drift_and_report_tampering_are_detected(tmp_path: Path) -> None:
    registry = _registry()
    registry["exercises"][0]["weight"] = 11
    drift_path = _write(tmp_path / "registry.json", registry)
    report = validate_training_registry(ROOT, drift_path)
    assert report["status"] == "blocked"
    assert any(item["code"] == "weight_total_invalid" for item in report["issues"])
    report["weight_total"] = 100
    assert verify_report(report) is False
