from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from knowledge_engine.m26_multilingual_language_envelope import LanguageEnvelope
from knowledge_engine.m26_multilingual_retrieval_adapter import (
    CandidateUnionResult,
    RetrievalChannelResult,
    RetrievalHit,
    RetrievalQuery,
    build_candidate_union,
    prepare_retrieval_input_plan,
)


class RecordingRetriever:
    def __init__(
        self,
        results: dict[tuple[str, str], RetrievalChannelResult] | None = None,
    ) -> None:
        self.results = results or {}
        self.calls: list[RetrievalQuery] = []

    def __call__(self, query: RetrievalQuery) -> RetrievalChannelResult:
        self.calls.append(query)
        return self.results.get(
            (query.channel, query.query_representation),
            RetrievalChannelResult(),
        )


def successful_envelope(
    *,
    original: str = "LangGraph 如何保留 API-42？",
    canonical: str = "How does LangGraph preserve API-42?",
    detected: str = "mixed",
) -> LanguageEnvelope:
    return LanguageEnvelope(
        original_question=original,
        canonical_question_en=canonical,
        requested_answer_language="zh-TW" if detected != "en" else "en",
        detected_input_language=detected,
        canonicalization_applied=detected != "en",
        canonicalization_status="ok",
    )


def failed_envelope() -> LanguageEnvelope:
    return LanguageEnvelope(
        original_question="LangGraph 如何保留 API-42？",
        canonical_question_en="How does LangGraph preserve API-42?",
        requested_answer_language="zh-TW",
        detected_input_language="mixed",
        canonicalization_applied=True,
        canonicalization_status="failed",
        failure_code="CANONICALIZATION_SEMANTIC_LOSS",
    )


def test_zh_tw_invokes_original_and_canonical_dense_exactly_once_each() -> None:
    dense = RecordingRetriever()
    envelope = successful_envelope(detected="zh-TW")

    result = build_candidate_union(
        envelope,
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    dense_calls = [(call.channel, call.query_representation) for call in dense.calls]
    assert result.ok is True
    assert dense_calls == [("dense", "original"), ("dense", "canonical_en")]


def test_mixed_invokes_original_and_canonical_dense_exactly_once_each() -> None:
    dense = RecordingRetriever()

    build_candidate_union(
        successful_envelope(detected="mixed"),
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    assert [call.query_representation for call in dense.calls] == ["original", "canonical_en"]


def test_english_uses_passthrough_plan_and_does_not_invoke_multilingual_retrievers() -> None:
    dense = RecordingRetriever()
    envelope = successful_envelope(
        original="  How   does routing work?\n",
        canonical="  How   does routing work?\n",
        detected="en",
    )

    result = build_candidate_union(
        envelope,
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    assert result.ok is True
    assert result.mode == "english_passthrough"
    assert result.queries == (
        RetrievalQuery(
            channel="dense",
            query_representation="original",
            query_text="  How   does routing work?\n",
        ),
    )
    assert result.candidates == ()
    assert dense.calls == []


def test_original_and_canonical_dense_queries_are_not_dropped() -> None:
    plan = prepare_retrieval_input_plan(
        successful_envelope(
            original="原始問題保留 API-42",
            canonical="Preserve API-42 from the canonical English question.",
        )
    )

    dense_queries = [query for query in plan.queries if query.channel == "dense"]

    assert [query.query_representation for query in dense_queries] == [
        "original",
        "canonical_en",
    ]
    assert dense_queries[0].query_text == "原始問題保留 API-42"
    assert dense_queries[1].query_text == "Preserve API-42 from the canonical English question."


def test_query_local_ranks_and_raw_scores_stay_with_originating_dense_query() -> None:
    dense = RecordingRetriever(
        {
            ("dense", "original"): RetrievalChannelResult(
                hits=(RetrievalHit("doc-a", rank=3, raw_score_if_available=0.91),)
            ),
            ("dense", "canonical_en"): RetrievalChannelResult(
                hits=(RetrievalHit("doc-a", rank=1, raw_score_if_available=0.14),)
            ),
        }
    )

    result = build_candidate_union(
        successful_envelope(),
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    candidate = result.candidates[0]
    observations = {
        contribution.query_representation: (
            contribution.rank,
            contribution.raw_score_if_available,
        )
        for contribution in candidate.contributions
    }
    assert observations == {"original": (3, 0.91), "canonical_en": (1, 0.14)}


def test_raw_dense_scores_are_not_blindly_summed_for_fusion() -> None:
    dense = RecordingRetriever(
        {
            ("dense", "original"): RetrievalChannelResult(
                hits=(RetrievalHit("doc-a", rank=1, raw_score_if_available=100.0),)
            ),
            ("dense", "canonical_en"): RetrievalChannelResult(
                hits=(RetrievalHit("doc-a", rank=1, raw_score_if_available=200.0),)
            ),
        }
    )

    result = build_candidate_union(
        successful_envelope(),
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    assert result.candidates[0].fusion_score != 300.0
    assert result.candidates[0].fusion_score < 1.0


def test_duplicate_identity_is_deduped_and_both_provenance_records_survive() -> None:
    dense = RecordingRetriever(
        {
            ("dense", "original"): RetrievalChannelResult(hits=(RetrievalHit("doc-a", 1),)),
            ("dense", "canonical_en"): RetrievalChannelResult(hits=(RetrievalHit("doc-a", 2),)),
        }
    )

    result = build_candidate_union(
        successful_envelope(),
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    assert [candidate.candidate_id for candidate in result.candidates] == ["doc-a"]
    assert result.candidates[0].contribution_count == 2
    assert {
        contribution.query_representation for contribution in result.candidates[0].contributions
    } == {"original", "canonical_en"}


def test_duplicate_identity_is_not_counted_as_two_candidate_identities() -> None:
    dense = RecordingRetriever(
        {
            ("dense", "original"): RetrievalChannelResult(hits=(RetrievalHit("doc-a", 1),)),
            ("dense", "canonical_en"): RetrievalChannelResult(hits=(RetrievalHit("doc-a", 1),)),
        }
    )

    result = build_candidate_union(
        successful_envelope(),
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    assert len(result.candidates) == 1


def test_rank_based_fusion_ordering_is_deterministic_and_unique_candidates_survive() -> None:
    dense = RecordingRetriever(
        {
            ("dense", "original"): RetrievalChannelResult(
                hits=(RetrievalHit("doc-a", 1), RetrievalHit("doc-b", 2))
            ),
            ("dense", "canonical_en"): RetrievalChannelResult(
                hits=(RetrievalHit("doc-c", 1), RetrievalHit("doc-a", 3))
            ),
        }
    )

    result = build_candidate_union(
        successful_envelope(),
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    assert [candidate.candidate_id for candidate in result.candidates] == [
        "doc-a",
        "doc-c",
        "doc-b",
    ]


def test_candidate_without_stable_identity_fails_explicitly() -> None:
    dense = RecordingRetriever(
        {
            ("dense", "original"): RetrievalChannelResult(hits=(RetrievalHit("", 1),)),
        }
    )

    result = build_candidate_union(
        successful_envelope(),
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    assert result.ok is False
    assert result.failure_code == "RETRIEVAL_CANDIDATE_ID_MISSING"


def test_fusion_output_does_not_set_verification_support_or_publication_fields() -> None:
    result = CandidateUnionResult(
        status="ok",
        mode="multilingual_dual_query",
    )

    field_names = {field.name for field in fields(result)}
    forbidden = {"is_verified", "is_supported", "publication_ready", "verified", "supported"}
    assert field_names.isdisjoint(forbidden)


def test_canonical_english_is_primary_lexical_query() -> None:
    lexical = RecordingRetriever()

    build_candidate_union(
        successful_envelope(canonical="How does the API-42 router preserve state?"),
        dense_retriever=RecordingRetriever(),
        lexical_retriever=lexical,
        graph_retriever=RecordingRetriever(),
    )

    assert lexical.calls[0].query_representation == "canonical_en"
    assert lexical.calls[0].query_text == "How does the API-42 router preserve state?"


def test_original_exact_identifiers_contribute_to_lexical_and_identifier_inputs() -> None:
    identifier = RecordingRetriever()

    result = build_candidate_union(
        successful_envelope(
            original=(
                "請保留 Cloudflare Workers AI、API-42、"
                "https://example.test/a 與 `router.plan()`"
            ),
            canonical="Preserve Cloudflare Workers AI, API-42, and router.plan().",
        ),
        dense_retriever=RecordingRetriever(),
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
        identifier_retriever=identifier,
    )

    lexical_query = next(query for query in result.queries if query.channel == "lexical")
    assert "Cloudflare Workers AI" in lexical_query.exact_identifier_terms
    assert "API-42" in lexical_query.exact_identifier_terms
    assert "https://example.test/a" in lexical_query.exact_identifier_terms
    assert "router.plan()" in lexical_query.exact_identifier_terms
    assert identifier.calls[0].query_representation == "original"


def test_product_code_has_no_chinese_keyword_rules_or_intent_parser_mapping() -> None:
    root = Path(__file__).resolve().parents[1]
    source = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in (
            "src/knowledge_engine/m26_multilingual_retrieval_adapter.py",
            "src/knowledge_engine/m26_multilingual_observability.py",
        )
    )

    for forbidden in ("Q01", "Q03", "Q04", "Q06", "Q08", "差別", "_intent_class"):
        assert forbidden not in source
    assert "derive_semantic_requirements" not in source
    assert "evaluate_visible_semantics" not in source


def test_canonical_english_is_primary_graph_query_and_direction_is_not_rewritten() -> None:
    graph = RecordingRetriever()
    canonical = "Which edge goes from Node-A to Node-B?"

    result = build_candidate_union(
        successful_envelope(
            original="Node-A 到 Node-B 的方向是什麼？",
            canonical=canonical,
        ),
        dense_retriever=RecordingRetriever(),
        lexical_retriever=RecordingRetriever(),
        graph_retriever=graph,
    )

    assert graph.calls[0].query_representation == "canonical_en"
    assert graph.calls[0].query_text == canonical
    graph_query = next(query for query in result.queries if query.channel == "graph")
    assert "Node-A" in graph_query.exact_identifier_terms
    assert "Node-B" in graph_query.exact_identifier_terms


def test_failed_envelope_is_not_sent_to_retrievers() -> None:
    dense = RecordingRetriever()

    result = build_candidate_union(
        failed_envelope(),
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    assert result.ok is False
    assert result.failure_code == "LANGUAGE_ENVELOPE_INVALID"
    assert dense.calls == []


def test_missing_canonical_english_for_non_english_fails_closed() -> None:
    dense = RecordingRetriever()

    result = build_candidate_union(
        successful_envelope(canonical=""),
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    assert result.ok is False
    assert result.failure_code == "CANONICAL_ENGLISH_QUERY_REQUIRED"
    assert dense.calls == []


def test_retrieval_channel_failure_is_explicit_and_fabricates_no_candidates() -> None:
    dense = RecordingRetriever(
        {
            ("dense", "original"): RetrievalChannelResult(
                status="failed",
                failure_code="DENSE_BACKEND_UNAVAILABLE",
                failure_detail="fixture failure",
            )
        }
    )

    result = build_candidate_union(
        successful_envelope(),
        dense_retriever=dense,
        lexical_retriever=RecordingRetriever(),
        graph_retriever=RecordingRetriever(),
    )

    assert result.ok is False
    assert result.failure_code == "DENSE_BACKEND_UNAVAILABLE"
    assert result.candidates == ()
