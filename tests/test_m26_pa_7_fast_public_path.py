from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine import m26_aq_semantic_contract as semantic_runtime
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
    skill_passage = (
        "In an AI agent architecture, a skill is a reusable method an agent follows "
        "for a class of task or capability."
    )
    evidence = {
        "evidence_id": "ev_skill",
        "locator_id": document["section_id"],
        "passage_text": skill_passage,
        "evidence_type": "passage",
        "text": skill_passage,
        "title": "AI Agent Skill Definition",
        "section_title": "Skill",
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
    lexical_result = {
        "backend_identity": {"backend": "lex"},
        "results": [{"section_id": document["section_id"]}],
    }
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

    monkeypatch.setattr(semantic_runtime, "load_production_answer_bundle", lambda: bundle)
    monkeypatch.setattr(
        runtime,
        "_run_lexical_primary_retrieval",
        lambda **_kwargs: (retrieval["lexical"], retrieval["dense"]),
    )
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
    assert (
        response["provider_routing"]["provider_attempts"][0]["call_class"]
        == "aq_fast_answer_synthesis"
    )
    assert response["semantic_closure"]["failures"] == []
    assert response["semantic_closure"]["canonical_fast_candidate"] == {
        "attempted": True,
        "accepted": True,
        "semantic_repair_invoked": False,
    }


def test_role_scope_drift_cannot_be_published_as_canonical_fast_answer(
    monkeypatch: pytest.MonkeyPatch,
    fast_path_bundle: tuple[Any, dict[str, Any], dict[str, Any]],
) -> None:
    bundle, evidence, retrieval = fast_path_bundle
    evidence = {
        **evidence,
        "passage_text": (
            "Early employees create leverage not by collecting titles, but by moving closer "
            "and closer to the company's actual bottlenecks. Strong operators turn fuzzy "
            "problems into work a team can understand, prioritise and ship."
        ),
        "text": (
            "Early employees create leverage not by collecting titles, but by moving closer "
            "and closer to the company's actual bottlenecks. Strong operators turn fuzzy "
            "problems into work a team can understand, prioritise and ship."
        ),
    }
    provider = FastAnswerProvider(
        answer_text=(
            "Founders should stop chasing titles and instead dive straight into the company's "
            "actual bottlenecks."
        ),
        citation_ids=["ev_skill"],
    )

    monkeypatch.setattr(semantic_runtime, "load_production_answer_bundle", lambda: bundle)
    monkeypatch.setattr(
        runtime,
        "_run_lexical_primary_retrieval",
        lambda **_kwargs: (retrieval["lexical"], retrieval["dense"]),
    )
    monkeypatch.setattr(runtime, "_select_evidence", lambda **_kwargs: [evidence])
    monkeypatch.setattr(runtime, "_has_meaningful_overlap", lambda _question, _evidence: True)

    response = runtime.run_owner_arbitrary_query(
        root=ROOT,
        gate=load_json(GATE_PATH),
        question="How can founders turn ambiguity into useful work quickly?",
        owner_subject_hash=OWNER_SUBJECT_HASH,
        provider_client=provider,
    )

    assert provider.call_classes == ["aq_fast_answer_synthesis"]
    assert response.get("answer_text") != provider.answer_text
    assert response["semantic_closure"]["canonical_fast_candidate"] == {
        "attempted": True,
        "accepted": False,
        "semantic_repair_invoked": True,
    }



def test_explicit_population_transfer_can_publish_as_one_call_fast_answer(
    monkeypatch: pytest.MonkeyPatch,
    fast_path_bundle: tuple[Any, dict[str, Any], dict[str, Any]],
) -> None:
    bundle, evidence, retrieval = fast_path_bundle
    passage = (
        "Early employees create leverage not by collecting titles, but by moving closer "
        "and closer to the company's actual bottlenecks. Strong operators turn fuzzy "
        "problems into work a team can understand, prioritise and ship."
    )
    evidence = {**evidence, "passage_text": passage, "text": passage}
    qualified = (
        "The source focuses on early employees rather than founders. A transferable lesson "
        "for founders is to move closer to the company's actual bottlenecks."
    )
    provider = FastAnswerProvider(answer_text=qualified, citation_ids=["ev_skill"])

    monkeypatch.setattr(semantic_runtime, "load_production_answer_bundle", lambda: bundle)
    monkeypatch.setattr(
        runtime,
        "_run_lexical_primary_retrieval",
        lambda **_kwargs: (retrieval["lexical"], retrieval["dense"]),
    )
    monkeypatch.setattr(runtime, "_select_evidence", lambda **_kwargs: [evidence])
    monkeypatch.setattr(runtime, "_has_meaningful_overlap", lambda _question, _evidence: True)

    response = runtime.run_owner_arbitrary_query(
        root=ROOT,
        gate=load_json(GATE_PATH),
        question="How can founders turn ambiguity into useful work quickly?",
        owner_subject_hash=OWNER_SUBJECT_HASH,
        provider_client=provider,
    )

    assert provider.call_classes == ["aq_fast_answer_synthesis"]
    assert response["status"] == "owner_only_cited_answer"
    assert response["answer_text"] == qualified
    assert response["semantic_closure"]["canonical_fast_candidate"]["accepted"] is True



@pytest.mark.parametrize(
    "provider_factory",
    [
        lambda: FastAnswerProvider(answer_text="Fine answer", citation_ids=["missing"]),
        lambda: LeakyProvider(
            answer_text="The definition head is hidden here.", citation_ids=["ev_skill"]
        ),
    ],
)
def test_invalid_fast_public_candidate_uses_bounded_semantic_retry_then_abstains(
    monkeypatch: pytest.MonkeyPatch,
    fast_path_bundle: tuple[Any, dict[str, Any], dict[str, Any]],
    provider_factory: Any,
) -> None:
    bundle, evidence, retrieval = fast_path_bundle
    provider = provider_factory()

    monkeypatch.setattr(semantic_runtime, "load_production_answer_bundle", lambda: bundle)
    monkeypatch.setattr(
        runtime,
        "_run_lexical_primary_retrieval",
        lambda **_kwargs: (retrieval["lexical"], retrieval["dense"]),
    )
    monkeypatch.setattr(runtime, "_select_evidence", lambda **_kwargs: [evidence])
    monkeypatch.setattr(runtime, "_has_meaningful_overlap", lambda _question, _evidence: True)

    response = runtime.run_owner_arbitrary_query(
        root=ROOT,
        gate=load_json(GATE_PATH),
        question="What is a skill in an AI agent architecture?",
        owner_subject_hash=OWNER_SUBJECT_HASH,
        provider_client=provider,
    )

    assert provider.calls == 3
    assert provider.call_classes == [
        "aq_fast_answer_synthesis",
        "aq_semantic_closure",
        "aq_semantic_closure_repair",
    ]
    assert response["status"] == "owner_only_safe_abstention"
    assert response["terminal_status"] == "safe_abstention"
    assert response["reason_codes"] == [
        "COMPACT_PROVIDER_PARSE_FAILED",
        "SEMANTIC_CLOSURE_FAILED",
    ]
    assert response["provider_call_count"] == 2
    assert response["citations"] == []
    assert response["semantic_closure"]["canonical_fast_candidate"] == {
        "attempted": True,
        "accepted": False,
        "semantic_repair_invoked": True,
    }


def test_fast_alignment_rejects_unqualified_population_role_substitution() -> None:
    question = "How can founders turn ambiguity into useful work quickly?"
    evidence = [
        {
            "passage_text": (
                "Early employees create leverage not by collecting titles, but by moving closer "
                "and closer to the company's actual bottlenecks. The strongest operators turn "
                "fuzzy problems into work a team can understand, prioritise and ship."
            )
        }
    ]
    failures = semantic_runtime._question_answer_alignment_failures(
        question=question,
        answer_text=(
            "Founders should stop chasing titles and instead dive straight into the company's "
            "real bottlenecks."
        ),
        evidence=evidence,
    )
    assert failures == ["QUESTION_ANSWER_ALIGNMENT_ROLE_SCOPE"]


def test_incident_20260925_exact_cited_section_rejects_founder_role_drift() -> None:
    question = "How can founders turn ambiguity into useful work quickly?"
    cited_section = (
        "The real leverage is not your title. It is how close you are to the company's core "
        "problems. Early employees create leverage not by collecting titles, but by moving "
        "closer and closer to the company's actual bottlenecks. Can you understand the product? "
        "The customer? The economic engine? Can you turn the fuzzy, cross-functional no-man's-land "
        "into something the company can actually scale? The work that changes your trajectory is "
        "often the work with cross-functional impact. So if someone asked me now what early "
        "startup employees should get good at, I would answer: become useful to the problems "
        "that actually matter."
    )
    live_answer = (
        "Founders should stop chasing titles and instead dive straight into the company's real "
        "bottlenecks. By getting close to the product, the customer and the economic engine, they "
        "can spot fuzzy cross-functional areas and turn those into concrete high-impact tasks."
    )

    failures = semantic_runtime._question_answer_alignment_failures(
        question=question,
        answer_text=live_answer,
        evidence=[{"passage_text": cited_section}],
    )

    assert failures == ["QUESTION_ANSWER_ALIGNMENT_ROLE_SCOPE"]



def test_fast_alignment_allows_explicitly_qualified_population_transfer() -> None:
    question = "How can founders turn ambiguity into useful work quickly?"
    evidence = [
        {
            "passage_text": (
                "Early employees create leverage not by collecting titles, but by moving closer "
                "and closer to the company's actual bottlenecks."
            )
        }
    ]
    failures = semantic_runtime._question_answer_alignment_failures(
        question=question,
        answer_text=(
            "The source focuses on early employees rather than founders. A transferable lesson "
            "for founders is to move closer to the company's actual bottlenecks."
        ),
        evidence=evidence,
    )
    assert failures == []


def test_fast_alignment_treats_customer_and_user_as_same_population_family() -> None:
    failures = semantic_runtime._question_answer_alignment_failures(
        question="How can customers reduce onboarding friction?",
        answer_text="Customers can reduce onboarding friction by clarifying the first workflow.",
        evidence=[
            {
                "passage_text": (
                    "Users can reduce onboarding friction by clarifying the first workflow and "
                    "removing unnecessary setup steps."
                )
            }
        ],
    )
    assert failures == []


def test_fast_synthesis_prompt_requires_population_role_scope_preservation() -> None:
    payload = runtime._fast_synthesis_payload(
        question="How can founders turn ambiguity into useful work quickly?",
        trace_id="trace-role-scope",
        intent_class="direct_grounded_knowledge",
        evidence=[
            {
                "evidence_id": "ev1",
                "evidence_type": "passage",
                "locator_id": "section1",
                "source_id": "source1",
                "source_identity": "source1",
                "section_id": "section1",
                "concept_id": "concept1",
                "passage_text": "Early employees turn fuzzy problems into useful work.",
                "channels": ["lexical"],
            }
        ],
    )
    system = str(payload["system"])
    assert "Preserve the population, actor, and role scope of the evidence" in system
    assert "transferable lesson or inference" in system


INCIDENT_SECTION = (
    "The real leverage is not your title. It is how close you are to the company's core "
    "problems. Early employees create leverage not by collecting titles, but by moving "
    "closer to the company's actual bottlenecks. Can you understand the product? "
    "The customer? The economic engine? Can you turn the fuzzy, cross-functional "
    "no-man's-land into something the company can actually scale? The work that changes "
    "your trajectory is often the work with cross-functional impact. So if someone asked "
    "me now what early startup employees should get good at, I would answer: become useful "
    "to the problems that actually matter."
)


def test_fast_sentence_support_rejects_adjacent_plausible_expansion() -> None:
    failures = semantic_runtime._fast_sentence_support_failures(
        answer_text=(
            "Early-stage employees should concentrate on finding and plugging the "
            "organization's gaps and bottlenecks rather than worrying about titles. "
            "By widening their own judgment, technical range, and operating scope as "
            "the business evolves, they grow with the company."
        ),
        evidence=[{"passage_text": INCIDENT_SECTION}],
    )
    assert failures == ["FAST_SENTENCE_SUPPORT_LOW_COVERAGE"]


def test_fast_sentence_support_accepts_tight_paraphrase_of_cited_passage() -> None:
    failures = semantic_runtime._fast_sentence_support_failures(
        answer_text=(
            "Early employees should focus less on titles and move closer to the company's "
            "actual bottlenecks, product, customers, and economic engine."
        ),
        evidence=[{"passage_text": INCIDENT_SECTION}],
    )
    assert failures == []


def test_fast_sentence_support_accepts_explicit_transfer_framing() -> None:
    failures = semantic_runtime._fast_sentence_support_failures(
        answer_text=(
            "The source focuses on early employees rather than founders. "
            "A transferable lesson for founders is to move closer to the company's "
            "actual bottlenecks."
        ),
        evidence=[
            {
                "passage_text": (
                    "Early employees create leverage not by collecting titles, but by moving "
                    "closer to the company's actual bottlenecks."
                )
            }
        ],
    )
    assert failures == []


def test_fast_synthesis_prompt_requires_sentence_level_evidence_discipline() -> None:
    payload = runtime._fast_synthesis_payload(
        question="What should early startup employees focus on instead of titles?",
        trace_id="trace-fast-grounding",
        intent_class="direct_grounded_knowledge",
        evidence=[
            {
                "evidence_id": "ev1",
                "evidence_type": "passage",
                "locator_id": "section1",
                "source_id": "source1",
                "source_identity": "source1",
                "section_id": "section1",
                "concept_id": "concept1",
                "passage_text": "Early employees should move closer to actual bottlenecks.",
                "channels": ["lexical"],
            }
        ],
    )
    system = str(payload["system"])
    assert (
        "Every material sentence must stay tightly within what the cited passage "
        "explicitly supports"
    ) in system
    assert "Prefer a shorter answer over an expanded answer" in system
