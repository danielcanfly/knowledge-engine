from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .m23_benchmark_correction import (
    BenchmarkCorrectionError,
    article_id,
)


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise BenchmarkCorrectionError("vector dimensions do not match")
    return math.fsum(a * b for a, b in zip(left, right, strict=True))


def semantic_top_scores(
    suite: Mapping[str, Any],
    gold: Mapping[str, Any],
    document_vectors: Sequence[Sequence[float]],
    query_vectors: Sequence[Sequence[float]],
) -> dict[str, float]:
    documents = suite["documents"]
    queries = suite["queries"]
    if len(documents) != len(document_vectors) or len(queries) != len(query_vectors):
        raise BenchmarkCorrectionError("vector row coverage mismatch")
    gold_by_query = {item["query_id"]: item for item in gold["queries"]}
    scores: dict[str, float] = {}
    for query_index, query in enumerate(queries):
        query_id = query["query_id"]
        allowed = set(gold_by_query[query_id]["semantic_probe_audiences"])
        candidates = [
            _dot(query_vectors[query_index], document_vectors[document_index])
            for document_index, document in enumerate(documents)
            if document["audience"] in allowed
        ]
        if not candidates:
            raise BenchmarkCorrectionError(
                f"semantic probe has no candidate documents for {query_id}"
            )
        scores[query_id] = max(candidates)
    return scores


def calibrate_threshold(
    gold: Mapping[str, Any], top_scores: Mapping[str, float]
) -> dict[str, Any]:
    role_by_query = {
        item["query_id"]: item["evaluation_role"] for item in gold["queries"]
    }
    positives = [
        top_scores[query_id]
        for query_id, role in role_by_query.items()
        if role == "threshold-calibration-positive"
    ]
    negatives = [
        top_scores[query_id]
        for query_id, role in role_by_query.items()
        if role == "threshold-calibration-negative"
    ]
    if not positives or not negatives:
        raise BenchmarkCorrectionError(
            "threshold calibration needs positives and negatives"
        )
    minimum_positive = min(positives)
    maximum_negative = max(negatives)
    if minimum_positive <= maximum_negative:
        raise BenchmarkCorrectionError(
            "calibration scores have no positive separation"
        )
    threshold = (minimum_positive + maximum_negative) / 2.0
    return {
        "strategy": "midpoint-between-worst-positive-and-worst-negative",
        "threshold": threshold,
        "calibration_positive_count": len(positives),
        "calibration_negative_count": len(negatives),
        "minimum_positive_top_score": minimum_positive,
        "maximum_negative_top_score": maximum_negative,
        "separation_margin": minimum_positive - maximum_negative,
    }


def vector_rankings(
    suite: Mapping[str, Any],
    document_vectors: Sequence[Sequence[float]],
    query_vectors: Sequence[Sequence[float]],
    *,
    threshold: float,
    limit: int = 6,
) -> dict[str, list[str]]:
    documents = suite["documents"]
    queries = suite["queries"]
    rankings: dict[str, list[str]] = {}
    for query_index, query in enumerate(queries):
        allowed = set(query["allowed_audiences"])
        if not allowed:
            rankings[query["query_id"]] = []
            continue
        candidates = [
            (
                _dot(
                    query_vectors[query_index],
                    document_vectors[document_index],
                ),
                document["section_id"],
            )
            for document_index, document in enumerate(documents)
            if document["audience"] in allowed
        ]
        candidates.sort(key=lambda item: (-item[0], item[1]))
        if not candidates or candidates[0][0] < threshold:
            rankings[query["query_id"]] = []
        else:
            rankings[query["query_id"]] = [
                section_id for _, section_id in candidates[:limit]
            ]
    return rankings


def reciprocal_rank_fusion(
    first: Mapping[str, Sequence[str]],
    second: Mapping[str, Sequence[str]],
    *,
    constant: int = 60,
    limit: int = 6,
) -> dict[str, list[str]]:
    if set(first) != set(second):
        raise BenchmarkCorrectionError("RRF ranking query coverage mismatch")
    result: dict[str, list[str]] = {}
    for query_id in sorted(first):
        scores: dict[str, float] = {}
        for ranking in (first[query_id], second[query_id]):
            for rank, section_id in enumerate(ranking, start=1):
                scores[section_id] = scores.get(section_id, 0.0) + 1.0 / (
                    constant + rank
                )
        result[query_id] = [
            section_id
            for section_id, _ in sorted(
                scores.items(), key=lambda item: (-item[1], item[0])
            )[:limit]
        ]
    return result


def evaluate_article_rankings(
    suite: Mapping[str, Any],
    gold: Mapping[str, Any],
    rankings: Mapping[str, Sequence[str]],
    *,
    k: int = 3,
) -> dict[str, Any]:
    queries = suite["queries"]
    known_sections = {
        document["section_id"] for document in suite["documents"]
    }
    if set(rankings) != {query["query_id"] for query in queries}:
        raise BenchmarkCorrectionError("ranking query coverage mismatch")
    gold_by_query = {item["query_id"]: item for item in gold["queries"]}
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    cross_language: list[float] = []
    not_found: list[float] = []
    per_query: list[dict[str, Any]] = []

    for query in queries:
        query_id = query["query_id"]
        ranking = list(rankings[query_id])
        if len(ranking) != len(set(ranking)):
            raise BenchmarkCorrectionError(
                f"duplicate ranked section for {query_id}"
            )
        unknown = sorted(set(ranking) - known_sections)
        if unknown:
            raise BenchmarkCorrectionError(
                f"ranking contains unknown sections for {query_id}: {unknown}"
            )
        ranked_articles: list[str] = []
        for section_id in ranking:
            candidate = article_id(section_id)
            if candidate not in ranked_articles:
                ranked_articles.append(candidate)

        expected = set(gold_by_query[query_id]["expected_article_ids"])
        if query["expect_not_found"]:
            correct = not ranked_articles
            not_found.append(float(correct))
            per_query.append(
                {
                    "query_id": query_id,
                    "expect_not_found": True,
                    "correct": correct,
                    "ranked_article_ids": ranked_articles,
                }
            )
            continue

        top = ranked_articles[:k]
        recall = len(expected.intersection(top)) / len(expected)
        first = next(
            (
                rank
                for rank, candidate in enumerate(ranked_articles, start=1)
                if candidate in expected
            ),
            None,
        )
        reciprocal_rank = 0.0 if first is None else 1.0 / first
        dcg = math.fsum(
            1.0 / math.log2(index + 2)
            for index, candidate in enumerate(top)
            if candidate in expected
        )
        ideal = math.fsum(
            1.0 / math.log2(index + 2)
            for index in range(min(len(expected), k))
        )
        ndcg = 0.0 if ideal == 0 else dcg / ideal
        recalls.append(recall)
        reciprocal_ranks.append(reciprocal_rank)
        ndcgs.append(ndcg)
        if query["kind"] in {"zh-to-en", "en-to-zh"}:
            cross_language.append(recall)
        per_query.append(
            {
                "query_id": query_id,
                "expect_not_found": False,
                "expected_article_ids": sorted(expected),
                "ranked_article_ids": ranked_articles,
                "recall_at_3": round(recall, 6),
                "reciprocal_rank": round(reciprocal_rank, 6),
                "ndcg_at_3": round(ndcg, 6),
            }
        )

    def average(values: Sequence[float]) -> float:
        return 0.0 if not values else math.fsum(values) / len(values)

    return {
        "evaluation_unit": "parent-article",
        "k": k,
        "query_count": len(queries),
        "answered_query_count": len(recalls),
        "recall_at_3": round(average(recalls), 6),
        "mean_reciprocal_rank": round(average(reciprocal_ranks), 6),
        "ndcg_at_3": round(average(ndcgs), 6),
        "cross_language_recall_at_3": round(
            average(cross_language), 6
        ),
        "not_found_accuracy": round(average(not_found), 6),
        "per_query": per_query,
    }


def evaluate_exact_section_diagnostic(
    suite: Mapping[str, Any],
    rankings: Mapping[str, Sequence[str]],
    *,
    k: int = 5,
) -> dict[str, Any]:
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    cross_language: list[float] = []
    not_found: list[float] = []
    for query in suite["queries"]:
        ranking = list(rankings[query["query_id"]])
        if query["expect_not_found"]:
            not_found.append(float(not ranking))
            continue
        expected = set(query["expected_section_ids"])
        recall = len(expected.intersection(ranking[:k])) / len(expected)
        recalls.append(recall)
        first = next(
            (
                rank
                for rank, section_id in enumerate(ranking, start=1)
                if section_id in expected
            ),
            None,
        )
        reciprocal_ranks.append(0.0 if first is None else 1.0 / first)
        if query["kind"] in {"zh-to-en", "en-to-zh"}:
            cross_language.append(recall)

    def average(values: Sequence[float]) -> float:
        return 0.0 if not values else math.fsum(values) / len(values)

    return {
        "evaluation_unit": "exact-section-diagnostic",
        "k": k,
        "recall_at_5": round(average(recalls), 6),
        "mean_reciprocal_rank": round(average(reciprocal_ranks), 6),
        "cross_language_recall_at_5": round(
            average(cross_language), 6
        ),
        "not_found_accuracy": round(average(not_found), 6),
        "acceptance_authority": False,
        "reason": "legacy section gold labels point to article chunk-000",
    }


def evaluate_held_out_abstention(
    gold: Mapping[str, Any],
    top_scores: Mapping[str, float],
    *,
    threshold: float,
) -> dict[str, Any]:
    roles = {
        item["query_id"]: item["evaluation_role"] for item in gold["queries"]
    }
    positives = [
        top_scores[query_id]
        for query_id, role in roles.items()
        if role == "held-out-positive"
    ]
    negatives = [
        top_scores[query_id]
        for query_id, role in roles.items()
        if role == "held-out-negative"
    ]
    if not positives or not negatives:
        raise BenchmarkCorrectionError(
            "held-out evaluation needs positives and negatives"
        )
    positive_correct = sum(score >= threshold for score in positives)
    negative_correct = sum(score < threshold for score in negatives)
    total = len(positives) + len(negatives)
    maximum_negative = max(negatives)
    minimum_positive = min(positives)
    clearance = threshold - maximum_negative
    return {
        "held_out_positive_count": len(positives),
        "held_out_negative_count": len(negatives),
        "accuracy": round(
            (positive_correct + negative_correct) / total, 6
        ),
        "minimum_positive_top_score": minimum_positive,
        "maximum_negative_top_score": maximum_negative,
        "separation_margin": minimum_positive - maximum_negative,
        "negative_threshold_clearance": clearance,
        "all_positive_above_threshold": positive_correct == len(positives),
        "all_negative_below_threshold": negative_correct == len(negatives),
    }
