from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "pilot" / "m25" / "m25-1-acceptance.json"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_m25_1_acceptance_is_digest_bound_and_exact() -> None:
    value = load(ACCEPTANCE)
    unsigned = dict(value)
    claimed = unsigned.pop("self_sha256")
    assert claimed == hashlib.sha256(canonical(unsigned)).hexdigest()
    assert value["status"] == "m25_1_architecture_freeze_accepted"
    assert value["implementation"]["base_sha"] == (
        "25a119e428bb202ebbed4b5a73a4209c41f9ce27"
    )
    assert value["implementation"]["head_sha"] == (
        "01c6e496e8c5947de02772d9035093b3fc991a4e"
    )
    assert value["implementation"]["merge_sha"] == (
        "8a3e798352f6d16e146b0dc25e1812cc9583cc7f"
    )
    assert value["implementation"]["expected_head_enforced"] is True


def test_all_required_workflows_passed() -> None:
    value = load(ACCEPTANCE)
    runs = value["workflow_runs"]
    assert {run["name"] for run in runs} == {
        "M25.1 Admission Architecture Freeze",
        "CI",
        "M17 Architecture Canon Acceptance",
        "M18 Graph v2 acceptance",
    }
    assert all(run["conclusion"] == "success" for run in runs)
    assert all(
        run["head_sha"] == "01c6e496e8c5947de02772d9035093b3fc991a4e"
        for run in runs
    )


def test_accepted_artifacts_match_repository_bytes() -> None:
    value = load(ACCEPTANCE)
    for artifact in value["accepted_artifacts"].values():
        path = ROOT / artifact["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["file_sha256"]
        payload = load(path)
        assert payload["self_sha256"] == artifact["self_sha256"]


def test_no_authority_drift_and_codex_was_not_needed() -> None:
    value = load(ACCEPTANCE)
    assert set(value["protected_mutations"].values()) == {False}
    assert value["acceptance_gates"]["protected_mutations_zero"] is True
    assert value["execution_roles"] == {
        "chatgpt_primary_executor": True,
        "codex_used": False,
        "codex_escalations": 0,
        "daniel_gate_required": False,
    }


def test_m25_2_is_the_only_authorized_next_stage() -> None:
    value = load(ACCEPTANCE)
    assert value["next_stage"] == {
        "stage_id": "M25.2",
        "name": "Intake and Batch Orchestrator",
        "authorized": True,
        "predecessor_status_required": "m25_1_architecture_freeze_accepted",
    }
    assert value["reconciliation"]["no_new_authority_granted"] is True
