from __future__ import annotations

import copy
from typing import Any

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m20_hybrid_fusion import (
    RRF_K,
    HybridFusionController,
)
from knowledge_engine.m20_retrieval_modes import (
    HYBRID_MODE,
    LEXICAL_MODE,
    VECTOR_MODE,
    RetrievalModeController,
    RetrievalModeSettings,
)

RELEASE = {
    "release_id": "20260713T000000Z-m205fixture",
    "manifest_sha256": "a" * 64,
    "loaded_at": "2026-07-13T00:00:00Z",
}


def _item(
    section: str,
    *,
    audience: str = "public",
    score: float | None = None,
) -> dict:
    item = {
        "section_id": section,
        "concept_id": section.split("#", 1)[0],
        "audience": audience,
        "title": section,
        "citations": [{"source_id": f"src-{section}"}],
    }
    if score is not None:
        item["score"] = score
    return item


class FakeRuntime:
    semantic_diagnostic_enabled = True

    def __init__(self) -> None:
        self.lexical_results = [
            _item("concepts/a#one"),
            _item("concepts/b#one"),
            _item("concepts/c#one"),
        ]
        self.vector_results = [
            _item("concepts/b#one", score=0.95),
            _item("concepts/d#one", score=0.90),
            _item("concepts/a#one", score=0.80),
        ]
        self.semantic_status = "ready"
        self.vector_release = copy.deepcopy(RELEASE)

    def query(self, query: str, audiences: set[str], *, limit: int = 10) -> dict:
        del query
        results = [
            item for item in self.lexical_results if item["audience"] in audiences
        ]
        return {
            "status": "answered" if results else "not_found",
            "release": copy.deepcopy(RELEASE),
            "results": copy.deepcopy(results[:limit]),
            "retrieval": {"mode": "lexical"},
            "evaluation": {"release_blocking": False},
            "not_found_reason": None if results else "no_authorized_match",
        }

    def query_vector_diagnostic(
        self,
        query_vector: tuple[float, ...] | list[float],
        audiences: set[str],
        *,
        limit: int = 10,
    ) -> dict:
        del query_vector
        results = [
            item for item in self.vector_results if item["audience"] in audiences
        ]
        return {
            "status": "answered" if results else "not_found",
            "release": copy.deepcopy(self.vector_release),
            "results": copy.deepcopy(results[:limit]),
            "retrieval": {"mode": "vector_diagnostic"},
            "not_found_reason": (
                None if results else "no_authorized_semantic_match"
            ),
        }

    def semantic_capability(self) -> dict[str, Any]:
        if self.semantic_status != "ready":
            return {"status": self.semantic_status}
        return {
            "status": "ready",
            "model_id": "fixture-model",
            "dimension": 4,
        }


def _controller(mode: str = HYBRID_MODE) -> HybridFusionController:
    settings = RetrievalModeSettings(
        mode=mode,
        app_env="staging",
        channel="staging",
        expected_model_id="fixture-model" if mode != LEXICAL_MODE else None,
        expected_dimension=4 if mode != LEXICAL_MODE else None,
        semantic_diagnostic_enabled=mode != LEXICAL_MODE,
    )
    return HybridFusionController(RetrievalModeController(settings))


def test_rrf_fuses_rankings_deterministically_without_raw_score_mixing() -> None:
    runtime = FakeRuntime()
    result = _controller().query(
        runtime,
        "query",
        {"public"},
        query_vector=[1.0, 0.0, 0.0, 0.0],
        limit=4,
    )

    assert [item["section_id"] for item in result["fused_candidates"]] == [
        "concepts/b#one",
        "concepts/a#one",
        "concepts/d#one",
        "concepts/c#one",
    ]
    first = result["fused_candidates"][0]
    expected = round(1 / (RRF_K + 2) + 1 / (RRF_K + 1), 12)
    assert first["fused_score"] == expected
    assert first["vector_score"] == 0.95
    assert result["retrieval"]["fusion_applied"] is True
    assert result["retrieval"]["rrf_k"] == RRF_K


def test_lexical_results_and_citations_remain_authoritative() -> None:
    runtime = FakeRuntime()
    result = _controller().query(
        runtime,
        "query",
        {"public"},
        query_vector=[1.0, 0.0, 0.0, 0.0],
    )

    assert [item["section_id"] for item in result["results"]] == [
        "concepts/a#one",
        "concepts/b#one",
        "concepts/c#one",
    ]
    assert result["results"][0]["citations"] == [
        {"source_id": "src-concepts/a#one"}
    ]
    assert result["evaluation"] == {"release_blocking": False}
    assert result["retrieval"]["authoritative_mode"] == LEXICAL_MODE


def test_missing_query_vector_falls_back_to_lexical_with_reason() -> None:
    result = _controller().query(FakeRuntime(), "query", {"public"})

    assert result["retrieval"]["fallback_applied"] is True
    assert result["retrieval"]["fallback_reason"] == "query_vector_unavailable"
    assert result["retrieval"]["fusion_applied"] is False
    assert result["fused_candidates"] == []


def test_semantic_unavailable_falls_back_to_lexical() -> None:
    runtime = FakeRuntime()
    runtime.semantic_status = "unavailable"

    result = _controller().query(
        runtime,
        "query",
        {"public"},
        query_vector=[1.0, 0.0, 0.0, 0.0],
    )

    assert result["retrieval"]["fallback_reason"] == "semantic_unavailable"
    assert result["results"][0]["section_id"] == "concepts/a#one"


def test_model_or_dimension_policy_mismatch_remains_fail_closed() -> None:
    runtime = FakeRuntime()
    runtime.semantic_capability = lambda: {
        "status": "ready",
        "model_id": "wrong-model",
        "dimension": 4,
    }

    with pytest.raises(IntegrityError, match="capability mismatch: model_mismatch"):
        _controller().query(
            runtime,
            "query",
            {"public"},
            query_vector=[1.0, 0.0, 0.0, 0.0],
        )


def test_cross_release_shadow_evidence_remains_fail_closed() -> None:
    runtime = FakeRuntime()
    runtime.vector_release["manifest_sha256"] = "b" * 64

    with pytest.raises(IntegrityError, match="release identities differ"):
        _controller().query(
            runtime,
            "query",
            {"public"},
            query_vector=[1.0, 0.0, 0.0, 0.0],
        )


def test_acl_violation_in_ranked_input_is_rejected_before_fusion() -> None:
    runtime = FakeRuntime()
    runtime.vector_results.insert(
        0,
        _item("concepts/secret#one", audience="internal", score=1.0),
    )

    result = _controller().query(
        runtime,
        "query",
        {"public"},
        query_vector=[1.0, 0.0, 0.0, 0.0],
    )
    assert "concepts/secret#one" not in {
        item["section_id"] for item in result["fused_candidates"]
    }


def test_duplicate_or_identity_drift_fails_closed() -> None:
    runtime = FakeRuntime()
    runtime.vector_results.append(_item("concepts/b#one", score=0.5))
    with pytest.raises(IntegrityError, match="duplicate vector section"):
        _controller().query(
            runtime,
            "query",
            {"public"},
            query_vector=[1.0, 0.0, 0.0, 0.0],
        )


def test_lexical_and_vector_modes_delegate_without_fusion() -> None:
    lexical = _controller(LEXICAL_MODE).query(
        FakeRuntime(),
        "query",
        {"public"},
    )
    assert lexical["retrieval"]["fusion_applied"] is False
    assert "fused_candidates" not in lexical

    vector = _controller(VECTOR_MODE).query(
        FakeRuntime(),
        "query",
        {"public"},
        query_vector=[1.0, 0.0, 0.0, 0.0],
    )
    assert vector["retrieval"]["authoritative_mode"] == "vector_diagnostic"
    assert vector["retrieval"]["fusion_applied"] is False
