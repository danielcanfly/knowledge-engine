from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine.m26_multilingual_canonicalization import (
    CANONICALIZATION_SCHEMA_VERSION,
    REQUIRED_SEMANTIC_FIDELITY_DIMENSIONS,
    CanonicalizationRequest,
    CanonicalizationResult,
    SemanticFidelityContract,
    bounded_canonicalization_request,
    extract_preservation_markers,
    validate_canonicalization_result,
)
from knowledge_engine.m26_multilingual_language_envelope import (
    build_language_envelope,
    detect_input_language,
)

_DEFAULT_FIDELITY = object()


def complete_fidelity(**overrides: str) -> SemanticFidelityContract:
    values = {
        dimension: "preserved"
        for dimension in REQUIRED_SEMANTIC_FIDELITY_DIMENSIONS
    }
    values.update(overrides)
    return SemanticFidelityContract(**values)


class FakeCanonicalizer:
    def __init__(
        self,
        canonical: str = "What is the supported canonical question?",
        *,
        semantic_fidelity: object = _DEFAULT_FIDELITY,
        telemetry: dict[str, object] | None = None,
    ) -> None:
        self.canonical = canonical
        self.semantic_fidelity = (
            complete_fidelity()
            if semantic_fidelity is _DEFAULT_FIDELITY
            else semantic_fidelity
        )
        self.telemetry = telemetry or {"fake": True}
        self.calls: list[CanonicalizationRequest] = []

    def canonicalize(self, request: CanonicalizationRequest) -> CanonicalizationResult:
        self.calls.append(request)
        return CanonicalizationResult(
            canonical_question_en=self.canonical,
            status="ok",
            telemetry=self.telemetry,
            semantic_fidelity=self.semantic_fidelity,
        )


class FailingCanonicalizer:
    def canonicalize(self, request: CanonicalizationRequest) -> CanonicalizationResult:
        del request
        return CanonicalizationResult(
            canonical_question_en="",
            status="failed",
            failure_code="CANONICALIZER_UNAVAILABLE",
            failure_detail="deterministic test failure",
        )


def test_plain_english_passes_through_without_provider_call() -> None:
    provider = FakeCanonicalizer("Should not be used")
    envelope = build_language_envelope(
        "How does the router choose a path?",
        canonicalization_provider=provider,
    )

    assert envelope.original_question == "How does the router choose a path?"
    assert envelope.canonical_question_en == "How does the router choose a path?"
    assert envelope.requested_answer_language == "en"
    assert envelope.detected_input_language == "en"
    assert envelope.canonicalization_applied is False
    assert envelope.canonicalization_status == "ok"
    assert provider.calls == []


def test_plain_english_preserves_exact_input_without_provider_call() -> None:
    provider = FakeCanonicalizer("Should not be used")
    original = "  How   does the router\nchoose a path?  "

    envelope = build_language_envelope(original, canonicalization_provider=provider)

    assert envelope.original_question == original
    assert envelope.canonical_question_en == original
    assert envelope.requested_answer_language == "en"
    assert envelope.detected_input_language == "en"
    assert envelope.canonicalization_applied is False
    assert provider.calls == []


def test_traditional_chinese_input_uses_canonicalizer_and_requests_zh_tw() -> None:
    provider = FakeCanonicalizer("How does LangGraph preserve API-42 state across 2 steps?")
    original = "LangGraph 如何在 2 個 steps 中保留 API-42 狀態？"

    envelope = build_language_envelope(original, canonicalization_provider=provider)

    assert envelope.original_question == original
    assert envelope.canonical_question_en == (
        "How does LangGraph preserve API-42 state across 2 steps?"
    )
    assert envelope.requested_answer_language == "zh-TW"
    assert envelope.detected_input_language == "mixed"
    assert envelope.canonicalization_applied is True
    assert envelope.ok is True
    assert provider.calls[0].original_question == original


def test_all_applicable_semantic_dimensions_preserved_are_accepted() -> None:
    provider = FakeCanonicalizer(
        "Do not treat Part 2 as preceding Part 1; compare router and replanner, "
        "and explain how they should work together when evidence is insufficient.",
        semantic_fidelity=complete_fidelity(),
    )
    original = (
        "不要把 Part 2 說成 precedes Part 1；請比較 router 和 replanner，"
        "並說明 evidence 不足時它們應該如何一起工作。"
    )

    envelope = build_language_envelope(original, canonicalization_provider=provider)

    assert envelope.ok is True
    assert envelope.canonicalization_status == "ok"
    assert len(provider.calls) == 1


def test_not_applicable_semantic_dimensions_are_accepted() -> None:
    provider = FakeCanonicalizer(
        "What does API-42 do in 2 steps?",
        semantic_fidelity=complete_fidelity(
            comparison_direction="not_applicable",
            relationship_direction="not_applicable",
            negation="not_applicable",
            modality_qualifiers="not_applicable",
            multi_part_synthesis="not_applicable",
            graph_entity_references="not_applicable",
        ),
    )

    envelope = build_language_envelope(
        "API-42 在 2 個 steps 中做什麼？",
        canonicalization_provider=provider,
    )

    assert envelope.ok is True
    assert envelope.failure_code == ""


def test_natural_mixed_input_defaults_to_zh_tw() -> None:
    provider = FakeCanonicalizer(
        "When comparing the router and replanner, which handles DAG-7 first?"
    )
    envelope = build_language_envelope(
        "Router 和 replanner 比較時，哪個先處理 DAG-7？",
        canonicalization_provider=provider,
    )

    assert envelope.detected_input_language == "mixed"
    assert envelope.requested_answer_language == "zh-TW"
    assert envelope.canonicalization_applied is True
    assert "DAG-7" in envelope.canonical_question_en


def test_explicit_english_answer_language_override_is_internal_only() -> None:
    provider = FakeCanonicalizer("What does the MCP Server do?")
    envelope = build_language_envelope(
        "MCP Server 做什麼？",
        answer_language="en",
        canonicalization_provider=provider,
    )

    assert envelope.requested_answer_language == "en"
    assert envelope.detected_input_language == "mixed"
    assert envelope.canonicalization_applied is True


def test_preservation_markers_cover_names_models_acronyms_ids_numbers_urls_and_code() -> None:
    question = (
        "請比較 LangGraph 和 Cloudflare Workers AI 在 API-42 的 90 秒限制，"
        "URL https://example.test/a 與 `router.plan()` 是否保留？"
    )

    markers = extract_preservation_markers(question)

    for expected in (
        "LangGraph",
        "Cloudflare Workers AI",
        "API-42",
        "90",
        "https://example.test/a",
        "router.plan()",
    ):
        assert expected in markers


def test_marker_loss_fails_closed_for_model_product_and_technical_identifiers() -> None:
    provider = FakeCanonicalizer("What is preserved?")
    envelope = build_language_envelope(
        "MiniMax-M3 與 CF-120B 哪個處理 2 個 segments？",
        canonicalization_provider=provider,
    )

    assert envelope.ok is False
    assert envelope.canonicalization_status == "failed"
    assert envelope.failure_code == "CANONICALIZATION_MARKER_LOSS"


@pytest.mark.parametrize(
    ("dimension", "description"),
    (
        ("negation", "drops negation"),
        ("relationship_direction", "reverses relationship direction"),
        ("comparison_direction", "reverses comparison subject or object"),
        ("multi_part_synthesis", "drops a required synthesis component"),
        ("modality_qualifiers", "loses modality or qualifier"),
        ("intent", "reports a failed applicable dimension"),
    ),
)
def test_semantic_fidelity_failed_dimensions_fail_closed(
    dimension: str,
    description: str,
) -> None:
    provider = FakeCanonicalizer(
        f"This provider result {description}.",
        semantic_fidelity=complete_fidelity(**{dimension: "failed"}),
    )

    envelope = build_language_envelope(
        "請不要改變關係方向、比較方向、限制條件或多段需求。",
        canonicalization_provider=provider,
    )

    assert envelope.ok is False
    assert envelope.canonicalization_status == "failed"
    assert envelope.failure_code == "CANONICALIZATION_SEMANTIC_LOSS"
    assert dimension in envelope.failure_detail


def test_missing_semantic_fidelity_contract_fails_closed() -> None:
    provider = FakeCanonicalizer(
        "Do not change the relationship, comparison, qualifier, or synthesis.",
        semantic_fidelity=None,
    )

    envelope = build_language_envelope(
        "請不要改變關係方向、比較方向、限制條件或多段需求。",
        canonicalization_provider=provider,
    )

    assert envelope.ok is False
    assert envelope.failure_code == "CANONICALIZATION_FIDELITY_MISSING"


def test_missing_required_semantic_fidelity_dimension_fails_closed() -> None:
    fidelity = complete_fidelity().as_mapping()
    del fidelity["graph_entity_references"]
    provider = FakeCanonicalizer(
        "Do not change the relationship, comparison, qualifier, or synthesis.",
        semantic_fidelity=fidelity,
    )

    envelope = build_language_envelope(
        "請不要改變關係方向、比較方向、限制條件或多段需求。",
        canonicalization_provider=provider,
    )

    assert envelope.ok is False
    assert envelope.failure_code == "CANONICALIZATION_FIDELITY_MISSING"


def test_invalid_semantic_fidelity_state_fails_closed() -> None:
    fidelity = complete_fidelity().as_mapping()
    fidelity["negation"] = "maybe"
    provider = FakeCanonicalizer(
        "Do not change the relationship, comparison, qualifier, or synthesis.",
        semantic_fidelity=fidelity,
    )

    envelope = build_language_envelope(
        "請不要改變關係方向、比較方向、限制條件或多段需求。",
        canonicalization_provider=provider,
    )

    assert envelope.ok is False
    assert envelope.failure_code == "CANONICALIZATION_FIDELITY_INVALID"


def test_negation_comparison_relation_synthesis_and_modality_are_carried_by_contract() -> None:
    provider = FakeCanonicalizer(
        "Do not treat Part 2 as preceding Part 1; compare router and replanner, "
        "and explain how they should work together when evidence is insufficient."
    )
    original = (
        "不要把 Part 2 說成 precedes Part 1；請比較 router 和 replanner，"
        "並說明 evidence 不足時它們應該如何一起工作。"
    )

    envelope = build_language_envelope(original, canonicalization_provider=provider)

    canonical = envelope.canonical_question_en.casefold()
    assert "do not" in canonical
    assert "part 2" in canonical and "preceding part 1" in canonical
    assert "compare router and replanner" in canonical
    assert "work together" in canonical
    assert "should" in canonical
    assert "insufficient" in canonical


def test_provider_telemetry_cannot_override_adapter_owned_validation_keys() -> None:
    request = bounded_canonicalization_request(
        original_question="API-42 如何在 2 個 steps 中工作？",
        detected_input_language="mixed",
        requested_answer_language="zh-TW",
    )

    result = validate_canonicalization_result(
        request=request,
        result=CanonicalizationResult(
            canonical_question_en="How does API-42 work in 2 steps?",
            status="ok",
            telemetry={
                "schema_version": "provider-owned",
                "status": "provider-owned",
                "preservation_marker_count": 999,
            },
            semantic_fidelity=complete_fidelity(),
        ),
    )

    assert result.ok is True
    assert result.telemetry["schema_version"] == CANONICALIZATION_SCHEMA_VERSION
    assert result.telemetry["status"] == "ok"
    assert result.telemetry["preservation_marker_count"] == len(
        request.preservation_markers
    )


def test_canonicalization_failure_is_explicit_and_does_not_invent_english() -> None:
    envelope = build_language_envelope(
        "這個問題需要 canonicalization。",
        canonicalization_provider=FailingCanonicalizer(),
    )

    assert envelope.ok is False
    assert envelope.canonical_question_en == ""
    assert envelope.failure_code == "CANONICALIZER_UNAVAILABLE"
    assert envelope.telemetry["canonicalization_status"] == "failed"


def test_non_english_without_provider_fails_closed() -> None:
    envelope = build_language_envelope("這個問題沒有 provider。")

    assert envelope.ok is False
    assert envelope.failure_code == "CANONICALIZATION_PROVIDER_REQUIRED"
    assert envelope.telemetry["canonicalization_provider_invoked"] is False


def test_original_question_is_never_overwritten() -> None:
    original = "  Router 如何保留 `state.id`？  "
    provider = FakeCanonicalizer("How does the router preserve `state.id`?")

    envelope = build_language_envelope(original, canonicalization_provider=provider)

    assert envelope.original_question == original
    assert envelope.canonical_question_en == "How does the router preserve `state.id`?"


def test_no_benchmark_specific_mappings_in_phase1_modules() -> None:
    root = Path(__file__).resolve().parents[1]
    source = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in (
            "src/knowledge_engine/m26_multilingual_language_envelope.py",
            "src/knowledge_engine/m26_multilingual_canonicalization.py",
        )
    )

    for forbidden in ("Q01", "Q03", "Q04", "Q06", "Q08", "差別"):
        assert forbidden not in source


def test_language_detection_distinguishes_english_zh_tw_and_mixed() -> None:
    assert detect_input_language("How does routing work?") == "en"
    assert detect_input_language("這是中文問題嗎？") == "zh-TW"
    assert detect_input_language("Router 會如何處理？") == "mixed"
