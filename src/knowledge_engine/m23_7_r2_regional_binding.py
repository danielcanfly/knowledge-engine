from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from .errors import IntegrityError
from .m23_7_5_live_shadow import (
    EXPECTED_POINTS,
    QDRANT_MANIFEST,
    QDRANT_RELEASE,
    VECTOR_DIMENSION,
    VECTOR_NAME,
)
from .m23_7_r1_semantic_alignment import (
    canonical_fixture_samples,
    compile_probe_plan,
)
from .m23_7_r1_semantic_alignment import (
    canonical_manifest as r1_manifest,
)
from .m23_7_r2_latency_path import StrictModeSafeBatchLatencyClient

SCHEMA_VERSION = "knowledge-engine-m23-7-r2-regional-binding/v1"
REPORT_SCHEMA_VERSION = "knowledge-engine-m23-7-r2-regional-binding-report/v1"
WORKER_RESPONSE_SCHEMA = "knowledge-engine-m23-7-r2-binding-worker-response/v1"
ENTRY_ENGINE_SHA = "72bf4e738d3ab73a13ea59f666cea36ee3a33eb1"
IMPLEMENTATION_ISSUE = 465
PARENT_ISSUE = 463
TRIGGER_RECEIPT_SHA256 = (
    "17ffeee8b8bc49d0d26126da617416a8d89870dc59b98f6085d2b0edba631bca"
)
R2_CONTRACT_SHA256 = (
    "5cb54b4fda94edd375235762fb546ce162bb512b419e03695755b0809603dd92"
)
R1_MANIFEST_SHA256 = (
    "ebff335d572461f4438ed06c4cc35288b0d0def8bbfc2b51e80bb262db12c576"
)
R1_REPORT_SHA256 = (
    "7ee8ddf6bf955cf0c1a10dd5442aa60d0b4b791bc2f3f4deba386213adf815e1"
)
SOURCE_PR_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
SAMPLE_CAP = 8
TOP_K = 5
MAX_SHADOW_P95_MS = 1200
WORKER_DATA_PLANE_CALLS = 2
DIRECT_DATA_PLANE_CALLS = 2
MAX_WORKER_RESPONSE_BYTES = 128_000

BLOCKERS = (
    "blocked_pending_latency",
    "blocked_pending_retrieval_quality",
)

PROTECTED_MUTATIONS = (
    "answer_serving",
    "candidate_mode",
    "credential_rotation",
    "deployment_production",
    "graph_neural_retrieval",
    "live_traffic",
    "permanent_ledger",
    "production_pointer",
    "production_query_mirroring",
    "promotion",
    "public_graph_explorer",
    "qdrant_delete",
    "qdrant_write",
    "r2_mutation",
    "source_mutation",
    "source_pr_19_merge",
    "user_sampling",
    "worker_queue_mutation",
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7-R2.1-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), 101, f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    valid = not isinstance(value, (str, bytes)) and isinstance(value, Sequence)
    _require(valid, 102, f"{label} must be a list")
    return tuple(value)


def _elapsed_ms(start_ns: int, end_ns: int) -> int:
    return max(0, math.ceil((end_ns - start_ns) / 1_000_000))


def _bounded_label(value: str, label: str) -> str:
    _require(isinstance(value, str), 103, f"{label} must be a string")
    candidate = value.strip().lower()
    _require(
        bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{2,39}", candidate)),
        104,
        f"{label} is invalid",
    )
    _require("http" not in candidate and "token" not in candidate, 105, f"{label} is unsafe")
    return candidate


def canonical_contract() -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R2.1",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "workstream": "workers_ai_binding_qdrant_placement",
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "trigger_receipt_sha256": TRIGGER_RECEIPT_SHA256,
            "trigger_status": "rejected_latency_path",
            "trigger_direct_batch_shadow_ms": 1235,
            "trigger_budget_miss_ms": 35,
            "r2_contract_sha256": R2_CONTRACT_SHA256,
            "r1_manifest_sha256": R1_MANIFEST_SHA256,
            "r1_report_sha256": R1_REPORT_SHA256,
            "source_pr_19": {
                "state": "open",
                "draft": True,
                "merged": False,
                "head_sha": SOURCE_PR_HEAD,
            },
        },
        "paths": {
            "baseline": {
                "id": "direct-rest-batch-mac-mini",
                "provider": "cloudflare-workers-ai-rest",
                "qdrant": "direct-https",
                "data_plane_requests": DIRECT_DATA_PLANE_CALLS,
            },
            "candidate": {
                "id": "workers-ai-binding-qdrant-placement",
                "provider": "workers-ai-binding",
                "qdrant": "placed-worker-query-batch",
                "data_plane_requests": WORKER_DATA_PLANE_CALLS,
                "placement": "hostname-generated-at-operator-time",
            },
            "same_probe_identity_required": True,
            "ranked_result_equivalence_required": True,
        },
        "worker_contract": {
            "model": "@cf/baai/bge-m3",
            "ai_binding": "AI",
            "qdrant_endpoint": "/points/query/batch",
            "sample_cap": SAMPLE_CAP,
            "top_k": TOP_K,
            "request_auth": "timing-safe-bearer-secret",
            "generated_config_committed": False,
            "service_hostname_persisted": False,
            "diagnostic_deployment_delete_after_reconciliation": True,
        },
        "budget": {
            "canonical_max_shadow_p95_ms": MAX_SHADOW_P95_MS,
            "applies_to": "worker_internal_provider_plus_qdrant",
            "operator_round_trip_informational": True,
            "budget_changed": False,
            "budget_inflation_allowed": False,
        },
        "exit_semantics": {
            "r2_1_complete_requires_live_receipt": True,
            "latency_blocker_cleared_only_below_budget": True,
            "retrieval_quality_blocker_cleared": False,
            "r3_required": True,
            "new_promotion_decision_required": True,
        },
        "carry_forward_blockers": list(BLOCKERS),
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "semantic_output_served": False,
            "production_authority": False,
            "promotion_eligibility_granted": False,
        },
        "protected_mutations": {key: False for key in PROTECTED_MUTATIONS},
    }
    contract["contract_sha256"] = canonical_sha256(contract)
    return contract


def validate_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(_mapping(payload, "contract"))
    digest = root.pop("contract_sha256", None)
    _require(digest == canonical_sha256(root), 106, "contract digest mismatch")
    expected = canonical_contract()
    expected_digest = expected.pop("contract_sha256")
    _require(root == expected, 107, "contract drifted")
    _require(digest == expected_digest, 108, "contract identity drifted")
    return {**root, "contract_sha256": digest}


def validate_wrangler_config(path: Path, qdrant_url: str) -> dict[str, Any]:
    parsed = urlparse(qdrant_url)
    _require(parsed.scheme == "https" and bool(parsed.hostname), 109, "Qdrant URL must use HTTPS")
    raw = path.read_text(encoding="utf-8")
    _require(len(raw) <= 30_000, 110, "Wrangler config is too large")
    payload = json.loads(raw)
    root = _mapping(payload, "Wrangler config")
    placement = _mapping(root.get("placement"), "Wrangler placement")
    ai = _mapping(root.get("ai"), "Wrangler AI binding")
    _require(placement.get("hostname") == parsed.hostname, 111, "placement hostname drifted")
    _require(ai.get("binding") == "AI", 112, "Workers AI binding drifted")
    _require(root.get("main") == "worker.mjs", 113, "Worker entrypoint drifted")
    encoded = canonical_json(root)
    for forbidden in ("QDRANT_API_KEY", "M23_R2_OPERATOR_TOKEN", qdrant_url):
        _require(forbidden not in encoded, 114, "secret or service URL persisted in config")
    return {
        "config_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "placement_hostname_sha256": hashlib.sha256(parsed.hostname.encode()).hexdigest(),
        "ai_binding": "AI",
        "generated_config_committed": False,
    }


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
        _require(snapshot.get(key) == value, 115, f"collection identity drifted: {key}")
    indexed = snapshot.get("indexed_vectors_count")
    _require(isinstance(indexed, int) and indexed >= 0, 116, "indexed vector count invalid")
    return {**expected, "indexed_vectors_count": indexed}


def _ranked_ids(points: Sequence[Mapping[str, Any]]) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for raw in points:
        payload = _mapping(raw.get("payload"), "ranked payload")
        expected = {
            "audience": "public",
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
            _require(payload.get(key) == value, 117, f"ranked point drifted: {key}")
        section_id = payload.get("section_id")
        score = raw.get("score")
        _require(isinstance(section_id, str) and bool(section_id), 118, "ranked section missing")
        _require(
            isinstance(score, (int, float)) and not isinstance(score, bool),
            119,
            "ranked score invalid",
        )
        number = float(score)
        _require(math.isfinite(number) and -1.0 <= number <= 1.0, 120, "ranked score invalid")
        ranked.append((number, section_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [section_id for _, section_id in ranked]


class RegionalWorkerInvoker(Protocol):
    def invoke(
        self,
        probes: Sequence[Mapping[str, Any]],
        *,
        nonce: str,
        clock_ns: Callable[[], int],
    ) -> dict[str, Any]: ...


class HttpRegionalWorkerInvoker:
    def __init__(self, endpoint: str, operator_token: str, timeout_seconds: float = 30.0) -> None:
        parsed = urlparse(endpoint)
        _require(
            parsed.scheme == "https" and bool(parsed.netloc),
            121,
            "Worker endpoint must use HTTPS",
        )
        _require(len(endpoint) <= 2_000, 122, "Worker endpoint is too long")
        _require(len(operator_token) >= 32, 123, "operator token is too short")
        self._endpoint = endpoint
        self._operator_token = operator_token
        self._http = httpx.Client(timeout=timeout_seconds)
        self._closed = False

    def __enter__(self) -> HttpRegionalWorkerInvoker:
        _require(not self._closed, 124, "Worker invoker is closed")
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._http.close()
        self._closed = True

    def invoke(
        self,
        probes: Sequence[Mapping[str, Any]],
        *,
        nonce: str,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
    ) -> dict[str, Any]:
        _require(not self._closed, 125, "Worker invoker is closed")
        body = {
            "schema_version": "knowledge-engine-m23-7-r2-binding-worker-request/v1",
            "nonce": nonce,
            "queries": [
                {
                    "probe_id": probe["probe_id"],
                    "query_digest": probe["query_digest"],
                    "target_section_id": probe["target_section_id"],
                    "query_text": probe["query_text"],
                }
                for probe in probes
            ],
        }
        started = clock_ns()
        try:
            response = self._http.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._operator_token}",
                    "Content-Type": "application/json",
                    "Cache-Control": "no-store",
                },
                content=canonical_json(body).encode(),
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise IntegrityError("M23.7-R2.1-126 placed Worker timed out") from exc
        except httpx.HTTPError as exc:
            raise IntegrityError("M23.7-R2.1-127 placed Worker unavailable") from exc
        finished = clock_ns()
        _require(
            len(response.content) <= MAX_WORKER_RESPONSE_BYTES,
            128,
            "Worker response too large",
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrityError("M23.7-R2.1-129 Worker response is not JSON") from exc
        root = dict(_mapping(payload, "Worker response"))
        encoded = canonical_json(root)
        for probe in probes:
            _require(probe["query_text"] not in encoded, 130, "Worker reflected raw query text")
        placement = response.headers.get("cf-placement")
        if placement is not None:
            _require(
                bool(re.fullmatch(r"(?:local|remote)-[A-Z0-9]{3}", placement)),
                131,
                "placement header is invalid",
            )
        return {
            "payload": root,
            "operator_round_trip_ms": _elapsed_ms(started, finished),
            "cf_placement": placement,
        }


def _direct_batch(
    client: StrictModeSafeBatchLatencyClient,
    *,
    clock_ns: Callable[[], int],
) -> dict[str, Any]:
    before = _validate_snapshot(client.collection_snapshot())
    samples = list(client.sample_points(SAMPLE_CAP))
    _require(len(samples) == SAMPLE_CAP, 132, "exactly eight samples are required")
    probes = compile_probe_plan(r1_manifest(), samples)
    query_texts = [probe["query_text"] for probe in probes]

    started = clock_ns()
    vectors = list(client.embed_batch(query_texts))
    provider_end = clock_ns()
    _require(len(vectors) == SAMPLE_CAP, 133, "direct embedding count drifted")
    qdrant_start = clock_ns()
    results = list(client.query_batch(vectors, TOP_K))
    qdrant_end = clock_ns()
    _require(len(results) == SAMPLE_CAP, 134, "direct result count drifted")
    rankings = [_ranked_ids(points) for points in results]
    after = _validate_snapshot(client.collection_snapshot())
    _require(before == after, 135, "collection changed during direct batch")

    return {
        "probes": probes,
        "rankings": rankings,
        "collection_before": before,
        "collection_after": after,
        "provider_ms": _elapsed_ms(started, provider_end),
        "qdrant_ms": _elapsed_ms(qdrant_start, qdrant_end),
        "shadow_ms": _elapsed_ms(started, qdrant_end),
    }


def _worker_result(
    worker_result: Mapping[str, Any],
    probes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = _mapping(worker_result.get("payload"), "Worker result payload")
    _require(payload.get("schema_version") == WORKER_RESPONSE_SCHEMA, 136, "Worker schema drifted")
    _require(payload.get("status") == "ok", 137, "Worker status is not ok")
    nonce = payload.get("nonce")
    _require(isinstance(nonce, str) and bool(nonce), 138, "Worker nonce missing")
    query_digests = list(_sequence(payload.get("query_digests"), "Worker query digests"))
    expected_digests = [probe["query_digest"] for probe in probes]
    _require(query_digests == expected_digests, 139, "Worker query identity drifted")

    cases = list(_sequence(payload.get("cases"), "Worker cases"))
    _require(len(cases) == SAMPLE_CAP, 140, "Worker case count drifted")
    rankings: list[list[str]] = []
    for probe, raw_case in zip(probes, cases, strict=True):
        case = _mapping(raw_case, "Worker case")
        _require(case.get("probe_id") == probe["probe_id"], 141, "Worker probe id drifted")
        _require(case.get("query_digest") == probe["query_digest"], 142, "Worker digest drifted")
        _require(
            case.get("target_section_id") == probe["target_section_id"],
            143,
            "Worker target drifted",
        )
        ranked = list(_sequence(case.get("ranked_section_ids"), "Worker rankings"))
        _require(
            all(isinstance(item, str) and item for item in ranked),
            144,
            "Worker ranking invalid",
        )
        rankings.append(ranked)

    before = _validate_snapshot(
        _mapping(payload.get("collection_before"), "Worker collection before")
    )
    after = _validate_snapshot(_mapping(payload.get("collection_after"), "Worker collection after"))
    _require(before == after, 145, "collection changed during Worker comparison")

    timings = _mapping(payload.get("timings"), "Worker timings")
    provider_ms = timings.get("provider_ms")
    qdrant_ms = timings.get("qdrant_ms")
    shadow_ms = timings.get("shadow_ms")
    for value in (provider_ms, qdrant_ms, shadow_ms):
        _require(isinstance(value, int) and value >= 0, 146, "Worker timing invalid")
    _require(shadow_ms >= provider_ms and shadow_ms >= qdrant_ms, 147, "Worker timing drifted")

    acceptance = _mapping(payload.get("acceptance"), "Worker acceptance")
    _require(acceptance.get("error_rate") == 0.0, 148, "Worker error rate drifted")
    _require(acceptance.get("acl_violation_rate") == 0.0, 149, "Worker ACL rate drifted")
    _require(acceptance.get("output_influence_rate") == 0.0, 150, "Worker output influence drifted")
    authority = _mapping(payload.get("authority"), "Worker authority")
    _require(authority.get("production_retrieval") == "lexical", 151, "Worker authority drifted")
    _require(
        authority.get("protected_mutations_dispatched") is False,
        152,
        "Worker mutation detected",
    )
    external = _mapping(payload.get("external_calls"), "Worker external calls")
    _require(external.get("workers_ai_binding") == 1, 153, "Workers AI call count drifted")
    _require(external.get("qdrant_query_batch") == 1, 154, "Qdrant batch count drifted")
    _require(external.get("qdrant_write") == 0, 155, "Qdrant write detected")

    return {
        "nonce": nonce,
        "rankings": rankings,
        "collection_before": before,
        "collection_after": after,
        "provider_ms": provider_ms,
        "qdrant_ms": qdrant_ms,
        "shadow_ms": shadow_ms,
        "operator_round_trip_ms": worker_result["operator_round_trip_ms"],
        "cf_placement": worker_result.get("cf_placement"),
    }


def _build_report(
    *,
    contract: Mapping[str, Any],
    probes: Sequence[Mapping[str, Any]],
    direct: Mapping[str, Any],
    worker: Mapping[str, Any],
    direct_origin: str,
    worker_origin: str,
    placement_config: Mapping[str, Any],
) -> dict[str, Any]:
    direct_rankings = list(direct["rankings"])
    worker_rankings = list(worker["rankings"])
    _require(direct_rankings == worker_rankings, 156, "placed Worker rankings drifted")
    _require(worker["nonce"], 157, "Worker nonce missing")
    latency_pass = worker["shadow_ms"] <= MAX_SHADOW_P95_MS
    remaining = ["blocked_pending_retrieval_quality"]
    if not latency_pass:
        remaining.insert(0, "blocked_pending_latency")

    cases = [
        {
            "probe_id": probe["probe_id"],
            "query_digest": probe["query_digest"],
            "target_section_id": probe["target_section_id"],
            "ranked_section_ids": ranked,
            "target_in_top_5": probe["target_section_id"] in ranked[:TOP_K],
            "raw_query_persisted": False,
            "output_influenced": False,
        }
        for probe, ranked in zip(probes, worker_rankings, strict=True)
    ]

    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": (
            "pass_regional_path_qualified" if latency_pass else "rejected_regional_path"
        ),
        "milestone": "M23.7-R2.1",
        "workstream": "workers_ai_binding_qdrant_placement",
        "contract_sha256": contract["contract_sha256"],
        "trigger_receipt_sha256": TRIGGER_RECEIPT_SHA256,
        "placement_config": dict(placement_config),
        "paths": {
            "baseline": {
                "id": "direct-rest-batch-mac-mini",
                "origin_label": _bounded_label(direct_origin, "direct origin"),
                "data_plane_requests": DIRECT_DATA_PLANE_CALLS,
                "provider_ms": direct["provider_ms"],
                "qdrant_ms": direct["qdrant_ms"],
                "shadow_ms": direct["shadow_ms"],
                "collection_before": direct["collection_before"],
                "collection_after": direct["collection_after"],
            },
            "candidate": {
                "id": "workers-ai-binding-qdrant-placement",
                "origin_label": _bounded_label(worker_origin, "Worker origin"),
                "data_plane_requests": WORKER_DATA_PLANE_CALLS,
                "provider_ms": worker["provider_ms"],
                "qdrant_ms": worker["qdrant_ms"],
                "shadow_ms": worker["shadow_ms"],
                "operator_round_trip_ms": worker["operator_round_trip_ms"],
                "cf_placement": worker.get("cf_placement"),
                "collection_before": worker["collection_before"],
                "collection_after": worker["collection_after"],
            },
        },
        "cases": cases,
        "comparison": {
            "probe_identity_equivalent": True,
            "ranked_results_equivalent": True,
            "direct_and_worker_collection_identity_equivalent": (
                direct["collection_before"] == worker["collection_before"]
            ),
            "connection_reuse_preserved": True,
            "worker_internal_shadow_improvement_ms": (
                direct["shadow_ms"] - worker["shadow_ms"]
            ),
        },
        "acceptance": {
            "canonical_max_shadow_p95_ms": MAX_SHADOW_P95_MS,
            "canonical_budget_applies_to": "worker_internal_provider_plus_qdrant",
            "operator_round_trip_informational": True,
            "canonical_budget_changed": False,
            "budget_inflation_used": False,
            "worker_internal_shadow_budget_pass": latency_pass,
            "error_rate": 0.0,
            "acl_violation_rate": 0.0,
            "output_influence_rate": 0.0,
        },
        "privacy": {
            "compiled_raw_queries_persisted": False,
            "raw_answers_persisted": False,
            "credentials_persisted": False,
            "service_urls_persisted": False,
            "service_hostnames_persisted": False,
            "arbitrary_exception_text_persisted": False,
        },
        "exit": {
            "r2_1_complete": latency_pass,
            "latency_blocker_cleared": latency_pass,
            "retrieval_quality_blocker_cleared": False,
            "r3_ready": latency_pass,
            "diagnostic_worker_delete_after_reconciliation": True,
            "new_promotion_decision_required": True,
            "promotion_eligibility_granted": False,
        },
        "remaining_blockers": remaining,
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "semantic_output_served": False,
            "production_authority": False,
            "protected_mutations_dispatched": False,
        },
        "external_calls": {
            "direct_provider_read_only": 1,
            "direct_qdrant_read_only": 4,
            "worker_ai_binding": 1,
            "worker_qdrant_read_only": 3,
            "qdrant_write": 0,
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


def run_regional_binding_comparison(
    direct_client: StrictModeSafeBatchLatencyClient,
    worker_invoker: RegionalWorkerInvoker,
    *,
    direct_origin: str,
    worker_origin: str,
    placement_config: Mapping[str, Any],
    nonce: str | None = None,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> dict[str, Any]:
    contract = validate_contract(canonical_contract())
    direct = _direct_batch(direct_client, clock_ns=clock_ns)
    probes = direct["probes"]
    safe_nonce = nonce or secrets.token_hex(16)
    _require(bool(re.fullmatch(r"[a-f0-9]{32}", safe_nonce)), 158, "nonce is invalid")
    raw_worker = worker_invoker.invoke(probes, nonce=safe_nonce, clock_ns=clock_ns)
    worker = _worker_result(raw_worker, probes)
    _require(worker["nonce"] == safe_nonce, 159, "Worker nonce drifted")
    return _build_report(
        contract=contract,
        probes=probes,
        direct=direct,
        worker=worker,
        direct_origin=direct_origin,
        worker_origin=worker_origin,
        placement_config=placement_config,
    )


def build_fixture_report() -> dict[str, Any]:
    contract = validate_contract(canonical_contract())
    probes = compile_probe_plan(r1_manifest(), canonical_fixture_samples())
    rankings = [[probe["target_section_id"]] for probe in probes]
    snapshot = {
        "status": "green",
        "points_count": EXPECTED_POINTS,
        "indexed_vectors_count": 0,
        "vector_name": VECTOR_NAME,
        "vector_dimension": VECTOR_DIMENSION,
        "distance": "Cosine",
        "sparse_vectors": None,
        "read_only": True,
    }
    direct = {
        "rankings": rankings,
        "collection_before": snapshot,
        "collection_after": snapshot,
        "provider_ms": 410,
        "qdrant_ms": 820,
        "shadow_ms": 1230,
    }
    worker = {
        "nonce": "0" * 32,
        "rankings": rankings,
        "collection_before": snapshot,
        "collection_after": snapshot,
        "provider_ms": 280,
        "qdrant_ms": 650,
        "shadow_ms": 930,
        "operator_round_trip_ms": 1010,
        "cf_placement": "remote-NRT",
    }
    placement_config = {
        "config_sha256": "1" * 64,
        "placement_hostname_sha256": "2" * 64,
        "ai_binding": "AI",
        "generated_config_committed": False,
    }
    return _build_report(
        contract=contract,
        probes=probes,
        direct=direct,
        worker=worker,
        direct_origin="fixture-direct",
        worker_origin="fixture-worker",
        placement_config=placement_config,
    )


def validate_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(_mapping(payload, "report"))
    digest = root.pop("report_sha256", None)
    _require(digest == canonical_sha256(root), 160, "report digest mismatch")
    _require(
        root.get("contract_sha256") == canonical_contract()["contract_sha256"],
        161,
        "contract identity drifted",
    )
    status = root.get("status")
    _require(
        status in {"pass_regional_path_qualified", "rejected_regional_path"},
        162,
        "unsupported report status",
    )
    paths = _mapping(root.get("paths"), "paths")
    baseline = _mapping(paths.get("baseline"), "baseline")
    candidate = _mapping(paths.get("candidate"), "candidate")
    _require(baseline.get("data_plane_requests") == 2, 163, "baseline request count drifted")
    _require(candidate.get("data_plane_requests") == 2, 164, "candidate request count drifted")
    shadow_ms = candidate.get("shadow_ms")
    _require(isinstance(shadow_ms, int) and shadow_ms >= 0, 165, "candidate latency invalid")
    latency_pass = shadow_ms <= MAX_SHADOW_P95_MS
    expected_status = "pass_regional_path_qualified" if latency_pass else "rejected_regional_path"
    _require(status == expected_status, 166, "status does not match latency")

    comparison = _mapping(root.get("comparison"), "comparison")
    _require(comparison.get("probe_identity_equivalent") is True, 167, "probe identity drifted")
    _require(comparison.get("ranked_results_equivalent") is True, 168, "ranking drifted")
    acceptance = _mapping(root.get("acceptance"), "acceptance")
    _require(
        acceptance.get("canonical_max_shadow_p95_ms") == MAX_SHADOW_P95_MS,
        169,
        "canonical budget drifted",
    )
    _require(acceptance.get("canonical_budget_changed") is False, 170, "budget changed")
    _require(acceptance.get("budget_inflation_used") is False, 171, "budget inflated")
    _require(
        acceptance.get("worker_internal_shadow_budget_pass") is latency_pass,
        172,
        "budget result drifted",
    )
    _require(acceptance.get("error_rate") == 0.0, 173, "error rate drifted")
    _require(acceptance.get("acl_violation_rate") == 0.0, 174, "ACL rate drifted")
    _require(acceptance.get("output_influence_rate") == 0.0, 175, "output influence drifted")

    exit_state = _mapping(root.get("exit"), "exit")
    _require(exit_state.get("r2_1_complete") is latency_pass, 176, "R2.1 exit drifted")
    _require(
        exit_state.get("latency_blocker_cleared") is latency_pass,
        177,
        "latency blocker drifted",
    )
    _require(
        exit_state.get("retrieval_quality_blocker_cleared") is False,
        178,
        "retrieval blocker cleared",
    )
    _require(exit_state.get("promotion_eligibility_granted") is False, 179, "promotion claimed")
    remaining = list(_sequence(root.get("remaining_blockers"), "remaining blockers"))
    expected_remaining = ["blocked_pending_retrieval_quality"]
    if not latency_pass:
        expected_remaining.insert(0, "blocked_pending_latency")
    _require(remaining == expected_remaining, 180, "remaining blockers drifted")

    placement = _mapping(root.get("placement_config"), "placement config")
    _require(placement.get("ai_binding") == "AI", 181, "AI binding drifted")
    _require(
        placement.get("generated_config_committed") is False,
        182,
        "generated config committed",
    )
    for key in ("config_sha256", "placement_hostname_sha256"):
        value = placement.get(key)
        _require(bool(re.fullmatch(r"[a-f0-9]{64}", value or "")), 183, f"{key} invalid")

    privacy = _mapping(root.get("privacy"), "privacy")
    _require(all(value is False for value in privacy.values()), 184, "privacy boundary drifted")
    authority = _mapping(root.get("authority"), "authority")
    _require(
        authority.get("production_retrieval") == "lexical",
        185,
        "production retrieval drifted",
    )
    _require(authority.get("candidate_mode_enabled") is False, 186, "candidate mode enabled")
    _require(authority.get("protected_mutations_dispatched") is False, 187, "mutation detected")
    external = _mapping(root.get("external_calls"), "external calls")
    _require(external.get("worker_ai_binding") == 1, 188, "Worker AI call drifted")
    _require(external.get("qdrant_write") == 0, 189, "Qdrant write detected")
    return {**root, "report_sha256": digest}
