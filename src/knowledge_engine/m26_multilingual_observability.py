from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .m26_multilingual_retrieval_adapter import CandidateUnionResult


@dataclass(frozen=True)
class QueryCandidateObservation:
    candidate_id: str
    rank: int


@dataclass(frozen=True)
class CandidateContributionObservation:
    channel: str
    query_representation: str
    rank: int
    raw_score_if_available: float | None


@dataclass(frozen=True)
class FusedCandidateObservation:
    candidate_id: str
    fusion_score: float
    contributions: tuple[CandidateContributionObservation, ...]


@dataclass(frozen=True)
class RetrievalObservabilitySnapshot:
    status: str
    mode: str | None
    original_dense_candidates: tuple[QueryCandidateObservation, ...]
    canonical_dense_candidates: tuple[QueryCandidateObservation, ...]
    original_canonical_dense_overlap_ids: tuple[str, ...]
    lexical_candidate_ids: tuple[str, ...]
    graph_candidate_ids: tuple[str, ...]
    identifier_candidate_ids: tuple[str, ...]
    union_candidate_count: int
    union_contribution_by_source: dict[str, int]
    fused_candidates: tuple[FusedCandidateObservation, ...]
    selected_evidence_ids: tuple[str, ...]
    failure_code: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "original_dense_candidates": [
                _query_observation_dict(candidate)
                for candidate in self.original_dense_candidates
            ],
            "canonical_dense_candidates": [
                _query_observation_dict(candidate)
                for candidate in self.canonical_dense_candidates
            ],
            "original_canonical_dense_overlap_ids": list(
                self.original_canonical_dense_overlap_ids
            ),
            "lexical_candidate_ids": list(self.lexical_candidate_ids),
            "graph_candidate_ids": list(self.graph_candidate_ids),
            "identifier_candidate_ids": list(self.identifier_candidate_ids),
            "union_candidate_count": self.union_candidate_count,
            "union_contribution_by_source": dict(self.union_contribution_by_source),
            "fused_candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "fusion_score": candidate.fusion_score,
                    "contributions": [
                        {
                            "channel": contribution.channel,
                            "query_representation": contribution.query_representation,
                            "rank": contribution.rank,
                            "raw_score_if_available": contribution.raw_score_if_available,
                        }
                        for contribution in candidate.contributions
                    ],
                }
                for candidate in self.fused_candidates
            ],
            "selected_evidence_ids": list(self.selected_evidence_ids),
            "failure_code": self.failure_code,
        }


def build_retrieval_observability_snapshot(
    union: CandidateUnionResult,
    *,
    selected_evidence_ids: tuple[str, ...] = (),
) -> RetrievalObservabilitySnapshot:
    original_dense = _candidate_rank_observations(
        union,
        channel="dense",
        query_representation="original",
    )
    canonical_dense = _candidate_rank_observations(
        union,
        channel="dense",
        query_representation="canonical_en",
    )
    original_ids = {candidate.candidate_id for candidate in original_dense}
    canonical_ids = {candidate.candidate_id for candidate in canonical_dense}
    return RetrievalObservabilitySnapshot(
        status=union.status,
        mode=union.mode,
        original_dense_candidates=original_dense,
        canonical_dense_candidates=canonical_dense,
        original_canonical_dense_overlap_ids=tuple(sorted(original_ids & canonical_ids)),
        lexical_candidate_ids=_candidate_ids_for_channel(union, "lexical"),
        graph_candidate_ids=_candidate_ids_for_channel(union, "graph"),
        identifier_candidate_ids=_candidate_ids_for_channel(union, "identifier"),
        union_candidate_count=len(union.candidates),
        union_contribution_by_source=_contribution_counts(union),
        fused_candidates=tuple(
            FusedCandidateObservation(
                candidate_id=candidate.candidate_id,
                fusion_score=candidate.fusion_score,
                contributions=tuple(
                    CandidateContributionObservation(
                        channel=contribution.channel,
                        query_representation=contribution.query_representation,
                        rank=contribution.rank,
                        raw_score_if_available=contribution.raw_score_if_available,
                    )
                    for contribution in candidate.contributions
                ),
            )
            for candidate in union.candidates
        ),
        selected_evidence_ids=selected_evidence_ids,
        failure_code=union.failure_code,
    )


def _candidate_rank_observations(
    union: CandidateUnionResult,
    *,
    channel: str,
    query_representation: str,
) -> tuple[QueryCandidateObservation, ...]:
    observations: list[QueryCandidateObservation] = []
    for candidate in union.candidates:
        for contribution in candidate.contributions:
            if (
                contribution.channel == channel
                and contribution.query_representation == query_representation
            ):
                observations.append(
                    QueryCandidateObservation(
                        candidate_id=candidate.candidate_id,
                        rank=contribution.rank,
                    )
                )
    return tuple(sorted(observations, key=lambda item: (item.rank, item.candidate_id)))


def _candidate_ids_for_channel(
    union: CandidateUnionResult,
    channel: str,
) -> tuple[str, ...]:
    ids = {
        candidate.candidate_id
        for candidate in union.candidates
        for contribution in candidate.contributions
        if contribution.channel == channel
    }
    return tuple(sorted(ids))


def _contribution_counts(union: CandidateUnionResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in union.candidates:
        for contribution in candidate.contributions:
            key = f"{contribution.channel}:{contribution.query_representation}"
            counts[key] = counts.get(key, 0) + 1
    return counts


def _query_observation_dict(
    candidate: QueryCandidateObservation,
) -> dict[str, str | int]:
    return {
        "candidate_id": candidate.candidate_id,
        "rank": candidate.rank,
    }
