from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .m26_multilingual_canonicalization import extract_preservation_markers
from .m26_multilingual_language_envelope import LanguageEnvelope

RetrievalChannel = Literal["dense", "lexical", "graph", "identifier"]
QueryRepresentation = Literal["original", "canonical_en"]
RetrievalMode = Literal["english_passthrough", "multilingual_dual_query"]
RetrievalStatus = Literal["ok", "failed"]

RRF_RANK_CONSTANT = 60


@dataclass(frozen=True)
class RetrievalQuery:
    channel: RetrievalChannel
    query_representation: QueryRepresentation
    query_text: str
    exact_identifier_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalHit:
    candidate_id: str
    rank: int
    raw_score_if_available: float | None = None


@dataclass(frozen=True)
class RetrievalChannelResult:
    hits: tuple[RetrievalHit, ...] = ()
    status: RetrievalStatus = "ok"
    failure_code: str = ""
    failure_detail: str = ""


@dataclass(frozen=True)
class CandidateContribution:
    channel: RetrievalChannel
    query_representation: QueryRepresentation
    rank: int
    raw_score_if_available: float | None
    rank_fusion_score: float


@dataclass(frozen=True)
class FusedRetrievalCandidate:
    candidate_id: str
    fusion_score: float
    contributions: tuple[CandidateContribution, ...]

    @property
    def contribution_count(self) -> int:
        return len(self.contributions)


@dataclass(frozen=True)
class RetrievalInputPlan:
    status: RetrievalStatus
    mode: RetrievalMode | None
    queries: tuple[RetrievalQuery, ...] = ()
    failure_code: str = ""
    failure_detail: str = ""


@dataclass(frozen=True)
class CandidateUnionResult:
    status: RetrievalStatus
    mode: RetrievalMode | None
    queries: tuple[RetrievalQuery, ...] = ()
    candidates: tuple[FusedRetrievalCandidate, ...] = ()
    failure_code: str = ""
    failure_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


Retriever = Callable[[RetrievalQuery], RetrievalChannelResult]


def prepare_retrieval_input_plan(envelope: LanguageEnvelope) -> RetrievalInputPlan:
    if envelope.detected_input_language == "en":
        if not envelope.ok:
            return RetrievalInputPlan(
                status="failed",
                mode=None,
                failure_code="LANGUAGE_ENVELOPE_INVALID",
                failure_detail="retrieval requires a successful language envelope",
            )
        return RetrievalInputPlan(
            status="ok",
            mode="english_passthrough",
            queries=(
                RetrievalQuery(
                    channel="dense",
                    query_representation="original",
                    query_text=envelope.original_question,
                ),
            ),
        )
    if not envelope.canonical_question_en:
        return RetrievalInputPlan(
            status="failed",
            mode=None,
            failure_code="CANONICAL_ENGLISH_QUERY_REQUIRED",
            failure_detail="non-English retrieval requires canonical English",
        )
    if not envelope.ok:
        return RetrievalInputPlan(
            status="failed",
            mode=None,
            failure_code="LANGUAGE_ENVELOPE_INVALID",
            failure_detail="retrieval requires a successful language envelope",
        )

    identifier_terms = tuple(extract_preservation_markers(envelope.original_question))
    queries = [
        RetrievalQuery(
            channel="dense",
            query_representation="original",
            query_text=envelope.original_question,
        ),
        RetrievalQuery(
            channel="dense",
            query_representation="canonical_en",
            query_text=envelope.canonical_question_en,
        ),
        RetrievalQuery(
            channel="lexical",
            query_representation="canonical_en",
            query_text=envelope.canonical_question_en,
            exact_identifier_terms=identifier_terms,
        ),
        RetrievalQuery(
            channel="graph",
            query_representation="canonical_en",
            query_text=envelope.canonical_question_en,
            exact_identifier_terms=identifier_terms,
        ),
    ]
    if identifier_terms:
        queries.append(
            RetrievalQuery(
                channel="identifier",
                query_representation="original",
                query_text=" ".join(identifier_terms),
                exact_identifier_terms=identifier_terms,
            )
        )
    return RetrievalInputPlan(
        status="ok",
        mode="multilingual_dual_query",
        queries=tuple(queries),
    )


def build_candidate_union(
    envelope: LanguageEnvelope,
    *,
    dense_retriever: Retriever,
    lexical_retriever: Retriever,
    graph_retriever: Retriever,
    identifier_retriever: Retriever | None = None,
) -> CandidateUnionResult:
    plan = prepare_retrieval_input_plan(envelope)
    if plan.status != "ok":
        return CandidateUnionResult(
            status="failed",
            mode=plan.mode,
            failure_code=plan.failure_code,
            failure_detail=plan.failure_detail,
        )
    if plan.mode == "english_passthrough":
        return CandidateUnionResult(
            status="ok",
            mode=plan.mode,
            queries=plan.queries,
        )

    observations: list[tuple[RetrievalQuery, RetrievalHit]] = []
    for query in plan.queries:
        retriever = _retriever_for_query(
            query,
            dense_retriever=dense_retriever,
            lexical_retriever=lexical_retriever,
            graph_retriever=graph_retriever,
            identifier_retriever=identifier_retriever,
        )
        if retriever is None:
            continue
        result = retriever(query)
        if result.status != "ok":
            return CandidateUnionResult(
                status="failed",
                mode=plan.mode,
                queries=plan.queries,
                failure_code=result.failure_code or "RETRIEVAL_CHANNEL_FAILED",
                failure_detail=result.failure_detail,
            )
        for hit in result.hits:
            failure = _validate_hit(hit)
            if failure is not None:
                return CandidateUnionResult(
                    status="failed",
                    mode=plan.mode,
                    queries=plan.queries,
                    failure_code=failure[0],
                    failure_detail=failure[1],
                )
            observations.append((query, hit))

    return CandidateUnionResult(
        status="ok",
        mode=plan.mode,
        queries=plan.queries,
        candidates=_fuse_observations(observations),
    )


def _retriever_for_query(
    query: RetrievalQuery,
    *,
    dense_retriever: Retriever,
    lexical_retriever: Retriever,
    graph_retriever: Retriever,
    identifier_retriever: Retriever | None,
) -> Retriever | None:
    if query.channel == "dense":
        return dense_retriever
    if query.channel == "lexical":
        return lexical_retriever
    if query.channel == "graph":
        return graph_retriever
    return identifier_retriever


def _validate_hit(hit: RetrievalHit) -> tuple[str, str] | None:
    if not hit.candidate_id.strip():
        return (
            "RETRIEVAL_CANDIDATE_ID_MISSING",
            "retrieval candidate omitted a stable identity",
        )
    if hit.rank < 1:
        return (
            "RETRIEVAL_CANDIDATE_RANK_INVALID",
            "retrieval candidate rank must be one-based",
        )
    return None


def _fuse_observations(
    observations: list[tuple[RetrievalQuery, RetrievalHit]],
) -> tuple[FusedRetrievalCandidate, ...]:
    by_id: dict[str, list[CandidateContribution]] = {}
    for query, hit in _dedupe_observations_by_vote(observations):
        contribution = CandidateContribution(
            channel=query.channel,
            query_representation=query.query_representation,
            rank=hit.rank,
            raw_score_if_available=hit.raw_score_if_available,
            rank_fusion_score=_reciprocal_rank_score(hit.rank),
        )
        by_id.setdefault(hit.candidate_id, []).append(contribution)

    candidates = [
        FusedRetrievalCandidate(
            candidate_id=candidate_id,
            fusion_score=sum(
                contribution.rank_fusion_score for contribution in contributions
            ),
            contributions=tuple(contributions),
        )
        for candidate_id, contributions in by_id.items()
    ]
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (-candidate.fusion_score, candidate.candidate_id),
        )
    )


def _dedupe_observations_by_vote(
    observations: list[tuple[RetrievalQuery, RetrievalHit]],
) -> tuple[tuple[RetrievalQuery, RetrievalHit], ...]:
    by_vote: dict[tuple[str, str, str], tuple[RetrievalQuery, RetrievalHit]] = {}
    for query, hit in observations:
        key = (hit.candidate_id, query.channel, query.query_representation)
        current = by_vote.get(key)
        if current is None or _observation_sort_key(hit) < _observation_sort_key(current[1]):
            by_vote[key] = (query, hit)
    return tuple(by_vote.values())


def _observation_sort_key(hit: RetrievalHit) -> tuple[int, int, float, str]:
    raw_score = hit.raw_score_if_available
    return (
        hit.rank,
        1 if raw_score is None else 0,
        -(raw_score if raw_score is not None else 0.0),
        hit.candidate_id,
    )


def _reciprocal_rank_score(rank: int) -> float:
    return 1.0 / (RRF_RANK_CONSTANT + rank)
