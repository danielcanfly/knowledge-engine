from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledge_engine.m26_final_authority_gate import verify_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_m26_10_acceptance_contract() -> None:
    acceptance = load(PILOT / "m26-10-acceptance.json")
    verify_self_digest(acceptance)
    assert acceptance["status"] == "m26_10_synthetic_final_authority_gate_accepted"
    assert acceptance["self_sha256"] == (
        "6626e2a5ef67580a455a5b744c53efd134ee7a5d08a93799f0506cf70764abfc"
    )
    assert acceptance["implementation"]["pull_request_number"] == 1170
    assert acceptance["implementation"]["merge_sha"] == (
        "9fdafee36202366c66aeb111d6943cbc279953f9"
    )
    assert acceptance["issue"]["number"] == 1169
    assert acceptance["issue"]["state"] == "closed"


def test_m26_10_acceptance_metrics_and_boundary() -> None:
    acceptance = load(PILOT / "m26-10-acceptance.json")
    benchmark = acceptance["benchmark"]
    assert benchmark["case_count"] == 12
    assert benchmark["passed_count"] == 12
    assert benchmark["failed_count"] == 0
    assert benchmark["approved_for_future_gate_count"] == 2
    assert benchmark["held_for_repair_count"] == 6
    assert benchmark["rejected_authority_escalation_count"] == 4
    authority = acceptance["authority_boundary"]
    allowed_true = {"synthetic_only", "baseline_refresh_review", "final_authority_review"}
    assert all(value is False for key, value in authority.items() if key not in allowed_true)


def test_m26_10_acceptance_evidence_and_closure() -> None:
    acceptance = load(PILOT / "m26-10-acceptance.json")
    artifact = acceptance["evidence_artifact"]
    assert artifact["artifact_id"] == 8613421036
    assert artifact["workflow_run_id"] == 30137800565
    assert artifact["digest"] == (
        "sha256:a1b6971d4b97eee3d95e393d1b51a78b4501741593acfc999289333530117a7a"
    )
    closure = acceptance["closure"]
    assert closure["m26_synthetic_chain_complete"] is True
    assert closure["production_authority_granted"] is False
    assert closure["future_live_corpus_or_provider_work_requires_new_explicit_authorization"] is True
