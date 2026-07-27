from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.m25_formal_closure import (
    VALID_OUTCOMES,
    M25FormalClosureError,
    load_json,
    self_digest,
    validate_repository,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "pilot" / "m25" / "m25-10-formal-closure-evidence.json"


def test_m25_formal_closure_evidence_validates() -> None:
    result = validate_repository(ROOT)
    assert result == {
        "status": "m25_formal_closure_evidence_valid",
        "release_id": "m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043",
        "stage_count": 10,
        "protected_mutation_count": 13,
        "decision_required": False,
    }


def test_m25_formal_closure_evidence_self_digest_is_stable() -> None:
    evidence = load_json(EVIDENCE)
    assert evidence["self_sha256"] == self_digest(evidence)
    assert evidence["status"] == "m25_closed"
    assert evidence["owner_decision"]["outcome"] == "approved_bounded_large_scale_ingestion"
    assert evidence["decision_gate"]["selected_outcome"] == "approved_bounded_large_scale_ingestion"


def test_m25_formal_closure_records_owner_decision_and_acceptance() -> None:
    evidence = load_json(EVIDENCE)
    owner = load_json(ROOT / "pilot" / "m25" / "m25-10-owner-decision.json")
    acceptance = load_json(ROOT / "pilot" / "m25" / "m25-10-final-acceptance.json")
    assert owner["outcome"] == "approved_bounded_large_scale_ingestion"
    assert owner["status"] == "owner_decision_recorded"
    assert owner["decided_at_utc"] == "2026-07-27T03:36:26Z"
    assert owner["self_sha256"] == self_digest(owner)
    assert acceptance["status"] == "m25_closed"
    assert acceptance["finality"]["m25_closed"] is True
    assert acceptance["self_sha256"] == self_digest(acceptance)
    assert evidence["status"] == "m25_closed"
    assert evidence["decision_gate"]["decision_required"] is False
    assert set(evidence["decision_gate"]["valid_outcomes"]) == VALID_OUTCOMES
    assert evidence["decision_gate"]["selected_outcome"] == "approved_bounded_large_scale_ingestion"
    assert evidence["owner_decision"]["path"] == "pilot/m25/m25-10-owner-decision.json"
    assert evidence["final_acceptance"]["path"] == "pilot/m25/m25-10-final-acceptance.json"


def test_m25_formal_closure_protected_mutations_are_all_denied() -> None:
    evidence = load_json(EVIDENCE)
    assert all(value is False for value in evidence["protected_mutations"].values())
    assert evidence["production_identities"]["production_pointer_sha256"] == (
        "4a2cf8cc16d598cc2c6928491cf2c3b926e57e571297c61a8c3ff7a4ae396ff9"
    )
    assert evidence["production_identities"]["production_manifest_sha256"] == (
        "72bb03e3fa22e453735719ab43898adfd4c7f186f818ed71685efb4fcd87de2b"
    )


def test_m25_formal_closure_denominator_is_complete() -> None:
    evidence = load_json(EVIDENCE)
    chain = evidence["evidence_chain"]
    assert {row["stage"] for row in chain} == {f"M25.{index}" for index in range(1, 11)}
    denominator = evidence["denominator_accounting"]
    assert denominator["admitted_blog_corpus"]["documents"] == 156
    assert denominator["admitted_blog_corpus"]["semantic_documents"] == 4197
    assert denominator["unaccounted_sources"] == 0


def test_m25_formal_closure_records_m26_forward_caveat() -> None:
    evidence = load_json(EVIDENCE)
    m26 = evidence["m26_forward_state"]
    assert m26["current_main_sha"] == "e88b50cb8f0084a6ec1ea1d9aadc9af7bce54bf6"
    assert m26["drift_classification"] == (
        "harmless_forward_commits_with_successor_caveat"
    )
    assert "M25 final closure remains separately required" in m26["m26_caveat"]


def test_m25_formal_closure_tampering_fails_closed(tmp_path: Path) -> None:
    evidence = load_json(EVIDENCE)
    evidence["protected_mutations"]["public_traffic"] = True
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
    with pytest.raises(M25FormalClosureError, match="self digest mismatch"):
        from knowledge_engine.m25_formal_closure import validate_closure_evidence

        validate_closure_evidence(tampered)
