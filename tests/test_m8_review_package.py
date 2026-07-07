from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.m8_validate_review_package import validate_review_package


def test_m8_review_package_is_complete_and_pending() -> None:
    result = validate_review_package(Path("review_packages/m8-001"))
    assert result["status"] == "passed"
    assert result["claim_count"] == 9
    assert result["review_status"] == "pending_human_review"
    assert result["source_change_ready"] is False
    assert result["mutations_performed"] == []


def test_m8_review_package_rejects_non_pending_state(tmp_path: Path) -> None:
    package = tmp_path / "m8-001"
    shutil.copytree(Path("review_packages/m8-001"), package)
    decision_path = package / "proposed-review-decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["status"] = "decision_recorded"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")

    with pytest.raises(ValueError, match="review status mismatch"):
        validate_review_package(package)


def test_m8_review_package_rejects_content_drift(tmp_path: Path) -> None:
    package = tmp_path / "m8-001"
    shutil.copytree(Path("review_packages/m8-001"), package)
    concept_path = package / "proposed-concept.md"
    concept_path.write_text(
        concept_path.read_text(encoding="utf-8") + "\nUnreviewed change.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="proposed concept SHA-256 mismatch"):
        validate_review_package(package)
