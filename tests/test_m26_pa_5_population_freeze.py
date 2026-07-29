from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from knowledge_engine.m26_pa5_population_freeze import (
    MANIFEST_SCHEMA_PATH,
    POPULATION_SCHEMA_PATH,
    STRATA,
    build_population,
    validate_files,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
DOCS = ROOT / "docs" / "architecture" / "m26"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-5-controlled-internal-pilot.yml"
PA4_WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-4-verified-answer-citation-gate.yml"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def validate_schema(value: dict[str, Any], schema_path: Path) -> None:
    schema = load(ROOT / schema_path)
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    assert errors == []


def test_pa5_frozen_population_schema_digest_and_manifest() -> None:
    population = load(PILOT / "m26-pa-5-frozen-population.json")
    manifest = load(PILOT / "m26-pa-5-population-manifest.json")
    validate_schema(population, POPULATION_SCHEMA_PATH)
    validate_schema(manifest, MANIFEST_SCHEMA_PATH)
    summary = validate_files(ROOT)
    assert summary == manifest["validation"]
    assert manifest["population_count"] == 200
    assert manifest["population_sha256"] == population["population_sha256"]
    assert manifest["population_sha256"] == population["self_sha256"]


def test_pa5_frozen_population_is_reproducible_from_accepted_corpus() -> None:
    committed = load(PILOT / "m26-pa-5-frozen-population.json")
    rebuilt = build_population(ROOT)
    assert rebuilt == committed
    assert committed["source_corpus_identity"]["accepted_local_release_ready"] is True
    assert (
        committed["source_corpus_identity"]["m26_production_identity_reference"][
            "release_id"
        ]
        == "m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043"
    )


def test_pa5_frozen_population_counts_and_ids_are_strict() -> None:
    population = load(PILOT / "m26-pa-5-frozen-population.json")
    questions = population["questions"]
    assert len(questions) == 200
    assert Counter(item["stratum"] for item in questions) == STRATA
    assert len({item["question_id"] for item in questions}) == 200
    assert len({item["question"] for item in questions}) == 200
    assert population["duplicate_count"] == 0


def test_pa5_frozen_population_questions_are_not_placeholders_or_answers() -> None:
    population = load(PILOT / "m26-pa-5-frozen-population.json")
    forbidden = (
        "<COUNT_200_TO_500>",
        "<SHA256>",
        "placeholder",
        "lorem ipsum",
        "raw_provider_response",
        "synthetic_provider_receipt",
    )
    for item in population["questions"]:
        assert all(term.lower() not in item["question"].lower() for term in forbidden)
        assert len(item["question"].split()) >= 10
        expected = item["expected_evidence_family"]
        abstention = item["abstention_class"]
        assert (expected is None) != (abstention is None)
        assert set(item["construction_source_identity"]) >= {
            "artifact_kind",
            "artifact_path",
            "artifact_sha256",
            "release_id",
            "source_repository",
            "source_commit_sha",
            "foundation_repository",
            "foundation_commit_sha",
        }


def test_pa5_population_freeze_preserves_non_live_boundary() -> None:
    population = load(PILOT / "m26-pa-5-frozen-population.json")
    boundary = population["authority_boundary"]
    assert boundary == {
        "answer_generation": False,
        "foundation_mutation": False,
        "non_live_read_only_preparation": True,
        "production_pointer_mutation": False,
        "provider_calls": 0,
        "public_traffic": False,
        "qdrant_write": False,
        "r2_write": False,
        "release_mutation": False,
        "review_execution": False,
        "source_mutation": False,
    }
    assert population["leakage_checks"] == {
        "raw_corpus_body_persisted": False,
        "raw_provider_response_persisted": False,
        "secret_values_persisted": False,
        "synthetic_provider_receipt_present": False,
        "vectors_persisted": False,
    }


def test_pa5_population_freeze_doc_and_workflows_are_read_only() -> None:
    doc = (DOCS / "m26-pa-5-controlled-internal-pilot.md").read_text(encoding="utf-8")
    assert "Population Freeze Preparation" in doc
    assert "does not execute PA.5 provider calls" in doc
    assert "m26-pa-5-frozen-population.json" in doc

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "static-authorization:\n    if: github.event_name == 'pull_request'" in workflow
    assert "m26_pa5_population_freeze" in workflow
    assert "m26-pa-5-frozen-population.json" in workflow

    pa4_workflow = PA4_WORKFLOW.read_text(encoding="utf-8")
    assert "m26-pa-5-frozen-population.json" in pa4_workflow
    assert "live-verified-answer:" in pa4_workflow
