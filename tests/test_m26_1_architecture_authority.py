from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"


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


def verify_self_digest(value: dict[str, Any]) -> None:
    unsigned = dict(value)
    claimed = unsigned.pop("self_sha256")
    assert claimed == hashlib.sha256(canonical(unsigned)).hexdigest()


def has_type(value: Any, type_name: str) -> bool:
    mapping = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    return mapping[type_name]


def validate(value: Any, schema: dict[str, Any]) -> None:
    if "anyOf" in schema:
        for candidate in schema["anyOf"]:
            try:
                validate(value, candidate)
                break
            except AssertionError:
                continue
        else:
            raise AssertionError("no anyOf branch matched")

    if "const" in schema:
        assert value == schema["const"]
    if "enum" in schema:
        assert value in schema["enum"]

    declared_type = schema.get("type")
    if isinstance(declared_type, list):
        assert any(has_type(value, item) for item in declared_type)
    elif isinstance(declared_type, str):
        assert has_type(value, declared_type)

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        assert set(schema.get("required", [])) <= set(value)
        if schema.get("additionalProperties") is False:
            assert set(value) <= set(properties)
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key])

    if isinstance(value, list):
        if "minItems" in schema:
            assert len(value) >= schema["minItems"]
        if "maxItems" in schema:
            assert len(value) <= schema["maxItems"]
        if schema.get("uniqueItems"):
            assert len({canonical(item) for item in value}) == len(value)
        if "items" in schema:
            for item in value:
                validate(item, schema["items"])

    if isinstance(value, str):
        if "minLength" in schema:
            assert len(value) >= schema["minLength"]
        if "maxLength" in schema:
            assert len(value) <= schema["maxLength"]
        if "pattern" in schema:
            assert re.search(schema["pattern"], value)
        if schema.get("format") == "date-time":
            assert re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                value,
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema:
            assert value >= schema["minimum"]
        if "maximum" in schema:
            assert value <= schema["maximum"]


def test_entry_baseline_is_exact_and_protected() -> None:
    baseline = load(PILOT / "m26-1-entry-baseline.json")
    verify_self_digest(baseline)
    assert baseline["repositories"]["engine"]["main_sha"] == (
        "d68be491f8d07a727bcf1f521a2e5e75256eede3"
    )
    assert baseline["accepted_predecessors"]["m25_5"]["status"] == (
        "m25_5_identity_governance_accepted"
    )
    assert baseline["release"]["production_retrieval"] == "lexical"
    assert not any(baseline["protected_mutations"].values())


def test_architecture_and_provider_authority_fail_closed() -> None:
    freeze = load(PILOT / "m26-1-architecture-freeze.json")
    verify_self_digest(freeze)
    assert all(freeze["exit_gate"].values())
    authority = freeze["architecture_authority"]
    assert authority["architecture_and_contract_writes_permitted"] is True
    assert authority["provider_calls_permitted"] is False
    assert authority["production_answer_serving_permitted"] is False
    principles = freeze["authority_matrix"]["principles"]
    assert principles["model_confidence_grants_authority"] is False
    assert principles["citation_presence_equals_support"] is False
    assert freeze["provider_contract"]["provider_output_authority"] == "draft_only"
    assert freeze["provider_contract"]["live_provider_calls_permitted"] is False
    assert freeze["next_stage"] == {
        "stage_id": "M26.2",
        "authorized": False,
        "requires_status": "m26_1_architecture_authority_accepted",
    }


def test_state_machine_reuse_threats_and_flags_are_closed() -> None:
    freeze = load(PILOT / "m26-1-architecture-freeze.json")
    machine = freeze["state_machine"]
    states = set(machine["states"])
    assert set(machine["transitions"]) == states
    assert machine["rules"]["max_repair_attempts"] == 2
    assert machine["rules"]["provider_delta_is_never_final"] is True
    assert machine["rules"]["safe_streaming_requires_verified_payload"] is True
    for terminal in machine["terminal_states"]:
        assert machine["transitions"][terminal] == []

    reuse = json.dumps(freeze["reuse_map"], sort_keys=True)
    assert "m14_retrieval" in reuse
    assert "ReadOnlyGraphService" in reuse
    assert "M25 intake/v1" in reuse

    threats = json.dumps(freeze["threat_register"], sort_keys=True).lower()
    required = {
        "unsupported fluent claim",
        "citation theatre",
        "acl leakage",
        "prompt injection",
        "provider secret exposure",
        "unverified streaming",
    }
    assert all(item in threats for item in required)

    flags = {
        item["name"]: item["default"]
        for item in freeze["feature_flags"]["flags"]
    }
    assert flags["M26_GLOBAL_OFF"] is True
    assert all(
        value is False
        for name, value in flags.items()
        if name != "M26_GLOBAL_OFF"
    )


def test_schemas_are_closed_and_examples_validate() -> None:
    registry = load(PILOT / "m26-1-schema-registry.json")
    verify_self_digest(registry)
    schemas: dict[str, dict[str, Any]] = {}
    for entry in registry["schemas"]:
        path = ROOT / entry["path"]
        schema = load(path)
        schemas[path.name] = schema
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]

    downstream = load(PILOT / "m26-1-downstream-inputs.json")
    verify_self_digest(downstream)
    assert downstream["real_corpus"] is False
    assert downstream["provider_call"] is False
    for entry in downstream["examples"]:
        path = ROOT / entry["path"]
        schema_name = Path(entry["schema_path"]).name
        validate(load(path), schemas[schema_name])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]


def test_digest_references_and_documented_stop_lines() -> None:
    freeze = load(PILOT / "m26-1-architecture-freeze.json")
    for key in ("schema_registry_ref", "downstream_inputs_ref"):
        path = ROOT / freeze[key]["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == freeze[key]["sha256"]

    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOCS.glob("*.md"))
    ).lower()
    assert "citation presence is not claim support" in text
    assert "structured draft result" in text
    assert "production retrieval remains lexical" in text
    assert "there is no provider implementation or live call" in text
    assert "m26_1_architecture_authority_accepted" in text
