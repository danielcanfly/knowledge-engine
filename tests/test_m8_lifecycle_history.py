from __future__ import annotations

import json
from pathlib import Path
from runpy import run_path

import pytest

validate_closure = run_path("scripts/m8_validate_closure.py")["validate_closure"]

HISTORY = Path("governed_batches/evidence/m8-001-lifecycle-history.json")
SPEC = Path("governed_batches/m8-001-agent-execution-paths.json")
REGISTRY = Path("governed_batches/registry-v2.json")
BASELINE = Path("governed_batches/evidence/m8-001-production-pointer.json")


def _validate(history: Path = HISTORY) -> dict:
    return validate_closure(
        history_path=history,
        spec_path=SPEC,
        registry_path=REGISTRY,
        baseline_path=BASELINE,
    )


def test_m8_lifecycle_history_closes_after_idempotent_replay() -> None:
    result = _validate()
    assert result["status"] == "passed"
    assert result["lifecycle_state"] == "closed"
    assert result["transition_count"] == 7
    assert result["idempotent_replay"] is True
    assert result["production_mutated"] is True
    assert result["next_action"] == "start_next_batch"


def test_m8_closure_rejects_skipped_transition(tmp_path: Path) -> None:
    payload = json.loads(HISTORY.read_text(encoding="utf-8"))
    payload["transitions"][1]["to"] = "candidate_built"
    path = tmp_path / "history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Exception, match="illegal lifecycle transition"):
        _validate(path)


def test_m8_closure_rejects_non_idempotent_replay(tmp_path: Path) -> None:
    payload = json.loads(HISTORY.read_text(encoding="utf-8"))
    payload["transitions"][-1]["evidence"]["idempotent"] = False
    path = tmp_path / "history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="replay evidence mismatch: idempotent"):
        _validate(path)


def test_m8_closure_rejects_pointer_drift(tmp_path: Path) -> None:
    payload = json.loads(HISTORY.read_text(encoding="utf-8"))
    payload["production_target"]["pointer_sha256"] = "0" * 64
    path = tmp_path / "history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="initial pointer mismatch"):
        _validate(path)
