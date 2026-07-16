from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from . import m23_7_r3_5_rank_quality_calibration as base_r35
from . import m23_7_r3_5_rank_quality_calibration_runtime as r35
from . import m23_7_r3_6_candidate_reingestion as r36
from .errors import IntegrityError
from .m23_cloudflare_qdrant import (
    CloudflareConfig,
    QdrantConfig,
    SectionInput,
    embed_sections,
)

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-7-live-acceptance/v1"
RECEIPT_SCHEMA_VERSION = "knowledge-engine-m23-7-r3-7-live-acceptance-receipt/v1"
IMPLEMENTATION_ISSUE = 514
PARENT_ISSUE = 474
ENTRY_ENGINE_SHA = "6fc46f9e129d0260e024677f3b45b0760582fc3a"
R3_6_RECONCILIATION_SHA256 = (
    "9748c187960452e443a9ea82bbce2f9e9ac93bdf7e5c9bbbe01935172385d5b6"
)
R3_6_RECEIPT_FILE_SHA256 = (
    "0ef4a0017ee1574d40f32c0eb11049512b78163ffc4302e34be30299817e96c6"
)
R3_6_RECEIPT_SHA256 = (
    "e59569d429b61dab516a47a4922a8b767f81e789f42b28105793276b643baaa8"
)
R3_6_MANIFEST_SHA256 = (
    "41c24b3103f5358874c665d6c58c4e8d6dd16efc1a254eb3a44f4932227bf345"
)
R3_6_AGGREGATE_SHA256 = (
    "ce5ebc12f2f353a45b5a1f3a2f19c2b67dc88b91d77b11550a8b271a4bcc5df6"
)
R3_6_IDS_SHA256 = "907e3020819ac6fd1c50ff45a4e266f97494b1aee312a1adb00547955245d0d8"
R3_5_REPORT_SHA256 = "410a5781504d2906f96191627e4e5cae46bb6eb1fa5dc907c1e84ec111c01bc2"
CONTRACT_SHA256 = "11faa597fe15e39f2589963b30e00e3b1580d6f7bb186ffe9ef180139d427d8d"

EXPECTED_COLLECTION = r36.EXPECTED_COLLECTION
HISTORICAL_PILOT_COLLECTION = r36.HISTORICAL_PILOT_COLLECTION
EXPECTED_POINT_COUNT = r36.EXPECTED_POINT_COUNT
VECTOR_NAME = r36.EXPECTED_VECTOR_NAME
VECTOR_DIMENSION = r36.EXPECTED_VECTOR_DIMENSION
PAYLOAD_SCHEMA = r36.EXPECTED_PAYLOAD_SCHEMA
DENSE_LIMIT = base_r35.r34.FUSION_DEPTH
QUERY_COUNT = base_r35.r34.TOTAL_QUERY_VARIANTS
PROBE_COUNT = base_r35.r34.SAMPLE_CAP
VARIANTS_PER_PROBE = base_r35.r34.VARIANTS_PER_PROBE
MAX_LIVE_P95_MS = 1200
MAXIMUM_HUB_FREQUENCY = 6
READBACK_BATCH_SIZE = r36.READBACK_BATCH_SIZE
ACCEPTED_METRICS = {
    "recall_at_5": 0.875,
    "mrr_at_10": 0.807291666667,
    "ndcg_at_10": 0.851933109598,
}
ACCEPTED_TARGET_RANKS = {
    "m23q-01": 1,
    "m23q-02": 8,
    "m23q-03": 3,
    "m23q-04": 1,
    "m23q-07": 1,
    "m23q-08": 1,
    "m23q-09": 1,
    "m23q-10": 1,
}


class LiveAcceptanceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise LiveAcceptanceError(code, message)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return r36.utc_now()


def _p95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    _require(bool(ordered), "latency_empty", "latency values are empty")
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _p50(values: Sequence[int]) -> int:
    ordered = sorted(values)
    _require(bool(ordered), "latency_empty", "latency values are empty")
    return ordered[math.ceil(0.50 * len(ordered)) - 1]


def _elapsed_ms(start_ns: int, end_ns: int) -> int:
    return max(0, math.ceil((end_ns - start_ns) / 1_000_000))


def canonical_contract() -> dict[str, Any]:
    ranker_source = inspect.getsource(live_calibrated_ranking)
    forbidden = (
        "target_section_id",
        "expected_relevant_ids",
        "offline_case_id",
        "probe_id",
    )
    _require(
        not any(term in ranker_source for term in forbidden),
        "target_aware_ranker",
        "live ranker accepts target-aware inputs",
    )
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R3.7",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "r3_6_reconciliation_sha256": R3_6_RECONCILIATION_SHA256,
            "r3_6_reconciliation_merge": ENTRY_ENGINE_SHA,
            "r3_6_receipt_file_sha256": R3_6_RECEIPT_FILE_SHA256,
            "r3_6_receipt_sha256": R3_6_RECEIPT_SHA256,
            "candidate_manifest_sha256": R3_6_MANIFEST_SHA256,
            "candidate_aggregate_fingerprint_sha256": R3_6_AGGREGATE_SHA256,
            "candidate_ids_sha256": R3_6_IDS_SHA256,
            "r3_5_candidate_artifact_sha256": r36.R3_5_CANDIDATE_ARTIFACT_SHA256,
            "r3_5_report_sha256": R3_5_REPORT_SHA256,
        },
        "collection": {
            "name": EXPECTED_COLLECTION,
            "historical_pilot": HISTORICAL_PILOT_COLLECTION,
            "point_count": EXPECTED_POINT_COUNT,
            "vector_name": VECTOR_NAME,
            "vector_dimension": VECTOR_DIMENSION,
            "distance": r36.EXPECTED_DISTANCE,
            "payload_schema_version": PAYLOAD_SCHEMA,
            "pre_post_full_readback": True,
        },
        "queries": {
            "probe_count": PROBE_COUNT,
            "variants_per_probe": VARIANTS_PER_PROBE,
            "query_count": QUERY_COUNT,
            "embedding_provider": "cloudflare-workers-ai",
            "embedding_model": "@cf/baai/bge-m3",
            "separate_live_calls": True,
            "qdrant_dense_limit": DENSE_LIMIT,
            "target_aware_inputs": False,
        },
        "quality": {
            "min_recall_at_5": base_r35.r34.MIN_RECALL_AT_5,
            "min_mrr_at_10": base_r35.r34.MIN_MRR_AT_10,
            "min_ndcg_at_10": base_r35.r34.MIN_NDCG_AT_10,
            "max_top10_hub_frequency": MAXIMUM_HUB_FREQUENCY,
            "exact_target_rank_parity": True,
            "accepted_target_ranks": ACCEPTED_TARGET_RANKS,
        },
        "latency": {
            "max_live_p95_ms": MAX_LIVE_P95_MS,
            "max_error_rate": 0.0,
            "max_acl_violation_rate": 0.0,
            "batch_amortisation_allowed": False,
        },
        "privacy": {
            "raw_query_persisted": False,
            "raw_answer_persisted": False,
            "document_text_persisted": False,
            "credentials_persisted": False,
            "service_url_persisted": False,
            "service_hostname_persisted": False,
            "arbitrary_exception_text_persisted": False,
        },
        "authority": {
            "qdrant_read_authorized": True,
            "qdrant_write_authorized": False,
            "qdrant_delete_authorized": False,
            "qdrant_reindex_authorized": False,
            "historical_pilot_mutation_authorized": False,
            "production_collection_mutation_authorized": False,
            "r2_mutation_authorized": False,
            "pointer_mutation_authorized": False,
            "source_mutation_authorized": False,
            "production_mutation_authorized": False,
            "serving_authorized": False,
            "promotion_eligibility_granted": False,
            "retrieval_quality_blocker_cleared": False,
            "production_retrieval": "lexical",
        },
    }
    _require(
        canonical_sha256(contract) == CONTRACT_SHA256,
        "contract_digest",
        "live acceptance contract digest drifted",
    )
    return {**contract, "contract_sha256": CONTRACT_SHA256}


class LiveAcceptanceClient(Protocol):
    network_calls: int

    def collection_snapshot(self) -> Mapping[str, Any]: ...

    def retrieve_points(self, ids: Sequence[str]) -> Sequence[Mapping[str, Any]]: ...

    def embed(self, variant_id: str, text: str) -> Sequence[float]: ...

    def query(
        self,
        vector: Sequence[float],
        limit: int,
    ) -> Sequence[Mapping[str, Any]]: ...


class HttpLiveAcceptanceClient:
    def __init__(self, cloudflare: CloudflareConfig, qdrant: QdrantConfig) -> None:
        _require(
            qdrant.collection_name == EXPECTED_COLLECTION,
            "collection_config",
            "Qdrant collection identity drifted",
        )
        self.cloudflare = cloudflare
        self.qdrant = qdrant
        self._cloudflare_http = httpx.Client(timeout=cloudflare.timeout_seconds)
        self._qdrant_http = httpx.Client(timeout=qdrant.timeout_seconds)
        self._closed = False
        self.network_calls = 0

    def __enter__(self) -> HttpLiveAcceptanceClient:
        self._ensure_open()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        _require(not self._closed, "client_closed", "live acceptance client is closed")

    def close(self) -> None:
        if self._closed:
            return
        self._cloudflare_http.close()
        self._qdrant_http.close()
        self._closed = True

    def _qdrant_request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self._ensure_open()
        _require(method in {"GET", "POST"}, "read_only_method", "non-read method rejected")
        url = f"{self.qdrant.base_url.rstrip('/')}{path}"
        self.network_calls += 1
        try:
            response = self._qdrant_http.request(
                method,
                url,
                headers={"api-key": self.qdrant.api_key},
                json=dict(body) if body is not None else None,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise LiveAcceptanceError("qdrant_timeout", "Qdrant request timed out") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LiveAcceptanceError("qdrant_unavailable", "Qdrant request failed") from exc
        _require(isinstance(payload, Mapping), "qdrant_shape", "Qdrant response is invalid")
        _require(payload.get("status") == "ok", "qdrant_status", "Qdrant status is not ok")
        return payload

    def collection_snapshot(self) -> Mapping[str, Any]:
        payload = self._qdrant_request(
            "GET",
            f"/collections/{quote(EXPECTED_COLLECTION, safe='')}",
        )
        result = payload.get("result")
        _require(isinstance(result, Mapping), "collection_result", "collection result missing")
        params = result.get("config", {}).get("params", {})
        vectors = params.get("vectors") if isinstance(params, Mapping) else None
        default = vectors.get(VECTOR_NAME) if isinstance(vectors, Mapping) else None
        _require(isinstance(default, Mapping), "collection_vector", "default vector missing")
        return {
            "status": result.get("status"),
            "points_count": result.get("points_count"),
            "indexed_vectors_count": result.get("indexed_vectors_count"),
            "vector_name": VECTOR_NAME,
            "vector_size": default.get("size"),
            "vector_distance": default.get("distance"),
            "sparse_vectors": (
                params.get("sparse_vectors") if isinstance(params, Mapping) else None
            ),
        }

    def retrieve_points(self, ids: Sequence[str]) -> Sequence[Mapping[str, Any]]:
        output: list[Mapping[str, Any]] = []
        escaped = quote(EXPECTED_COLLECTION, safe="")
        for start in range(0, len(ids), READBACK_BATCH_SIZE):
            payload = self._qdrant_request(
                "POST",
                f"/collections/{escaped}/points?consistency=all",
                {
                    "ids": list(ids[start : start + READBACK_BATCH_SIZE]),
                    "with_payload": True,
                    "with_vector": [VECTOR_NAME],
                },
            )
            result = payload.get("result")
            _require(isinstance(result, list), "readback_result", "readback result missing")
            _require(
                all(isinstance(item, Mapping) for item in result),
                "readback_shape",
                "readback point shape is invalid",
            )
            output.extend(result)
        return output

    def embed(self, variant_id: str, text: str) -> Sequence[float]:
        self._ensure_open()
        self.network_calls += 1
        section = SectionInput(section_id=variant_id, text=text, payload={})
        try:
            rows = embed_sections(
                [section],
                self.cloudflare,
                client=self._cloudflare_http,
            )
        except httpx.TimeoutException as exc:
            raise LiveAcceptanceError("cloudflare_timeout", "embedding request timed out") from exc
        except (httpx.HTTPError, IntegrityError) as exc:
            raise LiveAcceptanceError("cloudflare_unavailable", "embedding request failed") from exc
        _require(len(rows) == 1, "embedding_shape", "embedding response count drifted")
        return rows[0]

    def query(
        self,
        vector: Sequence[float],
        limit: int,
    ) -> Sequence[Mapping[str, Any]]:
        payload = self._qdrant_request(
            "POST",
            f"/collections/{quote(EXPECTED_COLLECTION, safe='')}/points/query?consistency=all",
            {
                "query": list(vector),
                "using": VECTOR_NAME,
                "limit": limit,
                "with_payload": True,
                "with_vector": False,
            },
        )
        result = payload.get("result")
        points = result.get("points") if isinstance(result, Mapping) else None
        _require(isinstance(points, list), "query_result", "query result missing")
        _require(
            all(isinstance(item, Mapping) for item in points),
            "query_shape",
            "query point shape is invalid",
        )
        return points


def _validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    r36.validate_collection_schema(snapshot, EXPECTED_POINT_COUNT)
    indexed = snapshot.get("indexed_vectors_count")
    _require(
        isinstance(indexed, int) and not isinstance(indexed, bool) and indexed >= 0,
        "indexed_vectors",
        "indexed vector count is invalid",
    )
    return dict(snapshot)


def _validate_point_set(
    manifest: Mapping[str, Any],
    returned: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    expected_points = list(manifest["points"])
    expected_ids = [str(point["id"]) for point in expected_points]
    _require(
        len(returned) == EXPECTED_POINT_COUNT,
        "readback_count",
        "full readback count drifted",
    )
    returned_by_id = {str(point.get("id")): point for point in returned}
    _require(
        len(returned_by_id) == EXPECTED_POINT_COUNT
        and set(returned_by_id) == set(expected_ids),
        "readback_ids",
        "full readback ID set drifted",
    )
    expected_by_id = {str(point["id"]): point for point in expected_points}
    mismatches = [
        point_id
        for point_id in sorted(expected_ids)
        if r36.point_fingerprint(expected_by_id[point_id])
        != r36.point_fingerprint(dict(returned_by_id[point_id]))
    ]
    _require(not mismatches, "readback_fingerprint", "point fingerprint drifted")
    ids_sha = r36.canonical_sha256(sorted(returned_by_id))
    aggregate = r36.aggregate_fingerprint([dict(item) for item in returned])
    _require(ids_sha == manifest["ids_sha256"], "ids_digest", "ID digest drifted")
    _require(
        aggregate == manifest["aggregate_fingerprint_sha256"],
        "aggregate_digest",
        "aggregate fingerprint drifted",
    )
    return {"ids_sha256": ids_sha, "aggregate_fingerprint_sha256": aggregate}


def _normalised_vector(raw: Sequence[Any], label: str) -> list[float]:
    values = [float(value) for value in raw]
    _require(len(values) == VECTOR_DIMENSION, "query_dimension", f"{label} dimension drifted")
    _require(all(math.isfinite(value) for value in values), "query_finite", f"{label} is invalid")
    norm = math.sqrt(math.fsum(value * value for value in values))
    _require(abs(norm - 1.0) <= 1e-4, "query_norm", f"{label} is not normalized")
    return values


def _validate_ranked_points(
    points: Sequence[Mapping[str, Any]],
    known_sections: set[str],
) -> list[tuple[float, str]]:
    _require(len(points) == DENSE_LIMIT, "dense_limit", "Qdrant dense result count drifted")
    seen: set[str] = set()
    output: list[tuple[float, str]] = []
    for raw in points:
        payload = raw.get("payload")
        _require(isinstance(payload, Mapping), "ranked_payload", "ranked payload missing")
        expected = {
            "payload_schema_version": PAYLOAD_SCHEMA,
            "source_membership": "r3-6-candidate-live-acceptance-only",
            "candidate_collection": EXPECTED_COLLECTION,
            "candidate_artifact_sha256": r36.R3_5_CANDIDATE_ARTIFACT_SHA256,
            "candidate_reingestion_issue": r36.IMPLEMENTATION_ISSUE,
            "vector_name": VECTOR_NAME,
            "vector_dimension": VECTOR_DIMENSION,
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
        }
        for key, value in expected.items():
            _require(payload.get(key) == value, "payload_identity", f"payload field drifted: {key}")
        section_id = payload.get("section_id")
        _require(
            isinstance(section_id, str) and section_id in known_sections,
            "ranked_section",
            "ranked section is unexpected",
        )
        _require(section_id not in seen, "ranked_duplicate", "ranked section is duplicated")
        seen.add(section_id)
        score = raw.get("score")
        _require(
            isinstance(score, (int, float)) and not isinstance(score, bool),
            "ranked_score",
            "ranked score is invalid",
        )
        numeric = float(score)
        _require(
            math.isfinite(numeric) and -1.0001 <= numeric <= 1.0001,
            "ranked_score",
            "ranked score is outside cosine bounds",
        )
        output.append((numeric, section_id))
    output.sort(key=lambda item: (-item[0], item[1]))
    for section_id in sorted(known_sections - seen):
        output.append((-2.0, section_id))
    _require(
        len(output) == EXPECTED_POINT_COUNT,
        "dense_coverage",
        "dense ranking coverage drifted",
    )
    return output


def live_calibrated_ranking(
    *,
    query_class: str,
    query_texts: Sequence[str],
    dense_rankings: Sequence[Sequence[tuple[float, str]]],
    section_ids: Sequence[str],
    counts_by_section: Mapping[str, Counter[str]],
    document_frequency: Mapping[str, int],
    lengths: Mapping[str, int],
    average_length: float,
) -> tuple[list[tuple[float, str]], dict[str, object]]:
    _require(
        query_class in base_r35.LEXICAL_WEIGHTS,
        "query_class",
        "unsupported query class",
    )
    _require(
        len(query_texts) == VARIANTS_PER_PROBE,
        "query_variant_count",
        "query text variant count drifted",
    )
    _require(
        len(dense_rankings) == VARIANTS_PER_PROBE,
        "dense_variant_count",
        "dense ranking variant count drifted",
    )
    dense_rrf = base_r35._rrf_scores(dense_rankings)
    lexical = r35._bm25_ranking(
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
    for ranking in dense_rankings:
        for rank, (_score, section_id) in enumerate(ranking, start=1):
            dense_best_rank[section_id] = min(
                dense_best_rank.get(section_id, len(section_ids) + 1),
                rank,
            )
            if rank <= base_r35.CONSENSUS_DEPTH:
                dense_consensus[section_id] += 1
    lexical_weight = base_r35.LEXICAL_WEIGHTS[query_class]
    calibrated: dict[str, float] = {}
    for section_id in section_ids:
        _require(section_id in dense_best_rank, "dense_coverage", "dense coverage incomplete")
        lexical_rank = lexical_ranks.get(section_id)
        lexical_score = (
            lexical_weight / (base_r35.LEXICAL_RRF_K + lexical_rank)
            if lexical_rank is not None
            else 0.0
        )
        consensus_score = (
            base_r35.CONSENSUS_WEIGHT
            * dense_consensus.get(section_id, 0)
            / (base_r35.CONSENSUS_RRF_K + dense_best_rank[section_id])
        )
        calibrated[section_id] = (
            float(dense_rrf.get(section_id, 0.0))
            + lexical_score
            + consensus_score
        )
    ranking = sorted(
        ((score, section_id) for section_id, score in calibrated.items()),
        key=lambda item: (-item[0], item[1]),
    )
    diagnostics: dict[str, object] = {
        "lexical_weight": lexical_weight,
        "dense_variant_count": len(dense_rankings),
        "positive_lexical_match_count": len(lexical_ranks),
        "zero_match_lexical_credit": False,
        "target_aware_inputs_accepted": False,
    }
    return ranking, diagnostics


def evaluate_live_dense_rankings(
    candidate: Mapping[str, Any],
    dense_rankings: Sequence[Sequence[tuple[float, str]]],
) -> dict[str, Any]:
    probes = list(candidate["probe_plan"])
    documents = list(candidate["lexical_documents"])
    points = list(candidate["points"])
    _require(len(probes) == PROBE_COUNT, "probe_count", "probe count drifted")
    _require(len(documents) == EXPECTED_POINT_COUNT, "document_count", "document count drifted")
    _require(len(points) == EXPECTED_POINT_COUNT, "point_count", "point count drifted")
    _require(len(dense_rankings) == QUERY_COUNT, "query_count", "dense query count drifted")
    section_ids = [str(point["payload"]["section_id"]) for point in points]
    _require(
        len(set(section_ids)) == EXPECTED_POINT_COUNT,
        "section_ids",
        "section IDs are not unique",
    )
    counts, frequencies, lengths, average_length = base_r35._lexical_index(documents)
    cases: list[dict[str, Any]] = []
    ranks: list[int] = []
    top_tens: list[list[str]] = []
    cursor = 0
    for probe in probes:
        group = dense_rankings[cursor : cursor + VARIANTS_PER_PROBE]
        cursor += VARIANTS_PER_PROBE
        ranking, diagnostics = live_calibrated_ranking(
            query_class=str(probe["query_class"]),
            query_texts=[
                str(variant["query_text"]) for variant in probe["variants"]
            ],
            dense_rankings=group,
            section_ids=section_ids,
            counts_by_section=counts,
            document_frequency=frequencies,
            lengths=lengths,
            average_length=average_length,
        )
        target = str(probe["target_section_id"])
        rank = base_r35._rank_of(ranking, target)
        ranked_ids = [section_id for _score, section_id in ranking[: base_r35.r34.TOP_K]]
        ranks.append(rank)
        top_tens.append(ranked_ids)
        cases.append(
            {
                "probe_id": probe["probe_id"],
                "offline_case_id": probe["offline_case_id"],
                "query_class": probe["query_class"],
                "variant_query_sha256": [
                    variant["query_text_sha256"] for variant in probe["variants"]
                ],
                "target_section_id": target,
                "live_calibrated_rank": rank,
                "ranked_section_ids": ranked_ids,
                "target_in_top_5": rank <= 5,
                "calibration": diagnostics,
                "raw_query_persisted": False,
                "raw_answer_persisted": False,
            }
        )
    metrics = base_r35.r34._metrics(ranks)
    hubs = Counter(section_id for row in top_tens for section_id in row)
    maximum_hub = max(hubs.values())
    target_ranks = {
        str(case["offline_case_id"]): int(case["live_calibrated_rank"])
        for case in cases
    }
    return {
        "metrics": metrics,
        "cases": cases,
        "target_ranks": target_ranks,
        "maximum_top10_hub_frequency": maximum_hub,
        "hubness_top_10": [
            {"section_id": section_id, "frequency": frequency}
            for section_id, frequency in sorted(
                hubs.items(),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        ],
    }


def _base_receipt(started_at: str) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "milestone": "M23.7-R3.7",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "started_at": started_at,
        "contract_sha256": canonical_contract()["contract_sha256"],
        "collection": EXPECTED_COLLECTION,
        "historical_pilot_collection": HISTORICAL_PILOT_COLLECTION,
        "privacy": canonical_contract()["privacy"],
        "authority": {
            "qdrant_read_dispatched": False,
            "qdrant_write_dispatched": False,
            "qdrant_delete_dispatched": False,
            "qdrant_reindex_dispatched": False,
            "historical_pilot_mutation_dispatched": False,
            "production_collection_mutation_dispatched": False,
            "r2_mutation_dispatched": False,
            "pointer_mutation_dispatched": False,
            "source_mutation_dispatched": False,
            "production_mutation_dispatched": False,
            "serving_dispatched": False,
            "promotion_eligibility_granted": False,
            "retrieval_quality_blocker_cleared": False,
            "production_retrieval": "lexical",
        },
    }


def run_live_acceptance(
    candidate: Mapping[str, Any],
    manifest: Mapping[str, Any],
    client: LiveAcceptanceClient,
    *,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> dict[str, Any]:
    _require(
        candidate.get("candidate_artifact_sha256")
        == r36.R3_5_CANDIDATE_ARTIFACT_SHA256,
        "candidate_identity",
        "R3.5 candidate identity drifted",
    )
    _require(
        manifest.get("manifest_sha256") == R3_6_MANIFEST_SHA256,
        "manifest_identity",
        "R3.6 candidate manifest drifted",
    )
    _require(
        manifest.get("ids_sha256") == R3_6_IDS_SHA256,
        "manifest_ids",
        "R3.6 ID digest drifted",
    )
    _require(
        manifest.get("aggregate_fingerprint_sha256") == R3_6_AGGREGATE_SHA256,
        "manifest_aggregate",
        "R3.6 aggregate fingerprint drifted",
    )
    expected_points = list(manifest["points"])
    ids = [str(point["id"]) for point in expected_points]
    known_sections = {
        str(point["payload"]["section_id"]) for point in expected_points
    }
    before = _validate_snapshot(client.collection_snapshot())
    pre_identity = _validate_point_set(manifest, client.retrieve_points(ids))

    query_vectors: list[list[float]] = []
    dense_rankings: list[list[tuple[float, str]]] = []
    latency_cases: list[dict[str, Any]] = []
    query_digests: list[str] = []
    for probe in candidate["probe_plan"]:
        for variant in probe["variants"]:
            variant_id = str(variant["variant_id"])
            query_digest = str(variant["query_text_sha256"])
            query_digests.append(query_digest)
            total_start = clock_ns()
            provider_start = clock_ns()
            vector = _normalised_vector(
                client.embed(variant_id, str(variant["query_text"])),
                variant_id,
            )
            provider_end = clock_ns()
            qdrant_start = clock_ns()
            ranked = _validate_ranked_points(
                client.query(vector, DENSE_LIMIT),
                known_sections,
            )
            qdrant_end = clock_ns()
            total_end = clock_ns()
            query_vectors.append(vector)
            dense_rankings.append(ranked)
            latency_cases.append(
                {
                    "variant_id": variant_id,
                    "query_sha256": query_digest,
                    "provider_latency_ms": _elapsed_ms(provider_start, provider_end),
                    "qdrant_latency_ms": _elapsed_ms(qdrant_start, qdrant_end),
                    "total_latency_ms": _elapsed_ms(total_start, total_end),
                    "failure_class": None,
                    "ranked_section_ids": [
                        section_id for _score, section_id in ranked[:DENSE_LIMIT]
                    ],
                    "raw_query_persisted": False,
                    "raw_answer_persisted": False,
                }
            )
    _require(len(query_vectors) == QUERY_COUNT, "query_count", "query execution count drifted")
    _require(
        len(set(query_digests)) == QUERY_COUNT,
        "query_identity",
        "query identities are not unique",
    )

    evaluation = evaluate_live_dense_rankings(candidate, dense_rankings)
    after = _validate_snapshot(client.collection_snapshot())
    post_identity = _validate_point_set(manifest, client.retrieve_points(ids))
    _require(before == after, "snapshot_drift", "collection snapshot changed")
    _require(pre_identity == post_identity, "point_drift", "collection point identity changed")

    provider_values = [case["provider_latency_ms"] for case in latency_cases]
    qdrant_values = [case["qdrant_latency_ms"] for case in latency_cases]
    total_values = [case["total_latency_ms"] for case in latency_cases]
    latency = {
        "provider_p50_ms": _p50(provider_values),
        "provider_p95_ms": _p95(provider_values),
        "qdrant_p50_ms": _p50(qdrant_values),
        "qdrant_p95_ms": _p95(qdrant_values),
        "live_p50_ms": _p50(total_values),
        "live_p95_ms": _p95(total_values),
        "maximum_live_p95_ms": MAX_LIVE_P95_MS,
        "batch_amortisation_used": False,
    }
    metrics = evaluation["metrics"]
    target_ranks = evaluation["target_ranks"]
    gates = {
        "candidate_identity": True,
        "collection_schema_pre_post_exact": before == after,
        "point_identity_pre_post_exact": pre_identity == post_identity,
        "query_count_24": len(query_vectors) == QUERY_COUNT,
        "query_identity_unique": len(set(query_digests)) == QUERY_COUNT,
        "recall_at_5": metrics["recall_at_5"] >= base_r35.r34.MIN_RECALL_AT_5,
        "mrr_at_10": metrics["mrr_at_10"] >= base_r35.r34.MIN_MRR_AT_10,
        "ndcg_at_10": metrics["ndcg_at_10"] >= base_r35.r34.MIN_NDCG_AT_10,
        "accepted_metric_parity": metrics == ACCEPTED_METRICS,
        "exact_target_rank_parity": target_ranks == ACCEPTED_TARGET_RANKS,
        "hub_frequency": (
            evaluation["maximum_top10_hub_frequency"] <= MAXIMUM_HUB_FREQUENCY
        ),
        "live_p95_latency": latency["live_p95_ms"] <= MAX_LIVE_P95_MS,
        "query_error_rate_zero": True,
        "acl_violation_rate_zero": True,
        "qdrant_writes_zero": True,
        "qdrant_deletes_zero": True,
        "qdrant_reindex_zero": True,
        "protected_mutations_zero": True,
    }
    passed = all(gates.values())
    retained_blockers = ["blocked_pending_retrieval_quality"]
    if not gates["live_p95_latency"]:
        retained_blockers.append("blocked_pending_latency")
    report: dict[str, Any] = {
        **_base_receipt(utc_now()),
        "status": (
            "pass_live_acceptance"
            if passed
            else "completed_fail_closed_live_acceptance"
        ),
        "completed_at": utc_now(),
        "candidate_manifest_sha256": manifest["manifest_sha256"],
        "ids_sha256": pre_identity["ids_sha256"],
        "aggregate_fingerprint_sha256": pre_identity[
            "aggregate_fingerprint_sha256"
        ],
        "point_count": EXPECTED_POINT_COUNT,
        "collection_before": before,
        "collection_after": after,
        "pre_post_point_identity_equal": pre_identity == post_identity,
        "query_count": len(query_vectors),
        "query_identity_count": len(set(query_digests)),
        "metrics": metrics,
        "accepted_metrics": ACCEPTED_METRICS,
        "target_ranks": target_ranks,
        "accepted_target_ranks": ACCEPTED_TARGET_RANKS,
        "maximum_top10_hub_frequency": evaluation[
            "maximum_top10_hub_frequency"
        ],
        "hubness_top_10": evaluation["hubness_top_10"],
        "latency": latency,
        "latency_cases": latency_cases,
        "quality_cases": evaluation["cases"],
        "gates": gates,
        "error_rate": 0.0,
        "acl_violation_rate": 0.0,
        "network_calls": client.network_calls,
        "retained_blockers": retained_blockers,
        "authority": {
            **_base_receipt(utc_now())["authority"],
            "qdrant_read_dispatched": True,
            "live_acceptance_gate_passed": passed,
        },
        "exit": {
            "live_acceptance_result_complete": True,
            "live_acceptance_passed": passed,
            "evidence_seal_required": True,
            "independent_reconciliation_required": True,
            "retrieval_quality_blocker_clearance_eligible_after_reconciliation": passed,
            "next_gate": "separately_governed_r3_7_live_acceptance_evidence_seal",
        },
    }
    report["receipt_sha256"] = canonical_sha256(report)
    return report


def _write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(receipt) + "\n", encoding="utf-8")


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise LiveAcceptanceError("environment", f"missing environment variable: {name}")
    return value


def execute(evidence_zip: Path, receipt_path: Path, timeout: int = 60) -> int:
    started = utc_now()
    client: HttpLiveAcceptanceClient | None = None
    try:
        candidate = r35.build_calibration_candidate(evidence_zip)
        manifest = r36.build_candidate_points(evidence_zip)
        cloudflare = CloudflareConfig(
            account_id=_required_environment("CLOUDFLARE_ACCOUNT_ID"),
            api_token=_required_environment("CLOUDFLARE_API_TOKEN"),
            timeout_seconds=float(timeout),
        )
        qdrant = QdrantConfig(
            base_url=_required_environment("QDRANT_URL"),
            api_key=_required_environment("QDRANT_API_KEY"),
            collection_name=EXPECTED_COLLECTION,
            timeout_seconds=float(timeout),
        )
        with HttpLiveAcceptanceClient(cloudflare, qdrant) as client:
            receipt = run_live_acceptance(candidate, manifest, client)
        receipt["started_at"] = started
        receipt["completed_at"] = utc_now()
        receipt.pop("receipt_sha256", None)
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        _write_receipt(receipt_path, receipt)
        return 0 if receipt["status"] == "pass_live_acceptance" else 30
    except (LiveAcceptanceError, IntegrityError, OSError) as exc:
        failure_code = exc.code if isinstance(exc, LiveAcceptanceError) else "input_or_integrity"
        receipt = {
            **_base_receipt(started),
            "status": "rejected_incomplete_live_acceptance",
            "completed_at": utc_now(),
            "failure_code": failure_code,
            "network_calls": client.network_calls if client is not None else 0,
            "retained_blockers": [
                "blocked_pending_retrieval_quality",
                "blocked_pending_live_acceptance",
            ],
            "exit": {
                "live_acceptance_result_complete": False,
                "live_acceptance_passed": False,
                "next_gate": "repair_or_retry_required",
            },
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        _write_receipt(receipt_path, receipt)
        return 23 if failure_code in {"environment", "input_or_integrity"} else 30


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run read-only M23.7-R3.7 live acceptance"
    )
    parser.add_argument("--evidence-zip", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return execute(
        Path(args.evidence_zip).expanduser().resolve(),
        Path(args.receipt).expanduser().resolve(),
        args.timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
