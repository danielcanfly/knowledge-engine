from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from knowledge_engine.m25_source_pr_executor import (
    build_source_pr_plan,
    load_json,
    validate_plan,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m25"
SCHEMAS = ROOT / "schemas"


def schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def test_closed_schemas_accept_committed_synthetic_artifacts() -> None:
    pairs = [
        ("m25-source-baseline-v1.schema.json", "m25-7-source-baseline.synthetic.json"),
        ("m25-source-item-authority-v1.schema.json", "m25-7-item-authority.synthetic.json"),
        ("m25-source-pr-plan-v1.schema.json", "m25-7-source-pr-plan.synthetic.json"),
    ]
    for schema_name, artifact_name in pairs:
        jsonschema.Draft202012Validator.check_schema(schema(schema_name))
        jsonschema.validate(load_json(PILOT / artifact_name), schema(schema_name))


def test_all_m25_7_schemas_are_closed() -> None:
    names = [
        "m25-source-baseline-v1.schema.json",
        "m25-source-item-authority-v1.schema.json",
        "m25-source-pr-plan-v1.schema.json",
        "m25-source-plan-approval-v1.schema.json",
        "m25-source-opening-receipt-v1.schema.json",
    ]
    for name in names:
        value = schema(name)
        assert value["additionalProperties"] is False
        jsonschema.Draft202012Validator.check_schema(value)


def test_readiness_gate_preserves_all_authority_boundaries() -> None:
    gate = load_json(PILOT / "m25-7-readiness-gate.json")
    assert gate["status"] == "m25_7_executor_implemented_awaiting_daniel_item_decisions"
    assert gate["current_browser_evidence_is_canonical_authority"] is False
    assert gate["complete_real_terminal_decision_population_available"] is False
    assert gate["daniel_item_authority_envelope_available"] is False
    assert gate["exact_live_source_baseline_available"] is False
    assert gate["exact_source_plan_approved"] is False
    assert gate["source_branch_write_permitted"] is False
    assert gate["github_pr_creation_permitted"] is False
    assert gate["source_pr_merge_permitted"] is False
    assert gate["canonical_knowledge"] is False
    assert gate["production_authority"] is False
    assert gate["m25_8_authorized"] is False


def test_committed_plan_matches_deterministic_rebuild() -> None:
    actual = build_source_pr_plan(
        load_json(PILOT / "m25-7-review-batch.synthetic.json"),
        load_json(PILOT / "m25-7-audit-export.synthetic.json"),
        load_json(PILOT / "m25-7-m25-6-acceptance.synthetic.json"),
        load_json(PILOT / "m25-7-source-baseline.synthetic.json"),
        load_json(PILOT / "m25-7-item-authority.synthetic.json"),
    )
    expected = validate_plan(load_json(PILOT / "m25-7-source-pr-plan.synthetic.json"))
    assert actual == expected
