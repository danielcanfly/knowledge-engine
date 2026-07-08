from __future__ import annotations

import json
import runpy
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

PACKAGE = Path("review_packages/m9-001")
SCRIPT = Path("scripts/validate_source_review_package.py")
_NAMESPACE = runpy.run_path(str(SCRIPT))
validate_source_review_package: Callable[[str | Path], dict[str, Any]] = _NAMESPACE[
    "validate_source_review_package"
]


def test_m9_source_review_package_is_valid_and_pending() -> None:
    result = validate_source_review_package(PACKAGE)

    assert result == {
        "schema_version": "governed-source-review-validation/v1",
        "status": "passed",
        "batch_id": "m9-001-agent-planning-strategies",
        "target_path": "bundle/concepts/agent-planning-strategies.md",
        "proposed_concept_sha256": (
            "cc6fe2743bec8bc90b6b7c5765dce5e32bdba060a0fd82817215197f37248e86"
        ),
        "claim_count": 11,
        "review_status": "pending_human_review",
        "source_change_ready": False,
        "canonical_write_authorized": False,
        "mutations_performed": [],
    }


def test_source_review_package_rejects_concept_tampering(tmp_path: Path) -> None:
    package = tmp_path / "package"
    shutil.copytree(PACKAGE, package)
    concept = package / "proposed-concept.md"
    concept.write_text(
        concept.read_text(encoding="utf-8") + "\nunauthorised edit\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="proposed concept SHA-256"):
        validate_source_review_package(package)


def test_source_review_package_rejects_implicit_approval(tmp_path: Path) -> None:
    package = tmp_path / "package"
    shutil.copytree(PACKAGE, package)
    decision_path = package / "proposed-review-decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["decision"] = "approve"
    decision["canonical_write_authorized"] = True
    decision_path.write_text(
        json.dumps(decision, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must remain unset before decision"):
        validate_source_review_package(package)
