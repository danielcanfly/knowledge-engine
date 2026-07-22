from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
M25_DOCS = ROOT / "docs" / "architecture" / "m25"
PILOT = ROOT / "pilot" / "m25"
SCHEMAS = ROOT / "schemas"

SCHEMA_FILES = {
    "m25-admission-plan-v1.schema.json": "knowledge-engine-m25-admission-plan/v1",
    "m25-admission-state-v1.schema.json": "knowledge-engine-m25-admission-state/v1",
    "m25-authority-envelope-v1.schema.json": "knowledge-engine-m25-authority-envelope/v1",
    "m25-adapter-envelope-v1.schema.json": "knowledge-engine-m25-adapter-envelope/v1",
}


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


def verify_self_digest(value: dict[str, Any], field: str = "self_sha256") -> None:
    unsigned = dict(value)
    claimed = unsigned.pop(field)
    assert claimed == hashlib.sha256(canonical(unsigned)).hexdigest()


def test_entry_baseline_is_exact_and_protected() -> None:
    baseline = load(PILOT / "m25-1-entry-baseline.json")
    verify_self_digest(baseline)
    assert baseline["repositories"]["engine"]["main_sha"] == (
        "25a119e428bb202ebbed4b5a73a4209c41f9ce27"
    )
    assert baseline["repositories"]["source"]["main_sha"] == (
        "acf78596ace8a7366688ccef72b507204d09d9f9"
    )
    assert baseline["repositories"]["foundation"]["main_sha"] == (
        "e5ef644053d34e89c70d2ceb37521e1c59234832"
    )
    assert baseline["release"]["production_retrieval"] == "lexical"
    assert baseline["drift_detected"] is False
    assert set(baseline["protected_mutations"].values()) == {False}


def test_reuse_map_classifies_all_components_and_prevents_parallel_stack() -> None:
    reuse = load(PILOT / "m25-1-reuse-map.json")
    verify_self_digest(reuse)
    assert reuse["no_parallel_ingestion_system"] is True
    assert reuse["canonical_evidence_namespace"] == "intake/v1"
    assert reuse["admission_control_namespace"] == "admission/v1"
    assert reuse["components"]
    allowed = set(reuse["classification_values"])
    assert all(component["decision"] in allowed for component in reuse["components"])
    serialized = json.dumps(reuse, sort_keys=True)
    assert "m21_entity_resolution.py" in serialized
    assert "versioned_adapter" in serialized
    assert "a6ba738d910d01d2ae99b1968f0831989934c549" in serialized


def test_state_machine_is_closed_adjacent_and_review_gated() -> None:
    machine = load(PILOT / "m25-1-state-machine.json")
    verify_self_digest(machine)
    states = set(machine["states"])
    assert set(machine["transitions"]) <= states
    for targets in machine["transitions"].values():
        assert set(targets) <= states
    for terminal in machine["terminal_states"]:
        assert machine["transitions"][terminal] == []
    assert machine["transitions"]["review_pending"] == [
        "approved",
        "rejected",
        "deferred",
        "duplicate",
        "blocked",
    ]
    assert machine["transition_rules"]["decision_digest_required_after_review_pending"] is True


def test_authority_matrix_is_default_deny_and_keeps_daniel_gates() -> None:
    authority = load(PILOT / "m25-1-authority-matrix.json")
    verify_self_digest(authority)
    assert authority["default_deny"] is True
    assert authority["authority_cannot_be_inferred_from_model_confidence"] is True
    rows = {row["action"]: row for row in authority["rows"]}
    assert rows["record_knowledge_decision"]["Daniel"] == "required"
    assert rows["merge_source_pr"]["Daniel"] == "required"
    assert rows["mutate_production_pointer"]["Daniel"] == "required"
    assert rows["enable_semantic_or_hybrid_serving"]["ChatGPT"] == "forbidden_in_m25"


def test_m25_schemas_are_closed_versioned_draft_2020_12_contracts() -> None:
    for filename, version in SCHEMA_FILES.items():
        schema = load(SCHEMAS / filename)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].endswith(filename)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == version


def test_authority_schema_cannot_enable_m26_serving() -> None:
    schema = load(SCHEMAS / "m25-authority-envelope-v1.schema.json")
    properties = schema["properties"]
    assert properties["semantic_or_hybrid_enable_permitted"]["const"] is False
    assert properties["production_answer_serving_permitted"]["const"] is False


def test_adapter_schema_requires_declared_io_and_no_hidden_io() -> None:
    schema = load(SCHEMAS / "m25-adapter-envelope-v1.schema.json")
    required = set(schema["required"])
    assert {"may_read", "may_write", "must_not_write", "hidden_io_permitted"} <= required
    assert schema["properties"]["hidden_io_permitted"]["const"] is False


def test_architecture_freeze_binds_all_deliverables_and_m25_2_inputs() -> None:
    freeze = load(PILOT / "m25-1-architecture-freeze.json")
    verify_self_digest(freeze)
    assert freeze["exit_gate"] == {
        "all_components_classified": True,
        "m25_2_inputs_digest_bound": True,
        "no_parallel_ingestion_system": True,
        "protected_mutations_explicit": True,
    }
    assert set(freeze["stage_authority"].values()) == {False, True}
    assert freeze["stage_authority"]["architecture_only"] is True
    forbidden = {key for key, value in freeze["stage_authority"].items() if value is False}
    assert {
        "live_extraction_permitted",
        "review_ui_permitted",
        "source_mutation_permitted",
        "release_mutation_permitted",
        "pilot_execution_permitted",
        "m26_answer_serving_permitted",
    } <= forbidden
    for key, ref in freeze.items():
        if key.endswith("_ref") and isinstance(ref, dict) and "path" in ref:
            assert hashlib.sha256((ROOT / ref["path"]).read_bytes()).hexdigest() == ref["sha256"]


def test_examples_are_digest_bound_and_candidate_only() -> None:
    plan = load(M25_DOCS / "examples" / "m25-2-admission-plan.example.json")
    authority = load(M25_DOCS / "examples" / "m25-2-authority-envelope.example.json")
    adapter = load(M25_DOCS / "examples" / "m25-2-adapter-envelope.example.json")
    for value, field in (
        (plan, "plan_sha256"),
        (authority, "authority_sha256"),
        (adapter, "adapter_sha256"),
    ):
        unsigned = dict(value)
        claimed = unsigned.pop(field)
        assert claimed == hashlib.sha256(canonical(unsigned)).hexdigest()
    assert authority["candidate_write_permitted"] is True
    assert authority["source_pr_open_permitted"] is False
    assert authority["production_pointer_write_permitted"] is False
    assert authority["large_scale_ingestion_permitted"] is False
    assert adapter["hidden_io_permitted"] is False


def test_docs_pin_no_parallel_stack_and_source_authority() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(M25_DOCS.glob("*.md"))
    ).lower()
    assert "intake/v1" in combined
    assert "admission/v1" in combined
    assert "does not duplicate" in combined or "must not duplicate" in combined
    assert "canonical source remains the only editable knowledge truth" in combined
    assert "production retrieval remains lexical" in combined
