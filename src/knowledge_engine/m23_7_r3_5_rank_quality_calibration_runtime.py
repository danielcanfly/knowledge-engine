from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from . import m23_7_r3_5_rank_quality_calibration as _base


def _bm25_ranking(
    query_texts: Sequence[str],
    *,
    counts_by_section: Mapping[str, Counter[str]],
    document_frequency: Mapping[str, int],
    lengths: Mapping[str, int],
    average_length: float,
) -> list[tuple[float, str]]:
    query_counts = Counter(
        token for text in query_texts for token in _base._tokens(text)
    )
    _base._require(bool(query_counts), 102, "query lexical surface is empty")
    document_count = len(counts_by_section)
    scores: dict[str, float] = {}
    for section_id, counts in counts_by_section.items():
        length = lengths[section_id]
        score = 0.0
        for token, query_frequency in query_counts.items():
            frequency = counts.get(token, 0)
            if frequency <= 0:
                continue
            df = int(document_frequency.get(token, 0))
            idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
            denominator = frequency + _base.BM25_K1 * (
                1
                - _base.BM25_B
                + _base.BM25_B * length / average_length
            )
            score += (
                idf
                * (frequency * (_base.BM25_K1 + 1) / denominator)
                * (1 + math.log(query_frequency))
            )
        if score > 0.0:
            scores[section_id] = score
    return sorted(
        ((score, section_id) for section_id, score in scores.items()),
        key=lambda item: (-item[0], item[1]),
    )


def calibrated_hybrid_ranking(
    *,
    query_class: str,
    query_texts: Sequence[str],
    query_vectors: Sequence[Sequence[float]],
    corpus: Sequence[tuple[str, Sequence[float]]],
    counts_by_section: Mapping[str, Counter[str]],
    document_frequency: Mapping[str, int],
    lengths: Mapping[str, int],
    average_length: float,
) -> tuple[list[tuple[float, str]], dict[str, object]]:
    """Fuse dense, positive lexical matches, and dense consensus."""

    _base._require(
        query_class in _base.LEXICAL_WEIGHTS,
        103,
        "unsupported query class",
    )
    _base._require(
        len(query_texts) == _base.r34.VARIANTS_PER_PROBE,
        104,
        "query text variant count drifted",
    )
    _base._require(
        len(query_vectors) == _base.r34.VARIANTS_PER_PROBE,
        105,
        "query vector variant count drifted",
    )
    dense = _base._dense_rankings(query_vectors, corpus)
    dense_rrf = _base._rrf_scores(dense)
    lexical = _bm25_ranking(
        query_texts,
        counts_by_section=counts_by_section,
        document_frequency=document_frequency,
        lengths=lengths,
        average_length=average_length,
    )
    lexical_ranks = {
        section_id: rank
        for rank, (_score, section_id) in enumerate(lexical, start=1)
    }
    dense_best_rank: dict[str, int] = {}
    dense_consensus: Counter[str] = Counter()
    for ranking in dense:
        for rank, (_score, section_id) in enumerate(ranking, start=1):
            dense_best_rank[section_id] = min(
                dense_best_rank.get(section_id, len(corpus) + 1),
                rank,
            )
            if rank <= _base.CONSENSUS_DEPTH:
                dense_consensus[section_id] += 1

    lexical_weight = _base.LEXICAL_WEIGHTS[query_class]
    calibrated: dict[str, float] = {}
    for section_id, _vector in corpus:
        dense_score = float(dense_rrf.get(section_id, 0.0))
        lexical_rank = lexical_ranks.get(section_id)
        lexical_score = (
            lexical_weight / (_base.LEXICAL_RRF_K + lexical_rank)
            if lexical_rank is not None
            else 0.0
        )
        consensus_score = (
            _base.CONSENSUS_WEIGHT
            * dense_consensus.get(section_id, 0)
            / (_base.CONSENSUS_RRF_K + dense_best_rank[section_id])
        )
        calibrated[section_id] = dense_score + lexical_score + consensus_score
    ranking = sorted(
        ((score, section_id) for section_id, score in calibrated.items()),
        key=lambda item: (-item[0], item[1]),
    )
    diagnostics: dict[str, object] = {
        "lexical_weight": lexical_weight,
        "dense_variant_count": len(dense),
        "query_token_count": len(
            {token for text in query_texts for token in _base._tokens(text)}
        ),
        "positive_lexical_match_count": len(lexical_ranks),
        "zero_match_lexical_credit": False,
        "target_aware_inputs_accepted": False,
    }
    return ranking, diagnostics


def evaluate_calibration_candidate(
    candidate: Mapping[str, Any],
    query_vectors: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    old_bm25 = _base._bm25_ranking
    old_ranker = _base.calibrated_hybrid_ranking
    try:
        _base._bm25_ranking = _bm25_ranking
        _base.calibrated_hybrid_ranking = calibrated_hybrid_ranking
        return _base.evaluate_calibration_candidate(candidate, query_vectors)
    finally:
        _base._bm25_ranking = old_bm25
        _base.calibrated_hybrid_ranking = old_ranker


r34 = _base.r34
canonical_json = _base.canonical_json
canonical_sha256 = _base.canonical_sha256
canonical_contract = _base.canonical_contract
build_calibration_candidate = _base.build_calibration_candidate
redacted_candidate_artifact = _base.redacted_candidate_artifact
_redacted_probe_plan = _base._redacted_probe_plan
