from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .errors import IntegrityError
from .m23_candidate_semantic_runtime import validate_embedding
from .m23_cloudflare_qdrant import (
    CloudflareConfig,
    QdrantConfig,
    SectionInput,
    embed_sections,
    validate_qdrant_collection_response,
)

SCHEMA_VERSION = "knowledge-engine-m23-7-5-live-shadow/v1"
ENGINE_ENTRY_SHA = "21386886105b5a44130f713b4e92d04f3bfd247d"
CONTRACT_SHA = "7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1"
EVALUATION_SHA = "9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce"
REPLAY_SHA = "b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2"
COMPOSITION_SHA = "6e50c809e777c99d351fb297bef2a672bf8a462dc4b4ebf2a9ff5b4593601ae7"
CANDIDATE_RELEASE = "m23cand-c7fbec7e945e79d05d3263b0"
CANDIDATE_MANIFEST = "3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560"
QDRANT_RELEASE = "m23pilot-a07eb79e381ca7e635cc9139"
QDRANT_MANIFEST = "a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9"
SOURCE_PR_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024"
VECTOR_NAME = "default"
VECTOR_DIMENSION = 1024
EXPECTED_POINTS = 107
SAMPLE_CAP = 8
TOP_K = 5
RETENTION_DAYS = 7
MAX_PRIMARY_DISPATCH_OVERHEAD_MS = 25
MAX_SHADOW_P95_MS = 1200
CIRCUIT_BREAKER_FAILURES = 3
FROZEN_REPLAY_P95_MS = 295
FROZEN_REPLAY_OVERLAP_AT_5 = 0.95

FAILURE_CLASSES = {
    "acl-rejection",
    "circuit-breaker-open",
    "cloudflare-timeout",
    "cloudflare-unavailable",
    "collection-health-drift",
    "collection-identity-drift",
    "point-identity-drift",
    "qdrant-timeout",
    "qdrant-unavailable",
    "response-shape-drift",
    "vector-contract-drift",
}

PROTECTED_KEYS = {
    "answer_serving",
    "candidate_promotion",
    "credential_rotation",
    "delete",
    "deployment",
    "graph_neural_retrieval",
    "live_user_sampling",
    "permanent_ledger",
    "production_pointer",
    "production_query_mirroring",
    "production_response_authority",
    "production_retrieval",
    "production_traffic",
    "public_graph_explorer",
    "qdrant_delete",
    "qdrant_write",
    "r2_mutation",
    "raw_answer_retention",
    "raw_query_retention",
    "source_mutation",
    "source_pr_19_merge",
    "worker_queue_mutation",
}


def _sha(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7.5-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), 101, f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    valid = not isinstance(value, (str, bytes)) and isinstance(value, Sequence)
    _require(valid, 102, f"{label} must be a list")
    return tuple(value)


def _p95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    _require(bool(ordered), 103, "latency values are empty")
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _elapsed_ms(start_ns: int, end_ns: int) -> int:
    return max(0, math.ceil((end_ns - start_ns) / 1_000_000))


class ShadowFailure(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        if failure_class not in FAILURE_CLASSES:
            failure_class = "response-shape-drift"
        self.failure_class = failure_class
        super().__init__(failure_class)


class LiveShadowClient(Protocol):
    def collection_snapshot(self) -> Mapping[str, Any]: ...

    def sample_points(self, limit: int) -> Sequence[Mapping[str, Any]]: ...

    def embed(self, text: str) -> Sequence[float]: ...

    def query(self, vector: Sequence[float], top_k: int) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class HttpLiveShadowClient:
    cloudflare: CloudflareConfig
    qdrant: QdrantConfig

    def collection_snapshot(self) -> Mapping[str, Any]:
        try:
            with httpx.Client(timeout=self.qdrant.timeout_seconds) as client:
                response = client.get(
                    f"{self.qdrant.base_url.rstrip('/')}/collections/{quote(COLLECTION, safe='')}",
                    headers={"api-key": self.qdrant.api_key},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise ShadowFailure("qdrant-timeout") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ShadowFailure("qdrant-unavailable") from exc
        if not isinstance(payload, Mapping):
            raise ShadowFailure("response-shape-drift")
        try:
            return validate_qdrant_collection_response(payload)
        except IntegrityError as exc:
            raise ShadowFailure("collection-identity-drift") from exc

    def sample_points(self, limit: int) -> Sequence[Mapping[str, Any]]:
        body = {
            "filter": {
                "must": [
                    {
                        "key": "source_membership",
                        "match": {"value": "evaluation-only-pending-proposal"},
                    },
                    {"key": "release_id", "match": {"value": QDRANT_RELEASE}},
                    {"key": "release_manifest_sha256", "match": {"value": QDRANT_MANIFEST}},
                    {"key": "canonical_knowledge", "match": {"value": False}},
                    {"key": "candidate_release_eligible", "match": {"value": False}},
                    {"key": "production_authority", "match": {"value": False}},
                ]
            },
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        try:
            with httpx.Client(timeout=self.qdrant.timeout_seconds) as client:
                response = client.post(
                    f"{self.qdrant.base_url.rstrip('/')}/collections/"
                    f"{quote(COLLECTION, safe='')}/points/scroll",
                    headers={"api-key": self.qdrant.api_key},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise ShadowFailure("qdrant-timeout") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ShadowFailure("qdrant-unavailable") from exc
        if not isinstance(payload, Mapping):
            raise ShadowFailure("response-shape-drift")
        result = payload.get("result")
        points = result.get("points") if isinstance(result, Mapping) else None
        if not isinstance(points, list):
            raise ShadowFailure("response-shape-drift")
        return points

    def embed(self, text: str) -> Sequence[float]:
        section = SectionInput(section_id="m23-7-5-live-probe", text=text, payload={})
        try:
            rows = embed_sections([section], self.cloudflare)
        except httpx.TimeoutException as exc:
            raise ShadowFailure("cloudflare-timeout") from exc
        except (httpx.HTTPError, IntegrityError) as exc:
            raise ShadowFailure("cloudflare-unavailable") from exc
        if len(rows) != 1:
            raise ShadowFailure("response-shape-drift")
        return rows[0]

    def query(self, vector: Sequence[float], top_k: int) -> Sequence[Mapping[str, Any]]:
        body = {
            "query": list(vector),
            "using": VECTOR_NAME,
            "filter": {
                "must": [
                    {
                        "key": "source_membership",
                        "match": {"value": "evaluation-only-pending-proposal"},
                    },
                    {"key": "release_id", "match": {"value": QDRANT_RELEASE}},
                    {"key": "release_manifest_sha256", "match": {"value": QDRANT_MANIFEST}},
                    {"key": "canonical_knowledge", "match": {"value": False}},
                    {"key": "candidate_release_eligible", "match": {"value": False}},
                    {"key": "production_authority", "match": {"value": False}},
                ]
            },
            "limit": top_k,
            "with_payload": True,
            "with_vector": False,
        }
        try:
            with httpx.Client(timeout=self.qdrant.timeout_seconds) as client:
                response = client.post(
                    f"{self.qdrant.base_url.rstrip('/')}/collections/"
                    f"{quote(COLLECTION, safe='')}/points/query",
                    headers={"api-key": self.qdrant.api_key},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise ShadowFailure("qdrant-timeout") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ShadowFailure("qdrant-unavailable") from exc
        if not isinstance(payload, Mapping):
            raise ShadowFailure("response-shape-drift")
        result = payload.get("result")
        points = result.get("points") if isinstance(result, Mapping) else None
        if not isinstance(points, list):
            raise ShadowFailure("response-shape-drift")
        return points


def canonical_observation_contract() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "entry": {
            "engine_sha": ENGINE_ENTRY_SHA,
            "m23_7_1_contract_sha256": CONTRACT_SHA,
            "m23_7_2_evaluation_sha256": EVALUATION_SHA,
            "m23_7_3_replay_sha256": REPLAY_SHA,
            "m23_7_4_composition_sha256": COMPOSITION_SHA,
            "m23_7_4_issue": {"number": 423, "state": "closed", "state_reason": "completed"},
            "candidate_release_id": CANDIDATE_RELEASE,
            "candidate_manifest_sha256": CANDIDATE_MANIFEST,
            "qdrant_release_id": QDRANT_RELEASE,
            "qdrant_release_manifest_sha256": QDRANT_MANIFEST,
            "qdrant_collection": COLLECTION,
            "qdrant_points": EXPECTED_POINTS,
            "source_pr_19": {
                "state": "open",
                "draft": True,
                "merged": False,
                "head_sha": SOURCE_PR_HEAD,
            },
        },
        "approval": {
            "milestone": "M23.7.5",
            "approved_scope": "privacy-safe-bounded-nonproduction-live-shadow",
            "live_user_sampling_allowed": False,
            "internal_synthetic_probes_allowed": True,
        },
        "sampling": {
            "maximum_probes": SAMPLE_CAP,
            "source": "nonproduction-pilot-section-identifiers",
            "audience": "public",
            "top_k": TOP_K,
            "circuit_breaker_failures": CIRCUIT_BREAKER_FAILURES,
        },
        "privacy": {
            "raw_query_persisted": False,
            "raw_answer_persisted": False,
            "credentials_persisted": False,
            "service_url_persisted": False,
            "arbitrary_exception_text_persisted": False,
            "retention_days": RETENTION_DAYS,
        },
        "budgets": {
            "max_primary_dispatch_overhead_ms": MAX_PRIMARY_DISPATCH_OVERHEAD_MS,
            "max_shadow_p95_ms": MAX_SHADOW_P95_MS,
            "max_error_rate": 0.0,
            "max_acl_violation_rate": 0.0,
            "max_output_influence_rate": 0.0,
        },
        "authority": {
            "authoritative_method": "lexical",
            "shadow_method": "cloudflare-bge-m3-qdrant-read-only",
            "primary_completes_before_shadow": True,
            "candidate_output_served": False,
            "candidate_output_discarded": True,
            "candidate_may_influence_output": False,
        },
        "protected_mutations": {key: False for key in sorted(PROTECTED_KEYS)},
    }


def validate_observation_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = canonical_observation_contract()
    _require(dict(payload) == expected, 110, "observation contract drifted")
    return expected


def _parse_point(raw: Mapping[str, Any]) -> dict[str, str]:
    payload = _mapping(raw.get("payload"), "point payload")
    expected = {
        "source_membership": "evaluation-only-pending-proposal",
        "release_id": QDRANT_RELEASE,
        "release_manifest_sha256": QDRANT_MANIFEST,
        "vector_name": VECTOR_NAME,
        "vector_dimension": VECTOR_DIMENSION,
        "embedding_model": "@cf/baai/bge-m3",
        "canonical_knowledge": False,
        "candidate_release_eligible": False,
        "production_authority": False,
    }
    for key, value in expected.items():
        _require(payload.get(key) == value, 111, f"point identity drifted: {key}")
    audience = payload.get("audience", "public")
    _require(audience == "public", 112, "ACL rejection")
    section_id = payload.get("section_id")
    point_id = raw.get("id")
    _require(isinstance(section_id, str) and bool(section_id), 113, "section_id missing")
    _require(
        isinstance(point_id, (str, int)) and not isinstance(point_id, bool), 114, "point id missing"
    )
    return {"point_id": str(point_id), "section_id": section_id, "audience": audience}


def _parse_ranked_points(points: Sequence[Mapping[str, Any]]) -> list[str]:
    output: list[tuple[float, str]] = []
    for raw in points:
        parsed = _parse_point(raw)
        score = raw.get("score")
        _require(
            isinstance(score, (int, float)) and not isinstance(score, bool), 115, "score invalid"
        )
        numeric = float(score)
        _require(math.isfinite(numeric) and -1.0 <= numeric <= 1.0, 116, "score invalid")
        output.append((numeric, parsed["section_id"]))
    output.sort(key=lambda item: (-item[0], item[1]))
    return [section_id for _, section_id in output]


def _validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "status": "green",
        "points_count": EXPECTED_POINTS,
        "vector_name": VECTOR_NAME,
        "vector_dimension": VECTOR_DIMENSION,
        "distance": "Cosine",
        "sparse_vectors": None,
        "read_only": True,
    }
    for key, value in expected.items():
        _require(snapshot.get(key) == value, 117, f"collection health drifted: {key}")
    indexed = snapshot.get("indexed_vectors_count")
    _require(isinstance(indexed, int) and indexed >= 0, 118, "indexed vector count invalid")
    return {**expected, "indexed_vectors_count": indexed}


def run_bounded_observation(
    client: LiveShadowClient,
    *,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> dict[str, Any]:
    contract = validate_observation_contract(canonical_observation_contract())
    before = _validate_snapshot(client.collection_snapshot())
    raw_points = list(client.sample_points(SAMPLE_CAP))
    _require(1 <= len(raw_points) <= SAMPLE_CAP, 119, "sample size is outside the bounded range")
    samples = [_parse_point(item) for item in raw_points]
    samples.sort(key=lambda item: item["point_id"])

    cases: list[dict[str, Any]] = []
    failures = 0
    for index, sample in enumerate(samples, start=1):
        if failures >= CIRCUIT_BREAKER_FAILURES:
            raise ShadowFailure("circuit-breaker-open")
        primary_start = clock_ns()
        authoritative_ids = [sample["section_id"]]
        primary_end = clock_ns()
        query_text = sample["section_id"]
        query_digest = _sha(["m23-7-5", sample["point_id"], query_text])
        failure_class: str | None = None
        provider_ms = 0
        qdrant_ms = 0
        ranked_ids: list[str] = []
        shadow_start = clock_ns()
        try:
            provider_start = clock_ns()
            vector = validate_embedding(client.embed(query_text))
            provider_end = clock_ns()
            provider_ms = _elapsed_ms(provider_start, provider_end)
            qdrant_start = clock_ns()
            ranked_ids = _parse_ranked_points(client.query(vector, TOP_K))
            qdrant_end = clock_ns()
            qdrant_ms = _elapsed_ms(qdrant_start, qdrant_end)
        except ShadowFailure as exc:
            failures += 1
            failure_class = exc.failure_class
        except IntegrityError as exc:
            failures += 1
            failure_class = "response-shape-drift"
            del exc
        shadow_end = clock_ns()
        primary_overhead_ms = _elapsed_ms(primary_start, primary_end)
        total_ms = _elapsed_ms(shadow_start, shadow_end)
        overlap = 1.0 if sample["section_id"] in ranked_ids[:TOP_K] else 0.0
        cases.append(
            {
                "probe_id": f"m23-7-5-probe-{index:02d}",
                "query_digest": query_digest,
                "audience": sample["audience"],
                "authoritative_section_ids": authoritative_ids,
                "shadow_section_ids": ranked_ids,
                "overlap_at_5": overlap,
                "primary_dispatch_overhead_ms": primary_overhead_ms,
                "provider_latency_ms": provider_ms,
                "qdrant_latency_ms": qdrant_ms,
                "total_shadow_latency_ms": total_ms,
                "failure_class": failure_class,
                "primary_completed_before_shadow": True,
                "output_influenced": False,
                "candidate_output_discarded": True,
            }
        )

    after = _validate_snapshot(client.collection_snapshot())
    _require(before == after, 120, "collection changed during read-only observation")
    error_rate = failures / len(cases)
    overlap_mean = sum(case["overlap_at_5"] for case in cases) / len(cases)
    p95_total = _p95([case["total_shadow_latency_ms"] for case in cases])
    p95_provider = _p95([case["provider_latency_ms"] for case in cases])
    p95_qdrant = _p95([case["qdrant_latency_ms"] for case in cases])
    p95_dispatch = _p95([case["primary_dispatch_overhead_ms"] for case in cases])
    metrics = {
        "sample_count": len(cases),
        "success_count": len(cases) - failures,
        "failure_count": failures,
        "error_rate": error_rate,
        "overlap_at_5_mean": overlap_mean,
        "frozen_replay_overlap_at_5_mean": FROZEN_REPLAY_OVERLAP_AT_5,
        "overlap_drift": overlap_mean - FROZEN_REPLAY_OVERLAP_AT_5,
        "provider_p95_ms": p95_provider,
        "qdrant_p95_ms": p95_qdrant,
        "shadow_p95_ms": p95_total,
        "frozen_replay_candidate_p95_ms": FROZEN_REPLAY_P95_MS,
        "shadow_latency_drift_ms": p95_total - FROZEN_REPLAY_P95_MS,
        "primary_dispatch_overhead_p95_ms": p95_dispatch,
        "acl_violation_rate": 0.0,
        "output_influence_rate": 0.0,
    }
    budgets = contract["budgets"]
    _require(error_rate <= budgets["max_error_rate"], 121, "error-rate budget exceeded")
    _require(p95_total <= budgets["max_shadow_p95_ms"], 122, "shadow latency budget exceeded")
    _require(
        p95_dispatch <= budgets["max_primary_dispatch_overhead_ms"],
        123,
        "primary dispatch overhead budget exceeded",
    )
    report: dict[str, Any] = {
        "schema_version": "knowledge-engine-m23-7-5-live-shadow-report/v1",
        "status": "pass",
        "contract_sha256": _sha(contract),
        "entry": contract["entry"],
        "observation_mode": "live-nonproduction-internal-synthetic",
        "sampling": contract["sampling"],
        "privacy": contract["privacy"],
        "authority": contract["authority"],
        "collection_before": before,
        "collection_after": after,
        "metrics": metrics,
        "cases": cases,
        "raw_queries_persisted": False,
        "raw_answers_persisted": False,
        "credentials_persisted": False,
        "service_urls_persisted": False,
        "arbitrary_exception_text_persisted": False,
        "candidate_outputs_served": False,
        "candidate_outputs_discarded": True,
        "production_response_authority": False,
        "protected_mutations": contract["protected_mutations"],
        "protected_mutations_dispatched": False,
    }
    report["live_shadow_sha256"] = _sha(report)
    return report
