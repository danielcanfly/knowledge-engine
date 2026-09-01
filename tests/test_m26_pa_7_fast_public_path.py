from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from knowledge_engine import m26_pa7_arbitrary_query_runtime as runtime
from knowledge_engine.m26_production_promotion_closure import load_json
from knowledge_engine.m26_verified_answer_citation_gate import canonical_sha256
from m26_answer_bundle_fixture import synthetic_full_production_answer_bundle

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "pilot" / "m26" / "m26-pa-7-resolved-production-gate.json"
OWNER_SUBJECT_HASH = "93c8aaae82e498dc2e6bfdcaa48b8823fe21a5ceef44ca2cf9cf35cf6350e05b"


@pytest.fixture()
def fast_path_bundle() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    bundle = synthetic_full_production_answer_bundle()
    document = bundle.lexical_index["documents"][0]
    record = bundle.provenance["records"][0]
    evidence = {
        "evidence_id": "ev_skill",
        "locator_id": document["section_id"],
        "passage_text": document["body"],
        "evidence_type": "passage",
        "text": document["body"],
        "title": document["title"],
        "section_title": document["section_title"],
        "source_id": document["source_id"],
        "source_identity": document["source_id"],
        "concept_id": document["concept_id"],
        "section_id": document["section_id"],
        "artifact_key": bundle.artifact_keys["lexical_index"],
        "artifact_sha256": bundle.artifact_sha256["lexical_index"],
        "release_id": bundle.release_id,
        "passage_text_sha256": canonical_sha256(document["body"]),
        "provenance_record_sha256": canonical_sha256(record),
        "retrieval_metadata": {"relation_types": []},
        "channels": ["lexical"],
    }
    lexical_result = {"backend_identity": {"backend": "lex"}, "results": [{"section_id": document["section_id"]}]}
    dense_result = {"backend_identity": {"backend": "dense"}, "candidates": []}
    return bundle, evidence, {"lexical": lexical_result, "dense": dense_result}


class FastAnswerProvider:
    def __init__(self, *, answer_text: str, citation_ids: list[str]) -> None:
        self.answer_text = answer_text
        self.citation_ids = citation_ids
        self.calls = 0
        self.payloads: list[dict[str, Any]] = []
        self.call_classes: list[str] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls += 1
        self.payloads.append(payload)
        self.call_classes.append(call_class)
        return {
            "text": json.dumps(
                {
                    "status": "answer",
                    "answer_text": self.answer_text,
                    "citation_ids": self.citation_ids,
                    "abstention_reason": None,
                }
            ),
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "cost_usd": "0.00001",
            "latency_ms": 5,
            "response_id": f"fast-{self.calls}",
            "call_class": call_class,
        }


class LeakyProvider(FastAnswerProvider):
    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls += 1
        self.payloads.append(payload)
        self.call_classes.append(call_class)
        return {
            "text": json.dumps(
                {
                    "status": "answer",
                    "answer_text": "The definition head is hidden here.",
                    "citation_ids": self.citation_ids,
                    "abstention_reason": None,
                }
            ),
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "cost_usd": "0.00001",
            "latency_ms": 5,
            "response_id": f"leaky-{self.calls}",
            "call_class": call_class,
        }


def test_fast_public_path_publishes_single_call_answer(
    monkeypatch: pytest.MonkeyPatch,
    fast_path_bundle: tuple[Any, dict[str, Any], dict[str, Any]],
) -> None:
    bundle, evidence, retrieval = fast_path_bundle
    provider = FastAnswerProvider(
        answer_text="A skill is a method an agent follows for a class of task.",
        citation_ids=["ev_skill"],
    )

    monkeypatch.setattr(runtime, "load_production_answer_bundle", lambda: bundle)
    monkeypatch.setattr(runtime, "_run_lexical_primary_retrieval", lambda **_kwargs: (retrieval["lexical"], retrieval["dense"]))
    monkeypatch.setattr(runtime, "_select_evidence", lambda **_kwargs: [evidence])
    monkeypatch.setattr(runtime, "_has_meaningful_overlap", lambda _question, _evidence: True)

    response = runtime.run_owner_arbitrary_query(
        root=ROOT,
        gate=load_json(GATE_PATH),
        question="What is a skill in an AI agent architecture?",
        owner_subject_hash=OWNER_SUBJECT_HASH,
        provider_client=provider,
    )

    assert provider.calls == 1
    assert response["status"] == "owner_only_cited_answer"
    assert response["terminal_status"] == "fast_answer_ready"
    assert response["provider_call_count"] == 1
    assert response["answer_source"] == "fast_natural_cited_synthesis"
    assert response["answer_text"] == "A skill is a method an agent follows for a class of task."
    assert response["citations"][0]["citation_id"] == "claim_1_ref_1"
    assert response["answer_claims"][0]["citation_ids"] == ["claim_1_ref_1"]
    assert response["provider_routing"]["provider_attempts"][0]["call_class"] == "aq_fast_answer_synthesis"
    assert response["semantic_closure"] == {}


@pytest.mark.parametrize(
    ("provider_factory", "expected_reason"),
    [
        (lambda: FastAnswerProvider(answer_text="Fine answer", citation_ids=["missing"]), "PROVIDER_OUTPUT_INVALID"),
        (lambda: LeakyProvider(answer_text="The definition head is hidden here.", citation_ids=["ev_skill"]), "PROVIDER_OUTPUT_INVALID"),
    ],
)
def test_fast_public_path_abstains_without_semantic_retry(
    monkeypatch: pytest.MonkeyPatch,
    fast_path_bundle: tuple[Any, dict[str, Any], dict[str, Any]],
    provider_factory: Any,
    expected_reason: str,
) -> None:
    bundle, evidence, retrieval = fast_path_bundle
    provider = provider_factory()

    monkeypatch.setattr(runtime, "load_production_answer_bundle", lambda: bundle)
    monkeypatch.setattr(runtime, "_run_lexical_primary_retrieval", lambda **_kwargs: (retrieval["lexical"], retrieval["dense"]))
    monkeypatch.setattr(runtime, "_select_evidence", lambda **_kwargs: [evidence])
    monkeypatch.setattr(runtime, "_has_meaningful_overlap", lambda _question, _evidence: True)

    response = runtime.run_owner_arbitrary_query(
        root=ROOT,
        gate=load_json(GATE_PATH),
        question="What is a skill in an AI agent architecture?",
        owner_subject_hash=OWNER_SUBJECT_HASH,
        provider_client=provider,
    )

    assert provider.calls == 1
    assert response["status"] == "owner_only_safe_abstention"
    assert response["terminal_status"] == "safe_abstention"
    assert response["reason_codes"] == [expected_reason]
    assert response["provider_call_count"] == 1
    assert response["citations"] == []
    assert response["semantic_closure"] == {}
