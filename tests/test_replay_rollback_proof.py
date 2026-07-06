from __future__ import annotations

import json
from pathlib import Path

from scripts.replay_rollback_proof import run_replay_rollback_proof


def test_replay_rollback_proof_writes_governed_evidence(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"

    summary = run_replay_rollback_proof(evidence_dir, "unit-test-run")

    assert summary["status"] == "passed"
    assert summary["promote_replay_idempotent"] is True
    assert summary["rollback_replay_idempotent"] is True
    assert summary["old_operation_after_rollback"]["status"] == "rejected"
    assert summary["governance"] == {
        "new_operation_required_after_rollback": True,
        "old_operation_cannot_revive_target_after_rollback": True,
        "rollback_restored_exact_previous_pointer_bytes": True,
    }

    expected_files = {
        "initial-production-pointer.json",
        "promote-first.json",
        "promote-replay.json",
        "rollback-first.json",
        "rollback-replay.json",
        "stale-promote-after-rollback.json",
        "new-operation-promote.json",
        "summary.json",
    }
    assert expected_files.issubset(
        {path.name for path in evidence_dir.iterdir() if path.is_file()}
    )

    stored_summary = json.loads((evidence_dir / "summary.json").read_text())
    assert stored_summary == summary
