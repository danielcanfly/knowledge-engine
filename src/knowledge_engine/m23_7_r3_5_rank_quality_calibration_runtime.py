from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence

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
        scores[section_id] = score
    return sorted(
        ((score, section_id) for section_id, score in scores.items()),
        key=lambda item: (-item[0], item[1]),
    )


_base._bm25_ranking = _bm25_ranking

r34 = _base.r34
canonical_json = _base.canonical_json
canonical_sha256 = _base.canonical_sha256
canonical_contract = _base.canonical_contract
build_calibration_candidate = _base.build_calibration_candidate
redacted_candidate_artifact = _base.redacted_candidate_artifact
calibrated_hybrid_ranking = _base.calibrated_hybrid_ranking
evaluate_calibration_candidate = _base.evaluate_calibration_candidate
_redacted_probe_plan = _base._redacted_probe_plan
