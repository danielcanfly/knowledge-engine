from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
M11_ROOT = ROOT / "docs" / "architecture" / "m11"
SCHEMA_ROOT = ROOT / "schemas"

SCHEMAS = {
    "input": (
        "compiler-input-v1.schema.json",
        "knowledge-compiler-input/v1",
    ),
    "block": (
        "compiler-structured-block-v1.schema.json",
        "knowledge-compiler-structured-block/v1",
    ),
    "source_map": (
        "compiler-source-map-v1.schema.json",
        "knowledge-compiler-source-map/v1",
    ),
    "candidate": (
        "compiler-extraction-candidate-v1.schema.json",
        "knowledge-compiler-extraction-candidate/v1",
    ),
    "resolution": (
        "compiler-resolution-v1.schema.json",
        "knowledge-compiler-resolution/v1",
    ),
    "proposal": (
        "compiler-synthesis-proposal-v1.schema.json",
        "knowledge-compiler-synthesis-proposal/v1",
    ),
}

RESOLUTION_OUTCOMES = {
    "new_concept",
    "existing_concept_update",
    "alias",
    "duplicate",
    "contradiction",
    "supersession",
    "unresolved_conflict",
    "rejected_unsupported_claim",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_m11_schemas_are_closed_versioned_draft_2020_12_contracts() -> None:
    for filename, schema_version in SCHEMAS.values():
        schema = load_json(SCHEMA_ROOT / filename)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].endswith(filename)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == schema_version


def test_compiler_input_binds_m10_evidence_policy_and_compiler_identity() -> None:
    schema = load_json(SCHEMA_ROOT / SCHEMAS["input"][0])
    required = set(schema["required"])
    assert {
        "compiler_run_id",
        "snapshot_ref",
        "derivative_ref",
        "admission_ref",
        "effective_policy",
        "compiler_identity",
    } <= required
    policy = schema["$defs"]["effectivePolicy"]
    assert policy["properties"]["may_broaden"]["const"] is False
    admission = schema["$defs"]["admissionRef"]
    assert admission["properties"]["status"]["const"] == "accepted_for_compilation"


def test_structured_blocks_and_candidates_require_exact_evidence() -> None:
    block = load_json(SCHEMA_ROOT / SCHEMAS["block"][0])
    assert block["properties"]["source_map_ids"]["minItems"] == 1
    assert block["properties"]["canonical_write_permitted"]["const"] is False

    candidate = load_json(SCHEMA_ROOT / SCHEMAS["candidate"][0])
    assert candidate["properties"]["evidence_refs"]["minItems"] == 1
    assert candidate["properties"]["confidence"]["maximum"] == 1
    assert candidate["properties"]["canonical_write_permitted"]["const"] is False
    rejection_rule = candidate["allOf"][0]["then"]["properties"]
    assert rejection_rule["synthesis_eligible"]["const"] is False


def test_source_map_requires_offsets_lines_quotes_and_hashes() -> None:
    schema = load_json(SCHEMA_ROOT / SCHEMAS["source_map"][0])
    segment_required = set(schema["$defs"]["segment"]["required"])
    assert {
        "normalized_start_char",
        "normalized_end_char",
        "normalized_start_line",
        "normalized_end_line",
        "quote",
        "quote_sha256",
    } <= segment_required


def test_resolution_taxonomy_is_exact_and_distinguishes_conflicts() -> None:
    schema = load_json(SCHEMA_ROOT / SCHEMAS["resolution"][0])
    outcomes = set(schema["properties"]["outcome"]["enum"])
    assert outcomes == RESOLUTION_OUTCOMES
    assert "duplicate" in outcomes
    assert "contradiction" in outcomes
    assert "supersession" in outcomes
    assert "merge" not in outcomes

    serialized = json.dumps(schema, sort_keys=True)
    assert "supersession_basis" in serialized
    assert '"synthesis_eligible": {"const": false}' in serialized


def test_synthesis_proposals_are_evidence_bound_and_review_only() -> None:
    schema = load_json(SCHEMA_ROOT / SCHEMAS["proposal"][0])
    properties = schema["properties"]
    assert properties["resolution_ids"]["minItems"] == 1
    assert properties["evidence_refs"]["minItems"] == 1
    assert properties["review_status"]["const"] == "pending_human_review"
    for field in (
        "direct_apply_permitted",
        "canonical_write_permitted",
        "github_write_permitted",
        "production_write_permitted",
    ):
        assert properties[field]["const"] is False
    claim = schema["$defs"]["claim"]["properties"]
    assert claim["unsupported"]["const"] is False


def test_example_is_consistent_with_m11_2_reference_boundary() -> None:
    example = load_json(M11_ROOT / "examples" / "compiler-input-v1.example.json")
    assert example["schema_version"] == "knowledge-compiler-input/v1"
    assert example["snapshot_ref"]["connector_type"] == "local_file"
    assert example["snapshot_ref"]["connector_version"] == "local-file/1.0.0"
    assert example["derivative_ref"]["normalizer_id"] == "markdown"
    assert example["derivative_ref"]["normalizer_version"] == "1.0.0"
    assert example["admission_ref"]["status"] == "accepted_for_compilation"
    assert example["effective_policy"]["may_broaden"] is False
    assert example["canonical_source_ref"] is None
    assert example["compiler_identity"]["resolver_version"].startswith("disabled/")
    assert example["compiler_identity"]["synthesizer_version"].startswith("disabled/")


def test_architecture_documents_pin_reuse_and_mutation_boundaries() -> None:
    readme = (M11_ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (M11_ROOT / "compiler-architecture.md").read_text(encoding="utf-8")
    reuse = (M11_ROOT / "reuse-and-migration-map.md").read_text(encoding="utf-8")
    boundary = (M11_ROOT / "review-boundary.md").read_text(encoding="utf-8")
    strategy = (M11_ROOT / "test-strategy-and-acceptance.md").read_text(
        encoding="utf-8"
    )
    combined = "\n".join((readme, architecture, reuse, boundary, strategy))

    assert "M11.2" in combined
    assert "canonical source remains the only editable truth" in combined.lower()
    assert "canonical_json_bytes" in reuse
    assert "exact character-span" in reuse
    assert "issue #30 must remain open" in readme
    assert "channels/production.json" in combined
    assert "direct apply" in boundary.lower()
    assert "model confidence" in combined.lower()


def test_m11_1_production_baseline_is_pinned_and_unchanged_by_design() -> None:
    readme = (M11_ROOT / "README.md").read_text(encoding="utf-8")
    assert "20260708T040116Z-69a9f445699a" in readme
    assert "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb" in readme
    assert "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5" in readme
    assert "Production mutation: forbidden" in readme
