from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any

GOLD_SCHEMA = "knowledge-engine-m23-retrieval-gold/v1"
RESULT_SCHEMA = "knowledge-engine-m23-corrected-benchmark-result/v1"
DECISION_SCHEMA = "knowledge-engine-m23-model-selection-decision/v1"
RECEIPT_SCHEMA = "knowledge-engine-m23-offline-rebenchmark-receipt/v1"
ALLOWED_ROLES = {
    "threshold-calibration-positive",
    "threshold-calibration-negative",
    "held-out-positive",
    "held-out-negative",
}
VECTOR_DIMENSION = 1024
MAX_ITEMS = 10_000


class BenchmarkCorrectionError(ValueError):
    """Raised when M23.5 corrected benchmark evidence is invalid."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def required_string(value: Any, label: str, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise BenchmarkCorrectionError(f"{label} must be a string")
    candidate = value.strip()
    if not candidate or len(candidate) > maximum:
        raise BenchmarkCorrectionError(
            f"{label} must contain 1 to {maximum} characters"
        )
    return candidate


def required_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise BenchmarkCorrectionError(f"{label} must be a boolean")
    return value


def string_list(value: Any, label: str, maximum: int = 100) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise BenchmarkCorrectionError(
            f"{label} must be an array with at most {maximum} items"
        )
    result = [required_string(item, f"{label}[]", 300) for item in value]
    if len(result) != len(set(result)):
        raise BenchmarkCorrectionError(f"{label} must contain unique values")
    return result


def article_id(section_id: str) -> str:
    section = required_string(section_id, "section_id", 300)
    marker = "/chunk-"
    if marker not in section:
        raise BenchmarkCorrectionError(f"section_id has no chunk suffix: {section}")
    return section.split(marker, 1)[0]


def validate_gold(
    suite: Mapping[str, Any], raw: Mapping[str, Any]
) -> dict[str, Any]:
    schema = required_string(raw.get("schema_version"), "schema_version")
    if schema != GOLD_SCHEMA:
        raise BenchmarkCorrectionError(
            f"unsupported corrected-gold schema: {schema}"
        )
    if required_string(raw.get("suite_id"), "suite_id", 200) != suite.get(
        "suite_id"
    ):
        raise BenchmarkCorrectionError("corrected gold suite_id mismatch")
    if required_string(
        raw.get("suite_revision"), "suite_revision", 100
    ) != suite.get("suite_revision"):
        raise BenchmarkCorrectionError("corrected gold suite_revision mismatch")
    suite_sha = required_string(
        raw.get("benchmark_suite_sha256"), "benchmark_suite_sha256", 64
    )
    if suite_sha != canonical_sha256(suite):
        raise BenchmarkCorrectionError(
            "corrected gold benchmark suite digest mismatch"
        )

    documents = suite.get("documents")
    queries = suite.get("queries")
    if not isinstance(documents, list) or not documents:
        raise BenchmarkCorrectionError("benchmark suite must contain documents")
    if not isinstance(queries, list) or not queries:
        raise BenchmarkCorrectionError("benchmark suite must contain queries")
    known_queries = {query.get("query_id"): query for query in queries}
    if None in known_queries:
        raise BenchmarkCorrectionError("benchmark query is missing query_id")
    known_articles = {
        article_id(document.get("section_id")) for document in documents
    }
    known_audiences = {
        required_string(document.get("audience"), "document.audience", 40)
        for document in documents
    }

    raw_queries = raw.get("queries")
    if not isinstance(raw_queries, list) or len(raw_queries) > MAX_ITEMS:
        raise BenchmarkCorrectionError(
            "corrected gold queries must be a bounded array"
        )
    validated: list[dict[str, Any]] = []
    for item in raw_queries:
        if not isinstance(item, Mapping):
            raise BenchmarkCorrectionError(
                "corrected gold query must be an object"
            )
        query_id = required_string(item.get("query_id"), "query_id", 200)
        if query_id not in known_queries:
            raise BenchmarkCorrectionError(
                f"corrected gold references unknown query: {query_id}"
            )
        role = required_string(
            item.get("evaluation_role"), "evaluation_role", 80
        )
        if role not in ALLOWED_ROLES:
            raise BenchmarkCorrectionError(
                f"unsupported evaluation role: {role}"
            )
        expected_articles = string_list(
            item.get("expected_article_ids"), "expected_article_ids", 20
        )
        unknown_articles = sorted(set(expected_articles) - known_articles)
        if unknown_articles:
            raise BenchmarkCorrectionError(
                f"corrected gold references unknown articles: {unknown_articles}"
            )
        benchmark_query = known_queries[query_id]
        expect_not_found = benchmark_query.get("expect_not_found")
        if expect_not_found == bool(expected_articles):
            raise BenchmarkCorrectionError(
                "not-found queries need no expected articles and answered "
                "queries need one"
            )
        derived = sorted(
            {
                article_id(section_id)
                for section_id in benchmark_query["expected_section_ids"]
            }
        )
        if expected_articles != derived:
            raise BenchmarkCorrectionError(
                "expected_article_ids must preserve section-derived article "
                f"labels for {query_id}"
            )
        probe_audiences = string_list(
            item.get("semantic_probe_audiences"),
            "semantic_probe_audiences",
            10,
        )
        unknown_audiences = sorted(set(probe_audiences) - known_audiences)
        if unknown_audiences:
            raise BenchmarkCorrectionError(
                f"semantic probe references unknown audiences: {unknown_audiences}"
            )
        if not probe_audiences:
            raise BenchmarkCorrectionError(
                "semantic_probe_audiences must not be empty"
            )
        validated.append(
            {
                "query_id": query_id,
                "expected_article_ids": expected_articles,
                "evaluation_role": role,
                "semantic_probe_audiences": sorted(probe_audiences),
            }
        )

    query_ids = [item["query_id"] for item in validated]
    if len(query_ids) != len(set(query_ids)):
        raise BenchmarkCorrectionError(
            "corrected gold query IDs must be unique"
        )
    if set(query_ids) != set(known_queries):
        raise BenchmarkCorrectionError(
            "corrected gold must cover every benchmark query"
        )
    roles = {item["evaluation_role"] for item in validated}
    if roles != ALLOWED_ROLES:
        raise BenchmarkCorrectionError(
            "corrected gold must contain all evaluation roles: "
            f"{sorted(ALLOWED_ROLES)}"
        )

    return {
        "schema_version": GOLD_SCHEMA,
        "suite_id": suite["suite_id"],
        "suite_revision": suite["suite_revision"],
        "benchmark_suite_sha256": suite_sha,
        "article_id_derivation": required_string(
            raw.get("article_id_derivation"),
            "article_id_derivation",
            200,
        ),
        "queries": sorted(validated, key=lambda item: item["query_id"]),
        "read_only": required_bool(raw.get("read_only"), "read_only"),
        "production_authority": required_bool(
            raw.get("production_authority"), "production_authority"
        ),
    }


def read_float32_vectors(
    data: bytes,
    *,
    row_count: int,
    dimension: int = VECTOR_DIMENSION,
) -> list[list[float]]:
    expected_bytes = row_count * dimension * 4
    if len(data) != expected_bytes:
        raise BenchmarkCorrectionError(
            f"vector byte length mismatch: expected {expected_bytes}, "
            f"got {len(data)}"
        )
    values = struct.unpack(f"<{row_count * dimension}f", data)
    vectors = [
        list(values[row * dimension : (row + 1) * dimension])
        for row in range(row_count)
    ]
    for row, vector in enumerate(vectors):
        if not all(math.isfinite(value) for value in vector):
            raise BenchmarkCorrectionError(
                f"vector row {row} contains non-finite values"
            )
        norm = math.sqrt(math.fsum(value * value for value in vector))
        if abs(norm - 1.0) > 1e-4:
            raise BenchmarkCorrectionError(
                f"vector row {row} is not L2-normalized; norm={norm:.8f}"
            )
    return vectors


# Public facade imports are placed last to keep the validation core acyclic.
from .m23_benchmark_decision import build_decision  # noqa: E402
from .m23_benchmark_evaluation import (  # noqa: E402
    calibrate_threshold,
    evaluate_article_rankings,
    evaluate_exact_section_diagnostic,
    evaluate_held_out_abstention,
    reciprocal_rank_fusion,
    semantic_top_scores,
    vector_rankings,
)
from .m23_benchmark_offline import run_offline_rebenchmark  # noqa: E402
