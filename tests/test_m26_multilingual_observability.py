from __future__ import annotations

from knowledge_engine.m26_multilingual_observability import (
    build_retrieval_observability_snapshot,
)
from knowledge_engine.m26_multilingual_retrieval_adapter import (
    CandidateContribution,
    CandidateUnionResult,
    FusedRetrievalCandidate,
)


def candidate_union_fixture() -> CandidateUnionResult:
    return CandidateUnionResult(
        status="ok",
        mode="multilingual_dual_query",
        candidates=(
            FusedRetrievalCandidate(
                candidate_id="doc-overlap",
                fusion_score=0.032,
                contributions=(
                    CandidateContribution(
                        channel="dense",
                        query_representation="original",
                        rank=1,
                        raw_score_if_available=0.88,
                        rank_fusion_score=0.016,
                    ),
                    CandidateContribution(
                        channel="dense",
                        query_representation="canonical_en",
                        rank=2,
                        raw_score_if_available=0.12,
                        rank_fusion_score=0.016,
                    ),
                ),
            ),
            FusedRetrievalCandidate(
                candidate_id="doc-lexical",
                fusion_score=0.016,
                contributions=(
                    CandidateContribution(
                        channel="lexical",
                        query_representation="canonical_en",
                        rank=1,
                        raw_score_if_available=None,
                        rank_fusion_score=0.016,
                    ),
                ),
            ),
            FusedRetrievalCandidate(
                candidate_id="doc-graph",
                fusion_score=0.015,
                contributions=(
                    CandidateContribution(
                        channel="graph",
                        query_representation="canonical_en",
                        rank=3,
                        raw_score_if_available=None,
                        rank_fusion_score=0.015,
                    ),
                ),
            ),
            FusedRetrievalCandidate(
                candidate_id="doc-identifier",
                fusion_score=0.014,
                contributions=(
                    CandidateContribution(
                        channel="identifier",
                        query_representation="original",
                        rank=4,
                        raw_score_if_available=None,
                        rank_fusion_score=0.014,
                    ),
                ),
            ),
        ),
    )


def test_observability_contains_ids_ranks_provenance_counts_and_overlap() -> None:
    snapshot = build_retrieval_observability_snapshot(candidate_union_fixture())

    assert snapshot.original_dense_candidates[0].candidate_id == "doc-overlap"
    assert snapshot.original_dense_candidates[0].rank == 1
    assert snapshot.canonical_dense_candidates[0].rank == 2
    assert snapshot.original_canonical_dense_overlap_ids == ("doc-overlap",)
    assert snapshot.lexical_candidate_ids == ("doc-lexical",)
    assert snapshot.graph_candidate_ids == ("doc-graph",)
    assert snapshot.identifier_candidate_ids == ("doc-identifier",)
    assert snapshot.union_contribution_by_source == {
        "dense:original": 1,
        "dense:canonical_en": 1,
        "lexical:canonical_en": 1,
        "graph:canonical_en": 1,
        "identifier:original": 1,
    }


def test_observability_does_not_persist_evidence_bodies_or_arbitrary_payloads() -> None:
    snapshot_dict = build_retrieval_observability_snapshot(
        candidate_union_fixture()
    ).as_dict()

    rendered = repr(snapshot_dict).casefold()

    assert "body" not in rendered
    assert "passage" not in rendered
    assert "content" not in rendered
    assert "payload" not in rendered
    assert "doc-overlap" in rendered


def test_selected_evidence_downstream_hook_is_representable_without_selection() -> None:
    empty_snapshot = build_retrieval_observability_snapshot(candidate_union_fixture())
    observed_snapshot = build_retrieval_observability_snapshot(
        candidate_union_fixture(),
        selected_evidence_ids=("doc-overlap",),
    )

    assert empty_snapshot.selected_evidence_ids == ()
    assert observed_snapshot.selected_evidence_ids == ("doc-overlap",)
    assert observed_snapshot.union_candidate_count == 4
