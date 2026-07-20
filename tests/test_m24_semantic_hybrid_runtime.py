from __future__ import annotations

import pytest

from knowledge_engine.errors import ConfigurationError, IntegrityError
from knowledge_engine.m24_semantic_hybrid_runtime import (
    HYBRID_SHADOW_MODE,
    LEXICAL_MODE,
    M24RetrievalRuntimeSettings,
    apply_m24_flagged_retrieval,
)


def _lexical_result() -> dict:
    return {
        "status": "answered",
        "results": [
            {
                "section_id": "concepts/harness#overview",
                "concept_id": "concepts/harness",
                "audience": "public",
                "citations": [{"source_id": "source-harness"}],
            }
        ],
        "retrieval": {"mode": "lexical"},
        "evaluation": {"evaluation_id": "lexical-fixture"},
    }


def _shadow_result() -> dict:
    return {
        "status": "answered",
        "results": [
            {
                "point_id": "point-harness",
                "section_id": "concepts/harness#overview",
                "score": 0.91,
            }
        ],
        "authority": {
            "semantic_output_production_authority": False,
            "answer_generation_dispatched": False,
            "qdrant_write_dispatched": False,
            "production_mutation_dispatched": False,
        },
    }


def test_default_runtime_preserves_lexical_authority() -> None:
    lexical = _lexical_result()

    result = apply_m24_flagged_retrieval(lexical)

    assert result["results"] == lexical["results"]
    assert result["evaluation"] == lexical["evaluation"]
    assert result["retrieval"]["production_retrieval"] == LEXICAL_MODE
    assert result["retrieval"]["authoritative_mode"] == LEXICAL_MODE
    assert result["retrieval"]["semantic_hybrid_implementation_enabled"] is False
    assert result["retrieval"]["semantic_answer_serving_enabled"] is False
    assert result["retrieval"]["semantic_promotion_enabled"] is False
    assert result["retrieval"]["hybrid_retrieval_enabled"] is False
    assert result["retrieval"]["shadow_preview_attached"] is False
    assert "m24_shadow_preview" not in result


def test_activation_flag_fails_closed_before_runtime_use() -> None:
    with pytest.raises(ConfigurationError, match="M24-RUNTIME-004"):
        M24RetrievalRuntimeSettings(activation_authorized=True).validate()


def test_shadow_mode_requires_flag_and_non_production_channel() -> None:
    with pytest.raises(ConfigurationError, match="M24-RUNTIME-005"):
        M24RetrievalRuntimeSettings(
            requested_mode=HYBRID_SHADOW_MODE,
            channel="internal",
        ).validate()

    with pytest.raises(ConfigurationError, match="M24-RUNTIME-006"):
        M24RetrievalRuntimeSettings(
            requested_mode=HYBRID_SHADOW_MODE,
            channel="production",
            flagged_implementation_enabled=True,
        ).validate()


def test_flagged_shadow_preview_does_not_change_authoritative_results() -> None:
    lexical = _lexical_result()
    settings = M24RetrievalRuntimeSettings(
        requested_mode=HYBRID_SHADOW_MODE,
        channel="internal",
        flagged_implementation_enabled=True,
    )

    result = apply_m24_flagged_retrieval(
        lexical,
        settings,
        shadow_result=_shadow_result(),
    )

    assert result["results"] == lexical["results"]
    assert result["retrieval"]["production_retrieval"] == LEXICAL_MODE
    assert result["retrieval"]["semantic_hybrid_implementation_enabled"] is True
    assert result["retrieval"]["shadow_preview_attached"] is True
    assert result["retrieval"]["fusion_applied"] is False
    assert result["m24_shadow_preview"] == {
        "status": "answered",
        "result_count": 1,
        "results": [
            {
                "rank": 1,
                "point_id": "point-harness",
                "section_id": "concepts/harness#overview",
                "score_present": True,
            }
        ],
        "diagnostic_only": True,
        "response_authoritative": False,
        "production_authority": False,
        "raw_query_persisted": False,
        "raw_answer_persisted": False,
    }


def test_shadow_preview_rejects_forbidden_authority() -> None:
    settings = M24RetrievalRuntimeSettings(
        requested_mode=HYBRID_SHADOW_MODE,
        channel="internal",
        flagged_implementation_enabled=True,
    )
    shadow = _shadow_result()
    shadow["authority"]["semantic_output_served_to_production"] = True

    with pytest.raises(IntegrityError, match="forbidden authority"):
        apply_m24_flagged_retrieval(
            _lexical_result(),
            settings,
            shadow_result=shadow,
        )


def test_shadow_payload_cannot_be_supplied_to_lexical_mode() -> None:
    with pytest.raises(IntegrityError, match="lexical mode is requested"):
        apply_m24_flagged_retrieval(
            _lexical_result(),
            shadow_result=_shadow_result(),
        )


def test_runtime_settings_from_env_default_to_lexical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "M24_RETRIEVAL_REQUESTED_MODE",
        "M24_SEMANTIC_HYBRID_IMPLEMENTATION_ENABLED",
        "M24_SEMANTIC_ACTIVATION_AUTHORIZED",
        "KNOWLEDGE_CHANNEL",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = M24RetrievalRuntimeSettings.from_env()

    assert settings.requested_mode == LEXICAL_MODE
    assert settings.channel == "production"
    assert settings.flagged_implementation_enabled is False
    assert settings.activation_authorized is False


def test_runtime_settings_from_env_uses_runtime_channel_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KNOWLEDGE_CHANNEL", raising=False)

    settings = M24RetrievalRuntimeSettings.from_env(channel_default="staging")

    assert settings.channel == "staging"


def test_runtime_settings_accept_dynamic_non_production_channels() -> None:
    settings = M24RetrievalRuntimeSettings(channel="candidate-source-abc123")

    settings.validate()


def test_runtime_settings_reject_unbounded_channel() -> None:
    with pytest.raises(ConfigurationError, match="M24-RUNTIME-003"):
        M24RetrievalRuntimeSettings(channel="x" * 129).validate()


def test_wrapper_deep_copies_lexical_input() -> None:
    lexical = _lexical_result()
    result = apply_m24_flagged_retrieval(lexical)

    result["results"][0]["citations"].append({"source_id": "mutated"})

    assert lexical["results"][0]["citations"] == [{"source_id": "source-harness"}]
