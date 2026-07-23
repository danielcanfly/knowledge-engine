from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledge_engine.m26_retrieval_envelope import verify_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_m26_8_acceptance_contract() -> None:
    acceptance = load(PILOT / "m26-8-acceptance.json")
    verify_self_digest(acceptance)
    assert acceptance["status"] == "m26_8_preview_evidence_candidate_bundle_accepted"
    assert acceptance["schema_version"] == "knowledge-engine-m26-8-acceptance/v1"
    assert acceptance["implementation"]["pull_request_number"] == 1099
    assert acceptance["implementation"]["final_head_sha"] == (
        "365b0089e89ae692f7e79ddbc47d5976fb5951ee"
    )
    assert acceptance["implementation"]["merge_sha"] == (
        "c65f427a85d58e15d6f6378f962ad5adfe42addf"
    )
    assert acceptance["issue"]["number"] == 1098
    assert acceptance["issue"]["state"] == "closed"
    assert acceptance["benchmark"]["case_count"] == 12
    assert acceptance["benchmark"]["passed_count"] == 12
    assert acceptance["benchmark"]["failed_count"] == 0


def test_m26_8_acceptance_authority_boundary() -> None:
    authority = load(PILOT / "m26-8-acceptance.json")["authority_boundary"]
    assert authority["synthetic_only"] is True
    assert authority["preview_evidence_integration"] is True
    assert authority["candidate_bundle"] is True
    forbidden = {
        key: value
        for key, value in authority.items()
        if key not in {"synthetic_only", "preview_evidence_integration", "candidate_bundle"}
    }
    assert not any(forbidden.values())


def test_m26_8_next_stage_is_bounded() -> None:
    next_stage = load(PILOT / "m26-8-acceptance.json")["next_stage"]
    assert next_stage["stage_id"] == "M26.9"
    assert next_stage["authorized"] is True
    assert next_stage["synthetic_only"] is True
    assert next_stage["candidate_bundle_review_permitted"] is True
    assert next_stage["baseline_refresh_planning_permitted"] is True
    assert next_stage["live_provider_calls_permitted"] is False
    assert next_stage["real_corpus_binding_permitted"] is False
    assert next_stage["production_answer_serving_permitted"] is False
    assert next_stage["production_pointer_mutation_permitted"] is False
    assert next_stage["verified_final_answer_permitted"] is False
