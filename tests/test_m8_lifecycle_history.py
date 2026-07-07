from __future__ import annotations

import json
from pathlib import Path
from runpy import run_path

import pytest

validate_history = run_path(
    "scripts/m8_validate_lifecycle_history.py"
)["validate_history"]

HISTORY = Path("governed_batches/evidence/m8-001-lifecycle-history.json")
SPEC = Path("governed_batches/m8-001-agent-execution-paths.json")
REGISTRY = Path("governed_batches/registry-v2.json")
POINTER = Path("governed_batches/evidence/m8-001-production-pointer.json")


def _validate(history: Path = HISTORY) -> dict:
    return validate_history(
        history_path=history,
        spec_path=SPEC,
        registry_path=REGISTRY,
        production_pointer_path=POINTER,
    )


def test_m8_lifecycle_history_reconciles_to_request_spec_committed() -> None:
    result = _validate()
    assert result["status"] == "passed"
    assert result["lifecycle_state"] == "request_spec_committed"
    assert result["transition_count"] == 5
    assert result["next_action"] == "review_production_promotion"
    assert result["production_mutated"] is False


def test_m8_lifecycle_history_rejects_skipped_transition(tmp_path: Path) -> None:
    payload = json.loads(HISTORY.read_text(encoding="utf-8"))
    payload["transitions"][1]["to"] = "candidate_built"
    path = tmp_path / "history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Exception, match="illegal lifecycle transition"):
        _validate(path)


def test_m8_lifecycle_history_rejects_production_drift(tmp_path: Path) -> None:
    payload = json.loads(HISTORY.read_text(encoding="utf-8"))
    payload["production_baseline"]["release_id"] = (
        "20260707T000000Z-000000000000"
    )
    path = tmp_path / "history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="production release baseline drift"):
        _validate(path)
