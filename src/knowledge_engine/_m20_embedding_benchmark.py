from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._m20_embedding_common import (
    ContractError,
    _bounded_int,
    _git_sha,
    _mapping,
    _required_bool,
    _required_string,
    _sequence,
    _sha256,
    canonical_sha256,
    validate_provider_contract,
)

BILINGUAL_BENCHMARK_SCHEMA = "knowledge-os-bilingual-blog-benchmark/v1"
BENCHMARK_RESULT_SCHEMA = "knowledge-os-embedding-benchmark-result/v1"
MAX_DOCUMENTS = 10_000
MAX_QUERIES = 10_000
MAX_TEXT_LENGTH = 64_000
_ALLOWED_LANGUAGE = {"en", "zh-TW", "mixed"}
_ALLOWED_QUERY_KINDS = {
    "exact-name",
    "paraphrase",
    "zh-to-en",
    "en-to-zh",
    "comparison",
    "dependency",
    "ambiguous",
    "not-found",
    "acl-negative",
}


@dataclass(frozen=True)
class BenchmarkMetrics:
    query_count: int
    answered_query_count: int
    recall_at_k: float
    mean_reciprocal_rank: float
    not_found_accuracy: float
    exact_name_recall_at_k: float
    paraphrase_recall_at_k: float
    cross_language_recall_at_k: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_count": self.query_count,
            "answered_query_count": self.answered_query_count,
            "recall_at_k": round(self.recall_at_k, 6),
            "mean_reciprocal_rank": round(self.mean_reciprocal_rank, 6),
            "not_found_accuracy": round(self.not_found_accuracy, 6),
            "exact_name_recall_at_k": round(self.exact_name_recall_at_k, 6),
            "paraphrase_recall_at_k": round(self.paraphrase_recall_at_k, 6),
            "cross_language_recall_at_k": round(self.cross_language_recall_at_k, 6),
        }


def _normalise_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _tokens(value: str) -> list[str]:
    normalised = _normalise_text(value)
    latin = re.findall(r"[a-z0-9][a-z0-9._/-]*", normalised)
    han = re.findall(r"[\u3400-\u9fff]", normalised)
    han_bigrams = ["".join(han[index : index + 2]) for index in range(max(0, len(han) - 1))]
    return latin + han + han_bigrams


def _validate_document(raw: Mapping[str, Any]) -> dict[str, Any]:
    language = _required_string(raw.get("language"), "document.language", 20)
    if language not in _ALLOWED_LANGUAGE:
        raise ContractError(f"unsupported document language: {language}")
    text = _required_string(raw.get("text"), "document.text", MAX_TEXT_LENGTH)
    section_id = _required_string(raw.get("section_id"), "document.section_id", 300)
    return {
        "section_id": section_id,
        "concept_id": _required_string(raw.get("concept_id"), "document.concept_id", 300),
        "language": language,
        "title": _required_string(raw.get("title"), "document.title", 500),
        "text": text,
        "source_path": _required_string(raw.get("source_path"), "document.source_path", 500),
        "source_sha256": _sha256(raw.get("source_sha256"), "document.source_sha256"),
        "audience": _required_string(raw.get("audience"), "document.audience", 40),
    }


def _validate_query(raw: Mapping[str, Any], document_ids: set[str]) -> dict[str, Any]:
    kind = _required_string(raw.get("kind"), "query.kind", 40)
    if kind not in _ALLOWED_QUERY_KINDS:
        raise ContractError(f"unsupported query kind: {kind}")
    language = _required_string(raw.get("language"), "query.language", 20)
    if language not in _ALLOWED_LANGUAGE:
        raise ContractError(f"unsupported query language: {language}")
    expected = _sequence(raw.get("expected_section_ids"), "query.expected_section_ids", 20)
    expected_ids = [_required_string(item, "query.expected_section_id", 300) for item in expected]
    if len(expected_ids) != len(set(expected_ids)):
        raise ContractError("query expected_section_ids must be unique")
    missing = sorted(set(expected_ids) - document_ids)
    if missing:
        raise ContractError(f"query references unknown sections: {missing}")
    expect_not_found = _required_bool(raw.get("expect_not_found"), "query.expect_not_found")
    if expect_not_found == bool(expected_ids):
        raise ContractError(
            "not-found queries must have no expected sections and answered queries need one"
        )
    return {
        "query_id": _required_string(raw.get("query_id"), "query.query_id", 200),
        "language": language,
        "kind": kind,
        "text": _required_string(raw.get("text"), "query.text", 2_000),
        "expected_section_ids": expected_ids,
        "expect_not_found": expect_not_found,
        "allowed_audiences": sorted(
            {
                _required_string(item, "query.allowed_audience", 40)
                for item in _sequence(raw.get("allowed_audiences"), "query.allowed_audiences", 10)
            }
        ),
    }


def validate_benchmark_suite(raw: Mapping[str, Any]) -> dict[str, Any]:
    schema = _required_string(raw.get("schema_version"), "schema_version")
    if schema != BILINGUAL_BENCHMARK_SCHEMA:
        raise ContractError(f"unsupported bilingual benchmark schema: {schema}")
    identities = _mapping(raw.get("identities"), "identities")
    documents_raw = _sequence(raw.get("documents"), "documents", MAX_DOCUMENTS)
    queries_raw = _sequence(raw.get("queries"), "queries", MAX_QUERIES)
    if len(documents_raw) < 4 or len(queries_raw) < 8:
        raise ContractError("benchmark requires at least four documents and eight queries")

    documents = [_validate_document(_mapping(item, "document")) for item in documents_raw]
    section_ids = [item["section_id"] for item in documents]
    if len(section_ids) != len(set(section_ids)):
        raise ContractError("document section IDs must be unique")
    for item in documents:
        expected_hash = hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
        if expected_hash != item["source_sha256"]:
            raise ContractError(f"document hash mismatch for {item['section_id']}")

    queries = [_validate_query(_mapping(item, "query"), set(section_ids)) for item in queries_raw]
    query_ids = [item["query_id"] for item in queries]
    if len(query_ids) != len(set(query_ids)):
        raise ContractError("query IDs must be unique")
    query_kinds = {item["kind"] for item in queries}
    required_kinds = {"exact-name", "paraphrase", "zh-to-en", "en-to-zh", "not-found"}
    if not required_kinds.issubset(query_kinds):
        raise ContractError(
            f"benchmark missing required query kinds: {sorted(required_kinds - query_kinds)}"
        )
    document_languages = {item["language"] for item in documents}
    if not {"en", "zh-TW"}.issubset(document_languages):
        raise ContractError("benchmark must contain English and Traditional Chinese documents")

    return {
        "schema_version": BILINGUAL_BENCHMARK_SCHEMA,
        "suite_id": _required_string(raw.get("suite_id"), "suite_id", 200),
        "suite_revision": _required_string(raw.get("suite_revision"), "suite_revision", 100),
        "identities": {
            "engine_baseline_sha": _git_sha(
                identities.get("engine_baseline_sha"), "identities.engine_baseline_sha"
            ),
            "source_commit_sha": _git_sha(
                identities.get("source_commit_sha"), "identities.source_commit_sha"
            ),
            "foundation_commit_sha": _git_sha(
                identities.get("foundation_commit_sha"), "identities.foundation_commit_sha"
            ),
        },
        "documents": sorted(documents, key=lambda item: item["section_id"]),
        "queries": sorted(queries, key=lambda item: item["query_id"]),
        "read_only": _required_bool(raw.get("read_only"), "read_only"),
        "production_authority": _required_bool(
            raw.get("production_authority"), "production_authority"
        ),
    }


def load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError("JSON root must be an object")
    return value


def lexical_rankings(
    suite: Mapping[str, Any], *, limit: int = 10
) -> dict[str, list[str]]:
    validated = validate_benchmark_suite(suite)
    limit = _bounded_int(limit, "limit", 1, 100)
    documents = validated["documents"]
    rankings: dict[str, list[str]] = {}
    for query in validated["queries"]:
        allowed = set(query["allowed_audiences"])
        query_text = _normalise_text(query["text"])
        query_tokens = Counter(_tokens(query["text"]))
        scored: list[tuple[float, str]] = []
        for document in documents:
            if document["audience"] not in allowed:
                continue
            haystack = _normalise_text(
                f"{document['title']} {document['text']} {document['concept_id']}"
            )
            document_tokens = Counter(_tokens(haystack))
            overlap = sum((query_tokens & document_tokens).values())
            exact = 20.0 if query_text and query_text in haystack else 0.0
            title = _normalise_text(document["title"])
            title_bonus = 8.0 if query_text and query_text in title else 0.0
            score = exact + title_bonus + float(overlap)
            if score > 0:
                scored.append((score, document["section_id"]))
        scored.sort(key=lambda item: (-item[0], item[1]))
        rankings[query["query_id"]] = [section_id for _, section_id in scored[:limit]]
    return rankings


def _recall(expected: set[str], ranking: Sequence[str], k: int) -> float:
    if not expected:
        return 0.0
    return len(expected.intersection(ranking[:k])) / len(expected)


def evaluate_rankings(
    suite: Mapping[str, Any], rankings: Mapping[str, Sequence[str]], *, k: int = 5
) -> BenchmarkMetrics:
    validated = validate_benchmark_suite(suite)
    k = _bounded_int(k, "k", 1, 100)
    known_sections = {item["section_id"] for item in validated["documents"]}
    query_ids = {item["query_id"] for item in validated["queries"]}
    if set(rankings) != query_ids:
        missing = sorted(query_ids - set(rankings))
        extra = sorted(set(rankings) - query_ids)
        raise ContractError(f"rankings query coverage mismatch; missing={missing}, extra={extra}")

    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    not_found: list[float] = []
    by_kind: dict[str, list[float]] = {}
    answered = 0
    for query in validated["queries"]:
        ranking = list(rankings[query["query_id"]])
        if len(ranking) != len(set(ranking)):
            raise ContractError(f"ranking contains duplicate sections for {query['query_id']}")
        unknown = sorted(set(ranking) - known_sections)
        if unknown:
            raise ContractError(
                f"ranking contains unknown sections for {query['query_id']}: {unknown}"
            )
        if query["expect_not_found"]:
            not_found.append(1.0 if not ranking else 0.0)
            continue
        answered += 1
        expected = set(query["expected_section_ids"])
        recall = _recall(expected, ranking, k)
        recalls.append(recall)
        by_kind.setdefault(query["kind"], []).append(recall)
        first = next((index + 1 for index, item in enumerate(ranking) if item in expected), None)
        reciprocal_ranks.append(0.0 if first is None else 1.0 / first)

    def average(values: Iterable[float]) -> float:
        items = list(values)
        return 0.0 if not items else sum(items) / len(items)

    return BenchmarkMetrics(
        query_count=len(validated["queries"]),
        answered_query_count=answered,
        recall_at_k=average(recalls),
        mean_reciprocal_rank=average(reciprocal_ranks),
        not_found_accuracy=average(not_found),
        exact_name_recall_at_k=average(by_kind.get("exact-name", [])),
        paraphrase_recall_at_k=average(by_kind.get("paraphrase", [])),
        cross_language_recall_at_k=average(
            by_kind.get("zh-to-en", []) + by_kind.get("en-to-zh", [])
        ),
    )


def benchmark_result(
    suite: Mapping[str, Any],
    rankings: Mapping[str, Sequence[str]],
    *,
    method: str,
    k: int = 5,
    provider_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    validated_suite = validate_benchmark_suite(suite)
    metrics = evaluate_rankings(validated_suite, rankings, k=k)
    contract = None
    if provider_contract is not None:
        contract = validate_provider_contract(provider_contract)
        suite_identities = validated_suite["identities"]
        contract_identities = contract["identities"]
        expected = {
            "engine_commit_sha": suite_identities["engine_baseline_sha"],
            "source_commit_sha": suite_identities["source_commit_sha"],
            "foundation_commit_sha": suite_identities["foundation_commit_sha"],
        }
        if contract_identities != expected:
            raise ContractError("provider and benchmark identities do not match")
    payload = {
        "schema_version": BENCHMARK_RESULT_SCHEMA,
        "suite_id": validated_suite["suite_id"],
        "suite_revision": validated_suite["suite_revision"],
        "suite_sha256": canonical_sha256(validated_suite),
        "method": _required_string(method, "method", 200),
        "k": k,
        "metrics": metrics.to_dict(),
        "rankings": {key: list(rankings[key]) for key in sorted(rankings)},
        "provider_contract_sha256": (
            canonical_sha256(contract) if contract is not None else None
        ),
        "read_only": True,
        "production_authority": False,
    }
    payload["result_sha256"] = canonical_sha256(payload)
    return payload


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        raise ContractError("vectors must be non-empty and have identical dimensions")
    if not all(math.isfinite(value) for value in [*left, *right]):
        raise ContractError("vectors must contain finite values")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ContractError("vectors must have non-zero norm")
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
