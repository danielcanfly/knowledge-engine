from __future__ import annotations

import copy
from typing import Any

import pytest

from knowledge_engine.errors import ConfigurationError, IntegrityError
from knowledge_engine.m20_retrieval_modes import (
    HYBRID_MODE,
    LEXICAL_MODE,
    VECTOR_MODE,
    RetrievalModeController,
    RetrievalModeSettings,
)

RELEASE = {
    "release_id": "20260713T000000Z-m204fixture",
    "manifest_sha256": "a" * 64,
    "loaded_at": "2026-07-13T00:00:00Z",
}


class FakeRuntime:
    def __init__(
        self,
        *,
        semantic_ready: bool = True,
        diagnostic_enabled: bool = True,
        semantic_release: dict[str, Any] | None = None,
    ) -> None:
        self.semantic_diagnostic_enabled = diagnostic_enabled
        self.semantic_ready = semantic_ready
        self.semantic_release = semantic_release or RELEASE
        self.lexical_calls = 0
        self.vector_calls = 0

    def semantic_capability(self) -> dict[str, Any]:
        if not self.semantic_ready:
            return {
                "status": "unavailable",
                "memory_mapped": False,
                "diagnostic_enabled": self.semantic_diagnostic_enabled,
            }
        return {
            "status": "ready",
            "memory_mapped": True,
            "diagnostic_enabled": self.semantic_diagnostic_enabled,
            "artifact_id": "semantic-fixture",
            "row_count": 2,
            "dimension": 2,
            "provider": "fixture-provider",
            "model_id": "fixture-model",
        }

    def query(
        self,
        query: str,
        allowed_audiences: set[str],
        *,
        limit: int = 10,
    ) -> dict[str, Any]:
        self.lexical_calls += 1
        del allowed_audiences, limit
        return {
            "status": "answered",
            "release": copy.deepcopy(RELEASE),
            "query": query,
            "results": [
                {
                    "section_id": "concepts/public#overview",
                    "concept_id": "concepts/public",
                    "audience": "public",
                    "score": 7,
                    "citations": [{"source_id": "source-public"}],
                }
            ],
            "retrieval": {"mode": "wiki_first", "lexical_candidate_count": 1},
            "evaluation": {"evaluation_id": "eval_lexical_fixture"},
            "not_found_reason": None,
            "non_answer_reason": None,
        }

    def query_vector_diagnostic(
        self,
        query_vector: tuple[float, ...],
        allowed_audiences: set[str],
        *,
        limit: int = 10,
    ) -> dict[str, Any]:
        self.vector_calls += 1
        assert query_vector == (1.0, 0.0)
        results = [
            {
                "row": 0,
                "section_id": "concepts/public#overview",
                "concept_id": "concepts/public",
                "audience": "public",
                "score": 1.0,
            }
        ]
        if "internal" in allowed_audiences:
            results.append(
                {
                    "row": 1,
                    "section_id": "concepts/internal#overview",
                    "concept_id": "concepts/internal",
                    "audience": "internal",
                    "score": 0.0,
                }
            )
        return {
            "status": "answered",
            "release": copy.deepcopy(self.semantic_release),
            "results": results[:limit],
            "retrieval": {
                "mode": "vector_diagnostic",
                "candidate_count": 2,
                "authorized_candidate_count": len(results),
                "acl_filtered_count": 2 - len(results),
            },
            "not_found_reason": None,
            "non_answer_reason": None,
        }


def settings(mode: str) -> RetrievalModeSettings:
    if mode == LEXICAL_MODE:
        return RetrievalModeSettings(mode=mode)
    return RetrievalModeSettings(
        mode=mode,
        app_env="staging",
        channel="candidate",
        expected_model_id="fixture-model",
        expected_dimension=2,
        semantic_diagnostic_enabled=True,
    )


def test_lexical_is_default_and_production_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "RETRIEVAL_MODE",
        "EXPECTED_SEMANTIC_MODEL_ID",
        "EXPECTED_SEMANTIC_DIMENSION",
        "SEMANTIC_DIAGNOSTIC_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("KNOWLEDGE_CHANNEL", "production")

    loaded = RetrievalModeSettings.from_env()

    assert loaded.mode == LEXICAL_MODE
    assert loaded.authoritative_mode == LEXICAL_MODE
    assert loaded.semantic_required is False


@pytest.mark.parametrize("mode", [HYBRID_MODE, VECTOR_MODE])
def test_semantic_modes_are_forbidden_in_production(mode: str) -> None:
    with pytest.raises(ConfigurationError, match="M20-MODE-005"):
        RetrievalModeSettings(
            mode=mode,
            app_env="production",
            channel="candidate",
            expected_model_id="fixture-model",
            expected_dimension=2,
            semantic_diagnostic_enabled=True,
        ).validate()

    with pytest.raises(ConfigurationError, match="M20-MODE-006"):
        RetrievalModeSettings(
            mode=mode,
            app_env="staging",
            channel="production",
            expected_model_id="fixture-model",
            expected_dimension=2,
            semantic_diagnostic_enabled=True,
        ).validate()


def test_semantic_modes_require_exact_policy_and_enablement() -> None:
    with pytest.raises(ConfigurationError, match="M20-MODE-007"):
        RetrievalModeSettings(
            mode=HYBRID_MODE,
            app_env="staging",
            channel="candidate",
            expected_dimension=2,
            semantic_diagnostic_enabled=True,
        ).validate()

    with pytest.raises(ConfigurationError, match="M20-MODE-008"):
        RetrievalModeSettings(
            mode=HYBRID_MODE,
            app_env="staging",
            channel="candidate",
            expected_model_id="fixture-model",
            semantic_diagnostic_enabled=True,
        ).validate()

    with pytest.raises(ConfigurationError, match="M20-MODE-009"):
        RetrievalModeSettings(
            mode=VECTOR_MODE,
            app_env="staging",
            channel="candidate",
            expected_model_id="fixture-model",
            expected_dimension=2,
        ).validate()


def test_lexical_mode_preserves_results_and_evaluation() -> None:
    runtime = FakeRuntime(semantic_ready=False, diagnostic_enabled=False)
    controller = RetrievalModeController(settings(LEXICAL_MODE))

    result = controller.query(runtime, "knowledge compiler", {"public"})

    assert runtime.lexical_calls == 1
    assert runtime.vector_calls == 0
    assert result["results"][0]["citations"] == [{"source_id": "source-public"}]
    assert result["evaluation"] == {"evaluation_id": "eval_lexical_fixture"}
    assert result["retrieval"]["authoritative_mode"] == LEXICAL_MODE
    assert result["retrieval"]["fusion_applied"] is False
    assert "shadow_evaluation" not in result


def test_lexical_mode_rejects_unused_query_vector() -> None:
    controller = RetrievalModeController(settings(LEXICAL_MODE))

    with pytest.raises(IntegrityError, match="M20-MODE-111"):
        controller.query(
            FakeRuntime(),
            "knowledge compiler",
            {"public"},
            query_vector=[1.0, 0.0],
        )


def test_hybrid_is_shadow_only_and_lexical_remains_authoritative() -> None:
    runtime = FakeRuntime()
    controller = RetrievalModeController(settings(HYBRID_MODE))

    first = controller.query(
        runtime,
        "knowledge compiler",
        {"public"},
        query_vector=[1.0, 0.0],
    )
    second = controller.query(
        runtime,
        "knowledge compiler",
        {"public"},
        query_vector=[1.0, 0.0],
    )

    assert first == second
    assert first["status"] == "answered"
    assert first["results"][0]["citations"] == [{"source_id": "source-public"}]
    assert first["evaluation"] == {"evaluation_id": "eval_lexical_fixture"}
    assert first["retrieval"]["mode"] == "hybrid_shadow"
    assert first["retrieval"]["authoritative_mode"] == LEXICAL_MODE
    assert first["retrieval"]["fusion_applied"] is False
    assert first["shadow_evaluation"]["diagnostic_only"] is True
    assert first["shadow_evaluation"]["fusion_applied"] is False
    assert all(
        item["audience"] == "public"
        for item in first["shadow_evaluation"]["results"]
    )


def test_vector_mode_returns_diagnostic_identity_and_scores_only() -> None:
    runtime = FakeRuntime()
    controller = RetrievalModeController(settings(VECTOR_MODE))

    result = controller.query(
        runtime,
        "knowledge compiler",
        {"public"},
        query_vector=[1.0, 0.0],
    )

    assert runtime.lexical_calls == 0
    assert runtime.vector_calls == 1
    assert result["query"] == "knowledge compiler"
    assert result["retrieval"]["diagnostic_only"] is True
    assert result["retrieval"]["authoritative_mode"] == "vector_diagnostic"
    assert result["retrieval"]["fusion_applied"] is False
    assert "evaluation" not in result
    assert "citations" not in result["results"][0]
    assert "body" not in result["results"][0]


def test_semantic_mode_requires_ready_matching_capability() -> None:
    controller = RetrievalModeController(settings(HYBRID_MODE))

    with pytest.raises(IntegrityError, match="semantic_unavailable"):
        controller.query(
            FakeRuntime(semantic_ready=False),
            "knowledge compiler",
            {"public"},
            query_vector=[1.0, 0.0],
        )

    runtime = FakeRuntime()
    runtime.semantic_capability = lambda: {
        "status": "ready",
        "model_id": "wrong-model",
        "dimension": 2,
    }
    with pytest.raises(IntegrityError, match="model_mismatch"):
        controller.query(
            runtime,
            "knowledge compiler",
            {"public"},
            query_vector=[1.0, 0.0],
        )


def test_semantic_query_vector_bounds_fail_closed() -> None:
    controller = RetrievalModeController(settings(VECTOR_MODE))
    runtime = FakeRuntime()

    with pytest.raises(IntegrityError, match="M20-MODE-104"):
        controller.query(runtime, "knowledge compiler", {"public"})
    with pytest.raises(IntegrityError, match="M20-MODE-105"):
        controller.query(
            runtime,
            "knowledge compiler",
            {"public"},
            query_vector=[1.0],
        )
    with pytest.raises(IntegrityError, match="M20-MODE-108"):
        controller.query(
            runtime,
            "knowledge compiler",
            {"public"},
            query_vector=[0.5, 0.5],
        )


def test_hybrid_rejects_cross_release_shadow_results() -> None:
    runtime = FakeRuntime(
        semantic_release={
            "release_id": "different-release",
            "manifest_sha256": "b" * 64,
            "loaded_at": "2026-07-13T00:00:00Z",
        }
    )
    controller = RetrievalModeController(settings(HYBRID_MODE))

    with pytest.raises(IntegrityError, match="M20-MODE-112"):
        controller.query(
            runtime,
            "knowledge compiler",
            {"public"},
            query_vector=[1.0, 0.0],
        )


def test_capability_is_bounded_path_free_and_reports_no_fusion() -> None:
    controller = RetrievalModeController(settings(HYBRID_MODE))

    capability = controller.capability(FakeRuntime())

    assert capability == {
        "configured_mode": "hybrid",
        "authoritative_mode": "lexical",
        "shadow_only": True,
        "diagnostic_only": False,
        "fusion_applied": False,
        "production_authority": False,
        "semantic_required": True,
        "semantic_ready": True,
        "ready": True,
        "reason": None,
        "model_id": "fixture-model",
        "dimension": 2,
    }
    assert "path" not in capability
    assert "object_key" not in capability
