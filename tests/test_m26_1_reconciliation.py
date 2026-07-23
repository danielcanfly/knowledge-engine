from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


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


def test_acceptance_identity_and_exact_implementation() -> None:
    acceptance = load(PILOT / "m26-1-acceptance.json")
    unsigned = dict(acceptance)
    claimed = unsigned.pop("self_sha256")
    assert claimed == hashlib.sha256(canonical(unsigned)).hexdigest()
    assert acceptance["status"] == "m26_1_architecture_authority_accepted"
    assert acceptance["predecessor"] == {
        "status": "m25_5_identity_governance_accepted",
        "main_seal_sha": "d68be491f8d07a727bcf1f521a2e5e75256eede3",
    }
    assert acceptance["implementation"]["pull_request_number"] == 1054
    assert acceptance["implementation"]["head_sha"] == (
        "7e23e50412a77dd2fabd80cd120a824919d68bb8"
    )
    assert acceptance["implementation"]["merge_sha"] == (
        "882d66fdb2bd17a1a1c6b7eb98c7a9242340a532"
    )
    assert acceptance["implementation"]["expected_head_merge"] is True
    assert acceptance["implementation"]["unresolved_review_thread_count"] == 0


def test_accepted_artifacts_are_byte_exact() -> None:
    acceptance = load(PILOT / "m26-1-acceptance.json")
    for artifact in acceptance["accepted_artifacts"].values():
        path = ROOT / artifact["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]

    freeze = load(PILOT / "m26-1-architecture-freeze.json")
    assert all(freeze["exit_gate"].values())
    assert freeze["next_stage"]["authorized"] is False


def test_workflow_and_evidence_identities_are_frozen() -> None:
    acceptance = load(PILOT / "m26-1-acceptance.json")
    assert acceptance["required_workflows"] == {
        "CI": 29987616013,
        "M26.1 Architecture Authority": 29987616046,
        "M17 Architecture Canon Acceptance": 29987616052,
        "M18 Graph v2 acceptance": 29987615986,
    }
    assert acceptance["evidence_artifact"] == {
        "workflow_run_id": 29987616046,
        "artifact_id": 8555671225,
        "name": "m26-1-architecture-authority-evidence",
        "digest": (
            "sha256:c10816ec357b12e49048b8f96b55679a"
            "be68aa4e501e05dbcf7413ccbe3fb08b"
        ),
    }
    assert all(
        value is True or value == 0
        for value in acceptance["acceptance_gates"].values()
    )


def test_authority_boundary_and_next_stage() -> None:
    acceptance = load(PILOT / "m26-1-acceptance.json")
    boundary = acceptance["authority_boundary"]
    assert boundary["architecture_only"] is True
    assert not any(
        value
        for key, value in boundary.items()
        if key != "architecture_only"
    )
    assert acceptance["execution_roles"] == {
        "chatgpt_primary_executor": True,
        "codex_escalations": 0,
        "codex_used": False,
        "daniel_gate_required": False,
    }
    assert acceptance["next_stage"] == {
        "stage_id": "M26.2",
        "name": "Retrieval Envelope and Evidence Assembly",
        "authorized": True,
        "predecessor_status_required": "m26_1_architecture_authority_accepted",
        "provider_calls_permitted": False,
        "real_corpus_binding_permitted": False,
    }
