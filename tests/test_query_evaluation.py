from __future__ import annotations

from pathlib import Path

from knowledge_engine.query_evaluation import evaluate_runtime_query
from knowledge_engine.runtime import Runtime


def test_runtime_answer_includes_passing_query_evaluation(tmp_path: Path, built_store) -> None:
    store, compiled, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")

    result = runtime.query("knowledge compiler", {"public", "internal"})

    assert result["status"] == "answered"
    assert result["release"]["release_id"] == compiled.release_id
    assert result["evaluation"]["schema_version"] == "1.0"
    assert result["evaluation"]["passed"] is True
    assert result["evaluation"]["release_blocking"] is False
    assert result["evaluation"]["reasons"] == []
    assert result["evaluation"]["metrics"] == {
        "candidate_count": 1,
        "selected_count": 1,
        "citation_count": 1,
        "citation_coverage": 1.0,
        "acl_filtered_count": 0,
        "raw_fallback_used": False,
    }
    assert result["evaluation"]["evaluation_id"].startswith("qeval_")


def test_runtime_non_answer_fails_closed_with_acl_evidence(tmp_path: Path, built_store) -> None:
    store, _, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")

    result = runtime.query("knowledge compiler", {"public"})

    assert result["status"] == "not_found"
    assert result["results"] == []
    assert result["evaluation"]["passed"] is False
    assert result["evaluation"]["release_blocking"] is True
    assert result["evaluation"]["reasons"] == [
        "no_authorized_match",
        "no_retrieval_candidates",
    ]
    assert result["evaluation"]["metrics"]["acl_filtered_count"] == 1


def test_query_evaluation_is_deterministic_and_idempotent() -> None:
    kwargs = {
        "release": {
            "release_id": "20260709T000000Z-m12eval",
            "manifest_sha256": "a" * 64,
            "loaded_at": "2026-07-09T00:00:00Z",
        },
        "query": "quality gate",
        "audiences": {"internal", "public"},
        "status": "answered",
        "results": [
            {
                "concept_id": "concepts/runtime-query-quality",
                "citations": [
                    {
                        "source_id": "src_eval_contract",
                        "uri": "https://example.com/eval",
                        "retrieved_at": "2026-07-09T00:00:00Z",
                    }
                ],
            }
        ],
        "retrieval": {
            "candidate_count": 1,
            "selected_count": 1,
            "acl_filtered_count": 0,
            "raw_fallback_used": False,
        },
        "non_answer_reason": None,
    }

    first = evaluate_runtime_query(**kwargs)
    second = evaluate_runtime_query(**kwargs)

    assert first == second
    assert first["passed"] is True


def test_query_evaluation_fails_closed_for_missing_citations_and_raw_fallback() -> None:
    evaluation = evaluate_runtime_query(
        release={
            "release_id": "20260709T000000Z-m12eval",
            "manifest_sha256": "b" * 64,
            "loaded_at": "2026-07-09T00:00:00Z",
        },
        query="unsupported answer",
        audiences={"internal"},
        status="answered",
        results=[{"concept_id": "concepts/unsupported", "citations": []}],
        retrieval={
            "candidate_count": 1,
            "selected_count": 1,
            "acl_filtered_count": 0,
            "raw_fallback_used": True,
        },
        non_answer_reason=None,
    )

    assert evaluation["passed"] is False
    assert evaluation["release_blocking"] is True
    assert evaluation["reasons"] == [
        "insufficient_citation_coverage",
        "raw_fallback_disallowed",
    ]
    assert evaluation["metrics"]["citation_coverage"] == 0.0
