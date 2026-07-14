from __future__ import annotations

import hashlib
import math
import struct

import pytest
from src.knowledge_engine.m23_benchmark_correction import (
    BenchmarkCorrectionError,
    build_decision,
    calibrate_threshold,
    canonical_sha256,
    evaluate_article_rankings,
    evaluate_exact_section_diagnostic,
    evaluate_held_out_abstention,
    read_float32_vectors,
    semantic_top_scores,
    validate_gold,
    vector_rankings,
)


def _document(section_id: str, audience: str = "public"):
    text = f"text for {section_id}"
    return {
        "section_id": section_id,
        "concept_id": section_id.split("/chunk-", 1)[0],
        "language": "en",
        "title": section_id,
        "text": text,
        "source_path": f"{section_id}.md",
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "audience": audience,
    }


def _suite():
    documents = [
        _document("article-a/chunk-000"),
        _document("article-a/chunk-001"),
        _document("article-b/chunk-000"),
        _document("article-b/chunk-001"),
    ]
    queries = [
        {
            "query_id": "q-cal-pos",
            "language": "en",
            "kind": "exact-name",
            "text": "article a",
            "expected_section_ids": ["article-a/chunk-000"],
            "expect_not_found": False,
            "allowed_audiences": ["public"],
        },
        {
            "query_id": "q-cal-neg",
            "language": "en",
            "kind": "not-found",
            "text": "nothing here",
            "expected_section_ids": [],
            "expect_not_found": True,
            "allowed_audiences": ["public"],
        },
        {
            "query_id": "q-held-pos",
            "language": "en",
            "kind": "paraphrase",
            "text": "article b",
            "expected_section_ids": ["article-b/chunk-000"],
            "expect_not_found": False,
            "allowed_audiences": ["public"],
        },
        {
            "query_id": "q-held-neg",
            "language": "en",
            "kind": "acl-negative",
            "text": "private credentials",
            "expected_section_ids": [],
            "expect_not_found": True,
            "allowed_audiences": [],
        },
    ]
    return {
        "schema_version": "knowledge-os-bilingual-blog-benchmark/v1",
        "suite_id": "suite",
        "suite_revision": "1",
        "identities": {
            "engine_baseline_sha": "1" * 40,
            "source_commit_sha": "2" * 40,
            "foundation_commit_sha": "3" * 40,
        },
        "documents": documents,
        "queries": queries,
        "read_only": True,
        "production_authority": False,
    }


def _gold(suite):
    return {
        "schema_version": "knowledge-engine-m23-retrieval-gold/v1",
        "suite_id": "suite",
        "suite_revision": "1",
        "benchmark_suite_sha256": canonical_sha256(suite),
        "article_id_derivation": "section_id before /chunk-",
        "queries": [
            {
                "query_id": "q-cal-pos",
                "expected_article_ids": ["article-a"],
                "evaluation_role": "threshold-calibration-positive",
                "semantic_probe_audiences": ["public"],
            },
            {
                "query_id": "q-cal-neg",
                "expected_article_ids": [],
                "evaluation_role": "threshold-calibration-negative",
                "semantic_probe_audiences": ["public"],
            },
            {
                "query_id": "q-held-pos",
                "expected_article_ids": ["article-b"],
                "evaluation_role": "held-out-positive",
                "semantic_probe_audiences": ["public"],
            },
            {
                "query_id": "q-held-neg",
                "expected_article_ids": [],
                "evaluation_role": "held-out-negative",
                "semantic_probe_audiences": ["public"],
            },
        ],
        "read_only": True,
        "production_authority": False,
    }


def test_corrected_gold_preserves_section_derived_article_labels():
    suite = _suite()
    gold = validate_gold(suite, _gold(suite))
    by_query = {item["query_id"]: item for item in gold["queries"]}
    assert by_query["q-cal-pos"]["expected_article_ids"] == ["article-a"]

    broken = _gold(suite)
    broken["queries"][0]["expected_article_ids"] = ["article-b"]
    with pytest.raises(BenchmarkCorrectionError, match="preserve"):
        validate_gold(suite, broken)


def test_threshold_is_calibrated_separately_and_held_out():
    suite = _suite()
    gold = validate_gold(suite, _gold(suite))
    document_vectors = [
        [1.0, 0.0],
        [0.9, math.sqrt(0.19)],
        [0.0, 1.0],
        [math.sqrt(0.19), 0.9],
    ]
    query_vectors = [
        [1.0, 0.0],
        [-1.0, 0.0],
        [0.0, 1.0],
        [-0.8, -0.6],
    ]
    scores = semantic_top_scores(suite, gold, document_vectors, query_vectors)
    calibration = calibrate_threshold(gold, scores)
    assert calibration["threshold"] > scores["q-cal-neg"]
    assert calibration["threshold"] < scores["q-cal-pos"]

    held_out = evaluate_held_out_abstention(
        gold, scores, threshold=calibration["threshold"]
    )
    assert held_out["accuracy"] == 1.0
    assert held_out["all_positive_above_threshold"] is True
    assert held_out["all_negative_below_threshold"] is True


def test_article_acceptance_does_not_replace_exact_section_diagnostic():
    suite = _suite()
    gold = validate_gold(suite, _gold(suite))
    rankings = {
        "q-cal-pos": ["article-a/chunk-001"],
        "q-cal-neg": [],
        "q-held-pos": ["article-b/chunk-001"],
        "q-held-neg": [],
    }
    article = evaluate_article_rankings(suite, gold, rankings)
    section = evaluate_exact_section_diagnostic(suite, rankings)
    assert article["recall_at_3"] == 1.0
    assert section["recall_at_5"] == 0.0
    assert section["acceptance_authority"] is False


def test_vector_rankings_respect_runtime_acl():
    suite = _suite()
    document_vectors = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [0.1, 0.9]]
    query_vectors = [[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
    rankings = vector_rankings(
        suite, document_vectors, query_vectors, threshold=0.5
    )
    assert rankings["q-cal-pos"][0].startswith("article-a/")
    assert rankings["q-held-pos"][0].startswith("article-b/")
    assert rankings["q-held-neg"] == []


def test_float32_reader_checks_size_and_norm():
    unit = [0.0] * 1023 + [1.0]
    data = struct.pack("<1024f", *unit)
    assert read_float32_vectors(data, row_count=1)[0][-1] == 1.0
    with pytest.raises(BenchmarkCorrectionError, match="byte length"):
        read_float32_vectors(data[:-4], row_count=1)


def test_decision_selects_provider_but_blocks_abstention_promotion():
    methods = {
        "vector": {
            "evaluation_unit": "parent-article",
            "k": 3,
            "query_count": 16,
            "answered_query_count": 14,
            "recall_at_3": 0.714286,
            "mean_reciprocal_rank": 0.964286,
            "ndcg_at_3": 0.829664,
            "cross_language_recall_at_3": 0.9375,
            "not_found_accuracy": 1.0,
        }
    }
    calibration = {"separation_margin": 0.13}
    held_out = {
        "accuracy": 1.0,
        "held_out_negative_count": 1,
        "negative_threshold_clearance": 0.001,
        "separation_margin": 0.02,
    }
    decision = build_decision(
        source_evidence_sha256="a" * 64,
        source_semantic_artifact_id="semantic-test",
        corrected_gold_sha256="b" * 64,
        methods=methods,
        calibration=calibration,
        held_out=held_out,
    )
    assert decision["decision"] == "select_for_non_production_pilot"
    assert decision["provider_selection_pass"] is True
    assert decision["abstention_promotion_pass"] is False
    assert decision["retrieval_default"] == "lexical"
    assert decision["qdrant_pilot_write_authorized"] is False
