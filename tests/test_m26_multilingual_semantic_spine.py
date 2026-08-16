from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy
from knowledge_engine.m26_aq_semantic_contract import (
    CONTRACT_SCHEMA_VERSION,
    derive_semantic_requirements,
    semantic_contract_fingerprint,
)
from knowledge_engine.m26_multilingual_language_envelope import LanguageEnvelope
from knowledge_engine.m26_multilingual_semantic_spine import (
    SemanticAuthorityDependencies,
    build_canonical_semantic_context,
)


@dataclass(frozen=True)
class FakeRequirement:
    requirement_id: str
    exact_phrase: str = ""


class RecordingAuthorities:
    def __init__(self) -> None:
        self.intent_questions: list[str] = []
        self.requirement_questions: list[tuple[str, str]] = []
        self.contract_questions: list[tuple[str, str]] = []

    def intent(self, question: str) -> str:
        self.intent_questions.append(question)
        if "edge" in question.casefold() or "relationship" in question.casefold():
            return "graph_relationship"
        return "direct_grounded_knowledge"

    def requirements(self, question: str, intent_class: str) -> list[FakeRequirement]:
        self.requirement_questions.append((question, intent_class))
        return [
            FakeRequirement("entity_router", "router"),
            FakeRequirement("semantic_boundary"),
        ]

    def question_contract(self, *, question: str, intent_class: str) -> dict[str, Any]:
        self.contract_questions.append((question, intent_class))
        return {"required_facets": [{"facet_id": "direct_answer", "required": True}]}

    def fingerprint(self) -> str:
        return "semantic-fingerprint-fixture"

    def dependencies(self) -> SemanticAuthorityDependencies:
        return SemanticAuthorityDependencies(
            intent_classifier=self.intent,
            question_contract_builder=self.question_contract,
            requirement_deriver=self.requirements,
            contract_fingerprint_provider=self.fingerprint,
            contract_schema_version="fixture-semantic-schema/v1",
        )


def envelope(
    *,
    original: str,
    canonical: str,
    detected: str,
    status: str = "ok",
) -> LanguageEnvelope:
    return LanguageEnvelope(
        original_question=original,
        canonical_question_en=canonical,
        requested_answer_language="en" if detected == "en" else "zh-TW",
        detected_input_language=detected,
        canonicalization_applied=detected != "en",
        canonicalization_status=status,
        failure_code="" if status == "ok" else "CANONICALIZATION_SEMANTIC_LOSS",
    )


def test_english_semantic_and_closure_questions_are_exact_original_input() -> None:
    authorities = RecordingAuthorities()
    original = "  How   does the router\nchoose an execution path?  "

    result = build_canonical_semantic_context(
        envelope(
            original=original,
            canonical="A different canonical string must not be used for English.",
            detected="en",
        ),
        authorities=authorities.dependencies(),
    )

    assert result.ok is True
    assert result.context is not None
    assert result.context.semantic_question_en == original
    assert result.context.closure_question_en == original
    assert result.context.semantic_question_source == "original"
    assert authorities.intent_questions == [original]


def test_zh_tw_semantic_question_is_canonical_english_and_original_is_preserved() -> None:
    authorities = RecordingAuthorities()
    original = "Router 如何保留 API-42？"
    canonical = "How does the router preserve API-42?"

    result = build_canonical_semantic_context(
        envelope(original=original, canonical=canonical, detected="zh-TW"),
        authorities=authorities.dependencies(),
    )

    assert result.ok is True
    assert result.context is not None
    assert result.context.semantic_question_en == canonical
    assert result.context.closure_question_en == canonical
    assert result.context.original_question == original
    assert result.context.semantic_question_source == "canonical_en"
    assert authorities.intent_questions == [canonical]


def test_mixed_semantic_question_is_canonical_english() -> None:
    authorities = RecordingAuthorities()
    canonical = "Which graph edge preserves the Node-A to Node-B relationship?"

    result = build_canonical_semantic_context(
        envelope(
            original="Node-A 到 Node-B 的 graph relationship 是什麼？",
            canonical=canonical,
            detected="mixed",
        ),
        authorities=authorities.dependencies(),
    )

    assert result.ok is True
    assert result.context is not None
    assert result.context.intent_class == "graph_relationship"
    assert result.context.semantic_question_en == canonical
    assert authorities.intent_questions == [canonical]
    assert authorities.requirement_questions == [(canonical, "graph_relationship")]


def test_original_chinese_text_is_never_passed_to_english_intent_classifier() -> None:
    authorities = RecordingAuthorities()
    original = "這段中文對英文 classifier 沒有意義。"
    canonical = "How does the router choose an execution path?"

    result = build_canonical_semantic_context(
        envelope(original=original, canonical=canonical, detected="zh-TW"),
        authorities=authorities.dependencies(),
    )

    assert result.ok is True
    assert authorities.intent_questions == [canonical]
    assert original not in authorities.intent_questions
    assert result.context is not None
    assert result.context.telemetry["semantic_question_source"] == "canonical_en"


def test_failed_language_envelope_does_not_reach_semantic_authority() -> None:
    authorities = RecordingAuthorities()

    result = build_canonical_semantic_context(
        envelope(
            original="Router 如何保留 API-42？",
            canonical="How does the router preserve API-42?",
            detected="mixed",
            status="failed",
        ),
        authorities=authorities.dependencies(),
    )

    assert result.ok is False
    assert result.failure_code == "LANGUAGE_ENVELOPE_INVALID"
    assert authorities.intent_questions == []


def test_missing_canonical_english_for_non_english_fails_closed() -> None:
    authorities = RecordingAuthorities()

    result = build_canonical_semantic_context(
        envelope(original="Router 如何保留 API-42？", canonical="", detected="mixed"),
        authorities=authorities.dependencies(),
    )

    assert result.ok is False
    assert result.failure_code == "CANONICAL_ENGLISH_SEMANTIC_QUESTION_REQUIRED"
    assert authorities.intent_questions == []


def test_intent_and_requirement_authorities_receive_expected_questions() -> None:
    authorities = RecordingAuthorities()
    english = "How should router and replanner responsibilities stay distinct?"
    original = "router 和 replanner 的責任如何保持不同？"

    result = build_canonical_semantic_context(
        envelope(original=original, canonical=english, detected="mixed"),
        authorities=authorities.dependencies(),
    )

    assert result.ok is True
    assert authorities.intent_questions == [english]
    assert authorities.requirement_questions == [(english, "direct_grounded_knowledge")]
    assert result.context is not None
    assert result.context.semantic_requirement_ids == (
        "entity_router",
        "semantic_boundary",
    )


def test_question_contract_and_future_closure_question_use_canonical_english() -> None:
    authorities = RecordingAuthorities()
    canonical = "Which edge says Node-A precedes Node-B?"

    result = build_canonical_semantic_context(
        envelope(
            original="Node-A precedes Node-B 嗎？",
            canonical=canonical,
            detected="mixed",
        ),
        authorities=authorities.dependencies(),
    )

    assert result.ok is True
    assert result.context is not None
    assert result.context.closure_question_en == canonical
    assert authorities.contract_questions == [(canonical, "graph_relationship")]
    assert result.context.question_contract_facet_ids == ("direct_answer",)


def test_empty_requirement_result_is_retained_without_track2_invention() -> None:
    authorities = RecordingAuthorities()

    def empty_requirements(question: str, intent_class: str) -> list[FakeRequirement]:
        authorities.requirement_questions.append((question, intent_class))
        return []

    deps = SemanticAuthorityDependencies(
        intent_classifier=authorities.intent,
        question_contract_builder=authorities.question_contract,
        requirement_deriver=empty_requirements,
        contract_fingerprint_provider=authorities.fingerprint,
    )

    result = build_canonical_semantic_context(
        envelope(
            original="Router 如何工作？",
            canonical="How does the router work?",
            detected="mixed",
        ),
        authorities=deps,
    )

    assert result.ok is True
    assert result.context is not None
    assert result.context.semantic_requirement_ids == ()


def test_semantic_authority_exception_becomes_explicit_failure() -> None:
    def broken_intent(question: str) -> str:
        del question
        raise RuntimeError("fixture authority unavailable")

    result = build_canonical_semantic_context(
        envelope(
            original="Router 如何工作？",
            canonical="How does the router work?",
            detected="mixed",
        ),
        authorities=SemanticAuthorityDependencies(intent_classifier=broken_intent),
    )

    assert result.ok is False
    assert result.failure_code == "SEMANTIC_AUTHORITY_EXCEPTION"


def test_invalid_intent_output_fails_explicitly() -> None:
    result = build_canonical_semantic_context(
        envelope(
            original="Router 如何工作？",
            canonical="How does the router work?",
            detected="mixed",
        ),
        authorities=SemanticAuthorityDependencies(intent_classifier=lambda question: ""),
    )

    assert result.ok is False
    assert result.failure_code == "SEMANTIC_INTENT_INVALID"


def test_malformed_requirement_output_fails_explicitly() -> None:
    result = build_canonical_semantic_context(
        envelope(
            original="Router 如何工作？",
            canonical="How does the router work?",
            detected="mixed",
        ),
        authorities=SemanticAuthorityDependencies(
            requirement_deriver=lambda question, intent: None  # type: ignore[arg-type,return-value]
        ),
    )

    assert result.ok is False
    assert result.failure_code == "SEMANTIC_REQUIREMENTS_INVALID"


def test_requirement_without_id_fails_explicitly() -> None:
    result = build_canonical_semantic_context(
        envelope(
            original="Router 如何工作？",
            canonical="How does the router work?",
            detected="mixed",
        ),
        authorities=SemanticAuthorityDependencies(
            requirement_deriver=lambda question, intent: [FakeRequirement("")]
        ),
    )

    assert result.ok is False
    assert result.failure_code == "SEMANTIC_REQUIREMENTS_INVALID"


def test_malformed_question_contract_fails_explicitly() -> None:
    result = build_canonical_semantic_context(
        envelope(
            original="Router 如何工作？",
            canonical="How does the router work?",
            detected="mixed",
        ),
        authorities=SemanticAuthorityDependencies(
            question_contract_builder=lambda **kwargs: {"required_facets": [object()]}
        ),
    )

    assert result.ok is False
    assert result.failure_code == "SEMANTIC_QUESTION_CONTRACT_INVALID"


def test_missing_semantic_authority_dependency_fails_explicitly() -> None:
    result = build_canonical_semantic_context(
        envelope(
            original="Router 如何工作？",
            canonical="How does the router work?",
            detected="mixed",
        ),
        authorities=SemanticAuthorityDependencies(intent_classifier=None),
    )

    assert result.ok is False
    assert result.failure_code == "SEMANTIC_AUTHORITY_UNAVAILABLE"


def test_contract_metadata_and_telemetry_are_retained() -> None:
    authorities = RecordingAuthorities()

    result = build_canonical_semantic_context(
        envelope(
            original="Router 如何工作？",
            canonical="How does the router work?",
            detected="mixed",
        ),
        authorities=authorities.dependencies(),
    )

    assert result.ok is True
    assert result.context is not None
    assert result.context.semantic_contract_schema == "fixture-semantic-schema/v1"
    assert result.context.semantic_contract_fingerprint == "semantic-fingerprint-fixture"
    assert result.context.canonicalization_status_reference == "ok"
    assert result.context.telemetry["canonical_question_used"] is True
    assert result.context.telemetry["original_question_retained"] is True


def test_product_code_contains_no_multilingual_intent_keyword_rules() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/knowledge_engine/m26_multilingual_semantic_spine.py").read_text(
        encoding="utf-8"
    )

    for forbidden in ("Q01", "Q03", "Q04", "Q06", "Q08", "差別", "benchmark", "R3"):
        assert forbidden not in source
    assert 'if "' not in source
    assert "evaluate_visible_semantics" not in source


def test_actual_authority_english_and_zh_tw_canonical_intent_parity() -> None:
    question = (
        "What is the difference between a production router and an adaptive replanner "
        "when a route changes after execution starts?"
    )

    english = build_canonical_semantic_context(
        envelope(original=question, canonical=question, detected="en")
    )
    translated = build_canonical_semantic_context(
        envelope(original="請用繁體中文回答。", canonical=question, detected="zh-TW")
    )

    assert english.ok is True
    assert translated.ok is True
    assert english.context is not None
    assert translated.context is not None
    assert english.context.intent_class == translated.context.intent_class
    assert english.context.semantic_question_source == "original"
    assert translated.context.semantic_question_source == "canonical_en"


def test_actual_authority_english_and_mixed_canonical_intent_parity() -> None:
    question = "Which graph edge says Node-A precedes Node-B?"

    english = build_canonical_semantic_context(
        envelope(original=question, canonical=question, detected="en")
    )
    mixed = build_canonical_semantic_context(
        envelope(
            original="Node-A 到 Node-B 的 graph edge 是什麼？",
            canonical=question,
            detected="mixed",
        )
    )

    assert english.ok is True
    assert mixed.ok is True
    assert english.context is not None
    assert mixed.context is not None
    assert english.context.intent_class == mixed.context.intent_class


def test_actual_authority_requirement_ids_and_contract_fingerprint_parity() -> None:
    questions = (
        (
            "Which graph edge says Node-A precedes Node-B, and what relation "
            "direction does that preserve?"
        ),
        (
            "How should admission, durable state, completion verification, "
            "and observability work together in a controlled lifecycle?"
        ),
        (
            "Does Part 1 preceding Part 2 prove that Part 2 causes Part 1? "
            "Do not infer unsupported causality."
        ),
        "How does LangGraph API-42 preserve Cloudflare Workers AI state across 2 steps?",
    )

    for question in questions:
        english = build_canonical_semantic_context(
            envelope(original=question, canonical=question, detected="en")
        )
        multilingual = build_canonical_semantic_context(
            envelope(original="原始問題保留供稽核。", canonical=question, detected="zh-TW")
        )

        assert english.ok is True
        assert multilingual.ok is True
        assert english.context is not None
        assert multilingual.context is not None
        assert english.context.semantic_requirement_ids == (
            multilingual.context.semantic_requirement_ids
        )
        assert english.context.semantic_contract_fingerprint == (
            multilingual.context.semantic_contract_fingerprint
        )
        assert english.context.semantic_contract_schema == CONTRACT_SCHEMA_VERSION
        assert english.context.semantic_contract_fingerprint == semantic_contract_fingerprint()


def test_actual_authority_matches_direct_frozen_calls_for_generalized_question() -> None:
    question = (
        "What is the difference between a production router and an adaptive replanner "
        "when a route changes after execution starts?"
    )

    result = build_canonical_semantic_context(
        envelope(original="請比較 router 與 replanner。", canonical=question, detected="mixed")
    )

    assert result.ok is True
    assert result.context is not None
    expected_intent = legacy._intent_class(question)
    expected_requirements = derive_semantic_requirements(question, expected_intent)
    assert result.context.intent_class == expected_intent
    assert result.context.semantic_requirement_ids == tuple(
        requirement.requirement_id for requirement in expected_requirements
    )
