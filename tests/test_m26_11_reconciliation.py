from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.m26_production_authority import verify_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


def load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_m26_11_acceptance_contract() -> None:
    acceptance = load(PILOT / "m26-11-acceptance.json")
    verify_self_digest(acceptance)
    assert acceptance["status"] == (
        "m26_11_production_authority_activation_contract_accepted"
    )
    assert acceptance["self_sha256"] == (
        "ca8236314c8ab67812979e0525f588ed2e11341382149adad96baf479cfa4f3e"
    )
    implementation = acceptance["implementation"]
    assert implementation["pull_request_number"] == 1174
    assert implementation["merge_sha"] == (
        "e8b5c63ea57a8df581a2792af267f3b22a65db3c"
    )


def test_m26_11_acceptance_boundary() -> None:
    acceptance = load(PILOT / "m26-11-acceptance.json")
    authority = acceptance["authority_boundary"]
    allowed_true = {
        "contract_definition",
        "secret_name_inventory",
        "rollback_contract_definition",
    }
    assert all(
        value is False
        for key, value in authority.items()
        if key not in allowed_true
    )


def test_m26_11_next_stage_is_bounded() -> None:
    acceptance = load(PILOT / "m26-11-acceptance.json")
    next_stage = acceptance["next_stage"]
    assert next_stage["stage_id"] == "M26.12"
    assert next_stage["authorized"] is True
    assert next_stage["production_release_read_permitted"] is True
    assert next_stage["production_qdrant_query_permitted"] is True
    assert next_stage["live_provider_calls_permitted"] is False
    assert next_stage["public_traffic_permitted"] is False
    assert next_stage["production_pointer_mutation_permitted"] is False
    assert next_stage["verified_final_answer_permitted"] is False
