from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
import re
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from . import m23_7_r3_5_rank_quality_calibration_runtime as r35
from . import m23_7_r3_6_candidate_reingestion as r36
from . import m23_7_r3_7_live_acceptance as r37
from .errors import IntegrityError

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-8-latency-repair/v1"
RECEIPT_SCHEMA_VERSION = "knowledge-engine-m23-7-r3-8-latency-repair-receipt/v1"
WORKER_REQUEST_SCHEMA = "knowledge-engine-m23-7-r3-8-worker-request/v1"
WORKER_RESPONSE_SCHEMA = "knowledge-engine-m23-7-r3-8-worker-response/v1"
IMPLEMENTATION_ISSUE = 520
PARENT_ISSUE = 474
ENTRY_ENGINE_SHA = "7793cd22092aca530ca48a3240a3c83ffd3d2894"
CONTRACT_SHA256 = "2224bfe20772855181e5f8ada706be307d9e55c340f94c939366ef896c309e01"

EXPECTED_COLLECTION = r37.EXPECTED_COLLECTION
HISTORICAL_PILOT_COLLECTION = r37.HISTORICAL_PILOT_COLLECTION
EXPECTED_POINT_COUNT = r37.EXPECTED_POINT_COUNT
VECTOR_NAME = r37.VECTOR_NAME
VECTOR_DIMENSION = r37.VECTOR_DIMENSION
PAYLOAD_SCHEMA = r37.PAYLOAD_SCHEMA
PROBE_COUNT = r37.PROBE_COUNT
VARIANTS_PER_PROBE = r37.VARIANTS_PER_PROBE
QUERY_COUNT = r37.QUERY_COUNT
DENSE_LIMIT = r37.DENSE_LIMIT
MAX_WORKER_SHADOW_MS = r37.MAX_LIVE_P95_MS
MAXIMUM_HUB_FREQUENCY = r37.MAXIMUM_HUB_FREQUENCY
EXPECTED_METRICS = r37.ACCEPTED_METRICS
EXPECTED_TARGET_RANKS = r37.ACCEPTED_TARGET_RANKS
MAX_RESPONSE_BYTES = 500_000
_WORKER_ERROR_CODE = re.compile(r"^[a-z0-9-]{1,80}$")


class LatencyRepairError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise LatencyRepairError(code, message)


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


def canonical_contract() -> dict[str, Any]:
    ranker_source = inspect.getsource(r37.live_calibrated_ranking)
    forbidden = (
        "target_section_id",
        "expected_relevant_ids",
        "offline_case_id",
        "probe_id",
    )
    _require(
        not any(term in ranker_source for term in forbidden),
        "target_aware_ranker",
        "accepted ranker accepts target-aware inputs",
    )
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R3.8",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "r3_7_contract_sha256": r37.CONTRACT_SHA256,
            "r3_7_receipt_file_sha256": (
                "72c8d9cc6a9262960659c75e87ac9cf6f6e73008633bc255f3c944681abcf4c2"
            ),
            "r3_7_receipt_sha256": (
                "55ccb6ccdb7f02fcc9ba7302c37021d6cd747af49ec8250c955e924979a3509a"
            ),
            "r3_7_evidence_seal_sha256": (
                "e5c35247dd10be17dfa526842e3f9dd27d875278d31c5537786e25bf0b17ecdd"
            ),
            "r3_7_reconciliation_sha256": (
                "861a0156aba827d4c6eb62ee13e8025cba466fdbe28c60328056c2ec0b88c918"
            ),
            "trigger_status": "completed_fail_closed_live_acceptance",
            "trigger_live_p95_ms": 1739,
            "trigger_maximum_live_p95_ms": 1200,
        },
        "worker": {
            "name": "knowledge-engine-m23-7-r3-8-latency",
            "route": "/v1/m23-7-r3-8/observe",
            "request_schema": WORKER_REQUEST_SCHEMA,
            "response_schema": WORKER_RESPONSE_SCHEMA,
            "model": "@cf/baai/bge-m3",
            "ai_binding": "AI",
            "placement": "hostname-generated-at-operator-time",
            "generated_config_committed": False,
            "request_auth": "timing-safe-bearer-secret",
            "maximum_body_bytes": 65536,
            "diagnostic_deployment_delete_after_reconciliation": True,
        },
        "collection": {
            "name": EXPECTED_COLLECTION,
            "historical_pilot": HISTORICAL_PILOT_COLLECTION,
            "point_count": EXPECTED_POINT_COUNT,
            "vector_name": VECTOR_NAME,
            "vector_dimension": VECTOR_DIMENSION,
            "distance": "Cosine",
            "payload_schema_version": PAYLOAD_SCHEMA,
            "schema_pre_post_exact": True,
        },
        "queries": {
            "probe_count": PROBE_COUNT,
            "variants_per_probe": VARIANTS_PER_PROBE,
            "query_count": QUERY_COUNT,
            "unique_query_identities": QUERY_COUNT,
            "workers_ai_binding_calls": 1,
            "qdrant_query_batch_calls": 0,
            "qdrant_vector_scroll_calls": 1,
            "qdrant_dense_limit": DENSE_LIMIT,
            "target_aware_inputs": False,
        },
        "quality": {
            "min_recall_at_5": r37.base_r35.r34.MIN_RECALL_AT_5,
            "min_mrr_at_10": r37.base_r35.r34.MIN_MRR_AT_10,
            "min_ndcg_at_10": r37.base_r35.r34.MIN_NDCG_AT_10,
            "accepted_metrics": EXPECTED_METRICS,
            "accepted_target_ranks": EXPECTED_TARGET_RANKS,
            "max_top10_hub_frequency": MAXIMUM_HUB_FREQUENCY,
            "exact_metric_parity": True,
            "exact_target_rank_parity": True,
        },
        "latency": {
            "maximum_worker_internal_shadow_ms": MAX_WORKER_SHADOW_MS,
            "applies_to": (
                "single_worker_invocation_workers_ai_binding_plus_qdrant_vector_scroll"
            ),
            "operator_round_trip_informational": True,
            "threshold_changed": False,
            "threshold_inflation_allowed": False,
        },
        "strict_zero": {
            "query_error_rate": 0.0,
            "acl_violation_rate": 0.0,
            "output_influence_rate": 0.0,
            "qdrant_writes": 0,
            "qdrant_deletes": 0,
            "qdrant_reindex": 0,
            "protected_mutations": 0,
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
            "transient_diagnostic_worker_deploy_authorized": True,
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
            "latency_blocker_cleared": False,
            "production_retrieval": "lexical",
        },
    }
    _require(
        canonical_sha256(contract) == CONTRACT_SHA256,
        "contract_digest",
        "R3.8 contract digest drifted",
    )
    return {**contract, "contract_sha256": CONTRACT_SHA256}


def validate_wrangler_config(path: Path, qdrant_url: str) -> dict[str, Any]:
    parsed = urlparse(qdrant_url)
    _require(
        parsed.scheme == "https" and bool(parsed.hostname),
        "qdrant_url",
        "Qdrant URL must be HTTPS",
    )
    raw = path.read_text(encoding="utf-8")
    _require(len(raw) <= 30_000, "wrangler_size", "Wrangler config is too large")
    payload = json.loads(raw)
    _require(isinstance(payload, Mapping), "wrangler_shape", "Wrangler config is invalid")
    placement = payload.get("placement")
    ai = payload.get("ai")
    _require(isinstance(placement, Mapping), "placement_shape", "placement is missing")
    _require(isinstance(ai, Mapping), "ai_shape", "AI binding is missing")
    _require(
        placement.get("hostname") == parsed.hostname,
        "placement_hostname",
        "placement hostname drifted",
    )
    _require(ai.get("binding") == "AI", "ai_binding", "AI binding drifted")
    _require(payload.get("main") == "worker.mjs", "worker_main", "Worker main drifted")
    _require(
        payload.get("name") == "knowledge-engine-m23-7-r3-8-latency",
        "worker_name",
        "Worker name drifted",
    )
    encoded = canonical_json(payload)
    for forbidden in ("QDRANT_API_KEY", "M23_R3_8_OPERATOR_TOKEN", qdrant_url):
        _require(forbidden not in encoded, "wrangler_secret", "secret persisted in config")
    return {
        "config_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "placement_hostname_sha256": hashlib.sha256(parsed.hostname.encode()).hexdigest(),
        "generated_config_committed": False,
        "ai_binding": "AI",
    }


def build_worker_request(candidate: Mapping[str, Any], *, nonce: str) -> dict[str, Any]:
    _require(
        isinstance(nonce, str)
        and len(nonce) == 32
        and all(character in "0123456789abcdef" for character in nonce),
        "nonce",
        "nonce is invalid",
    )
    variants: list[dict[str, str]] = []
    for probe in candidate["probe_plan"]:
        for variant in probe["variants"]:
            variants.append(
                {
                    "variant_id": str(variant["variant_id"]),
                    "query_sha256": str(variant["query_text_sha256"]),
                    "query_text": str(variant["query_text"]),
                }
            )
    _require(len(variants) == QUERY_COUNT, "query_count", "query count drifted")
    _require(
        len({item["query_sha256"] for item in variants}) == QUERY_COUNT,
        "query_identity",
        "query identities are not unique",
    )
    return {
        "schema_version": WORKER_REQUEST_SCHEMA,
        "contract_sha256": CONTRACT_SHA256,
        "nonce": nonce,
        "variants": variants,
    }


class WorkerInvoker(Protocol):
    def invoke(
        self,
        request_body: Mapping[str, Any],
        *,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
    ) -> tuple[Mapping[str, Any], int]: ...


class HttpWorkerInvoker:
    def __init__(
        self,
        endpoint: str,
        operator_token: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        parsed = urlparse(endpoint)
        _require(
            parsed.scheme == "https" and bool(parsed.netloc),
            "worker_endpoint",
            "Worker endpoint must use HTTPS",
        )
        _require(len(endpoint) <= 2_000, "worker_endpoint", "Worker endpoint too long")
        _require(len(operator_token) >= 32, "operator_token", "operator token too short")
        self._endpoint = endpoint
        self._operator_token = operator_token
        self._http = httpx.Client(timeout=timeout_seconds)
        self._closed = False

    def __enter__(self) -> HttpWorkerInvoker:
        _require(not self._closed, "client_closed", "Worker invoker is closed")
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
        request_body: Mapping[str, Any],
        *,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
    ) -> tuple[Mapping[str, Any], int]:
        _require(not self._closed, "client_closed", "Worker invoker is closed")
        body = canonical_json(request_body).encode("utf-8")
        started = clock_ns()
        try:
            response = self._http.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._operator_token}",
                    "Content-Type": "application/json",
                    "Cache-Control": "no-store",
                    "Content-Length": str(len(body)),
                },
                content=body,
            )
            _require(
                len(response.content) <= MAX_RESPONSE_BYTES,
                "worker_response_size",
                "Worker response is too large",
            )
            if response.status_code >= 400:
                raise LatencyRepairError(
                    worker_http_error_code(response),
                    "Worker returned bounded error status",
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise LatencyRepairError(
                    "worker_unavailable", "Worker response is invalid JSON"
                ) from exc
        except httpx.TimeoutException as exc:
            raise LatencyRepairError("worker_timeout", "Worker request timed out") from exc
        except httpx.HTTPError as exc:
            raise LatencyRepairError("worker_unavailable", "Worker request failed") from exc
        finished = clock_ns()
        _require(isinstance(payload, Mapping), "worker_shape", "Worker response is invalid")
        return payload, max(0, math.ceil((finished - started) / 1_000_000))


def worker_http_error_code(response: httpx.Response) -> str:
    base = f"worker_http_{response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        return base
    if not isinstance(payload, Mapping):
        return base
    code = payload.get("code")
    if not isinstance(code, str) or not _WORKER_ERROR_CODE.fullmatch(code):
        return base
    return base + "_" + code.replace("-", "_")


def _validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "status": "green",
        "points_count": EXPECTED_POINT_COUNT,
        "vector_name": VECTOR_NAME,
        "vector_size": VECTOR_DIMENSION,
        "vector_distance": "Cosine",
        "sparse_vectors": None,
        "read_only": True,
    }
    for key, value in expected.items():
        _require(snapshot.get(key) == value, "collection_identity", f"collection drifted: {key}")
    indexed = snapshot.get("indexed_vectors_count")
    _require(
        isinstance(indexed, int) and not isinstance(indexed, bool) and indexed >= 0,
        "indexed_vectors",
        "indexed vector count invalid",
    )
    return {**expected, "indexed_vectors_count": indexed}


def _validate_worker_response(
    payload: Mapping[str, Any],
    candidate: Mapping[str, Any],
    request_body: Mapping[str, Any],
) -> tuple[list[list[tuple[float, str]]], dict[str, Any]]:
    _require(
        payload.get("schema_version") == WORKER_RESPONSE_SCHEMA,
        "response_schema",
        "Worker response schema drifted",
    )
    _require(payload.get("status") == "ok", "worker_status", "Worker status is not ok")
    _require(payload.get("nonce") == request_body["nonce"], "nonce", "nonce drifted")
    before_raw = payload.get("collection_before")
    after_raw = payload.get("collection_after")
    _require(isinstance(before_raw, Mapping), "collection_before", "collection before missing")
    _require(isinstance(after_raw, Mapping), "collection_after", "collection after missing")
    before = _validate_snapshot(before_raw)
    after = _validate_snapshot(after_raw)
    _require(before == after, "collection_drift", "collection schema changed")

    variants = list(payload.get("variants", []))
    _require(len(variants) == QUERY_COUNT, "variant_count", "Worker variant count drifted")
    expected_variants = {
        str(item["variant_id"]): str(item["query_sha256"])
        for item in request_body["variants"]
    }
    known_sections = {
        str(point["payload"]["section_id"]) for point in candidate["points"]
    }
    seen: set[str] = set()
    dense_rankings: list[list[tuple[float, str]]] = []
    for item in variants:
        _require(isinstance(item, Mapping), "variant_shape", "variant response invalid")
        variant_id = str(item.get("variant_id"))
        query_sha = str(item.get("query_sha256"))
        _require(
            expected_variants.get(variant_id) == query_sha,
            "query_identity",
            "Worker query identity drifted",
        )
        _require(variant_id not in seen, "variant_duplicate", "variant duplicated")
        seen.add(variant_id)
        ranked_ids = list(item.get("ranked_section_ids", []))
        _require(
            len(ranked_ids) == DENSE_LIMIT,
            "dense_limit",
            "Worker dense limit drifted",
        )
        _require(
            len(set(ranked_ids)) == DENSE_LIMIT
            and all(
                isinstance(value, str) and value in known_sections
                for value in ranked_ids
            ),
            "dense_identity",
            "Worker dense ranking drifted",
        )
        ranking = [
            (1.0 - rank / 10_000.0, section_id)
            for rank, section_id in enumerate(ranked_ids, start=1)
        ]
        for section_id in sorted(known_sections - set(ranked_ids)):
            ranking.append((-2.0, section_id))
        dense_rankings.append(ranking)

    _require(set(seen) == set(expected_variants), "variant_set", "variant set drifted")
    timings = payload.get("timings")
    _require(isinstance(timings, Mapping), "timings", "Worker timings missing")
    normalised_timings: dict[str, int] = {}
    for key in ("provider_ms", "qdrant_ms", "shadow_ms"):
        value = timings.get(key)
        _require(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0,
            "timing_value",
            f"Worker timing invalid: {key}",
        )
        normalised_timings[key] = value
    _require(
        normalised_timings["shadow_ms"]
        >= normalised_timings["provider_ms"] + normalised_timings["qdrant_ms"] - 5,
        "timing_consistency",
        "Worker shadow timing is inconsistent",
    )

    acceptance = payload.get("acceptance")
    authority = payload.get("authority")
    external_calls = payload.get("external_calls")
    privacy = payload.get("privacy")
    _require(isinstance(acceptance, Mapping), "acceptance", "acceptance missing")
    _require(isinstance(authority, Mapping), "authority", "authority missing")
    _require(isinstance(external_calls, Mapping), "external_calls", "external calls missing")
    _require(isinstance(privacy, Mapping), "privacy", "privacy missing")
    _require(
        acceptance
        == {
            "error_rate": 0.0,
            "acl_violation_rate": 0.0,
            "output_influence_rate": 0.0,
        },
        "strict_zero",
        "strict-zero rates drifted",
    )
    _require(
        external_calls
        == {
            "workers_ai_binding": 1,
            "qdrant_collection_reads": 2,
            "qdrant_query_batch": 0,
            "qdrant_vector_scroll": 1,
            "qdrant_write": 0,
            "qdrant_delete": 0,
            "qdrant_reindex": 0,
        },
        "external_calls",
        "external call accounting drifted",
    )
    _require(
        authority
        == {
            "production_retrieval": "lexical",
            "semantic_output_served": False,
            "production_authority": False,
            "protected_mutations_dispatched": False,
            "retrieval_quality_blocker_cleared": False,
            "latency_blocker_cleared": False,
        },
        "authority",
        "Worker authority drifted",
    )
    _require(
        privacy
        == {
            "raw_queries_persisted": False,
            "raw_answers_persisted": False,
            "credentials_persisted": False,
            "service_urls_persisted": False,
            "service_hostnames_persisted": False,
            "arbitrary_exception_text_persisted": False,
        },
        "privacy",
        "Worker privacy drifted",
    )
    return dense_rankings, {
        "collection_before": before,
        "collection_after": after,
        "timings": normalised_timings,
        "acceptance": dict(acceptance),
        "authority": dict(authority),
        "external_calls": dict(external_calls),
        "privacy": dict(privacy),
    }


def run_latency_repair(
    candidate: Mapping[str, Any],
    invoker: WorkerInvoker,
    placement_config: Mapping[str, Any],
    *,
    nonce: str | None = None,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> dict[str, Any]:
    request_body = build_worker_request(candidate, nonce=nonce or secrets.token_hex(16))
    worker_payload, operator_round_trip_ms = invoker.invoke(
        request_body,
        clock_ns=clock_ns,
    )
    dense_rankings, worker = _validate_worker_response(
        worker_payload,
        candidate,
        request_body,
    )
    evaluation = r37.evaluate_live_dense_rankings(candidate, dense_rankings)
    metrics = evaluation["metrics"]
    target_ranks = evaluation["target_ranks"]
    shadow_ms = worker["timings"]["shadow_ms"]
    gates = {
        "candidate_identity": (
            candidate.get("candidate_artifact_sha256")
            == r36.R3_5_CANDIDATE_ARTIFACT_SHA256
        ),
        "probe_count_8": len(candidate["probe_plan"]) == PROBE_COUNT,
        "query_count_24": len(request_body["variants"]) == QUERY_COUNT,
        "query_identity_unique": (
            len({item["query_sha256"] for item in request_body["variants"]})
            == QUERY_COUNT
        ),
        "collection_schema_pre_post_exact": (
            worker["collection_before"] == worker["collection_after"]
        ),
        "recall_at_5": (
            metrics["recall_at_5"] >= r37.base_r35.r34.MIN_RECALL_AT_5
        ),
        "mrr_at_10": metrics["mrr_at_10"] >= r37.base_r35.r34.MIN_MRR_AT_10,
        "ndcg_at_10": (
            metrics["ndcg_at_10"] >= r37.base_r35.r34.MIN_NDCG_AT_10
        ),
        "accepted_metric_parity": metrics == EXPECTED_METRICS,
        "exact_target_rank_parity": target_ranks == EXPECTED_TARGET_RANKS,
        "hub_frequency": (
            evaluation["maximum_top10_hub_frequency"] <= MAXIMUM_HUB_FREQUENCY
        ),
        "worker_internal_shadow": shadow_ms <= MAX_WORKER_SHADOW_MS,
        "query_error_rate_zero": worker["acceptance"]["error_rate"] == 0.0,
        "acl_violation_rate_zero": (
            worker["acceptance"]["acl_violation_rate"] == 0.0
        ),
        "output_influence_rate_zero": (
            worker["acceptance"]["output_influence_rate"] == 0.0
        ),
        "qdrant_writes_zero": worker["external_calls"]["qdrant_write"] == 0,
        "qdrant_deletes_zero": worker["external_calls"]["qdrant_delete"] == 0,
        "qdrant_reindex_zero": worker["external_calls"]["qdrant_reindex"] == 0,
        "protected_mutations_zero": (
            worker["authority"]["protected_mutations_dispatched"] is False
        ),
    }
    passed = all(gates.values())
    retained_blockers = [
        "blocked_pending_retrieval_quality",
        "blocked_pending_latency",
    ]
    report: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "milestone": "M23.7-R3.8",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "status": (
            "pass_placed_worker_latency_repair"
            if passed
            else "completed_fail_closed_latency_repair"
        ),
        "contract_sha256": CONTRACT_SHA256,
        "candidate_artifact_sha256": candidate["candidate_artifact_sha256"],
        "collection": EXPECTED_COLLECTION,
        "probe_count": PROBE_COUNT,
        "query_count": QUERY_COUNT,
        "query_identity_count": QUERY_COUNT,
        "metrics": metrics,
        "accepted_metrics": EXPECTED_METRICS,
        "target_ranks": target_ranks,
        "accepted_target_ranks": EXPECTED_TARGET_RANKS,
        "maximum_top10_hub_frequency": evaluation[
            "maximum_top10_hub_frequency"
        ],
        "quality_cases": evaluation["cases"],
        "worker": {
            "placement_config_sha256": placement_config["config_sha256"],
            "placement_hostname_sha256": placement_config[
                "placement_hostname_sha256"
            ],
            "provider_ms": worker["timings"]["provider_ms"],
            "qdrant_ms": worker["timings"]["qdrant_ms"],
            "shadow_ms": shadow_ms,
            "maximum_shadow_ms": MAX_WORKER_SHADOW_MS,
            "operator_round_trip_ms": operator_round_trip_ms,
            "operator_round_trip_informational": True,
            "collection_before": worker["collection_before"],
            "collection_after": worker["collection_after"],
            "external_calls": worker["external_calls"],
        },
        "gates": gates,
        "error_rate": worker["acceptance"]["error_rate"],
        "acl_violation_rate": worker["acceptance"]["acl_violation_rate"],
        "output_influence_rate": worker["acceptance"]["output_influence_rate"],
        "privacy": canonical_contract()["privacy"],
        "authority": {
            **canonical_contract()["authority"],
            "transient_diagnostic_worker_deployed": True,
            "qdrant_read_dispatched": True,
            "qdrant_write_dispatched": False,
            "qdrant_delete_dispatched": False,
            "qdrant_reindex_dispatched": False,
            "protected_mutations_dispatched": False,
        },
        "retained_blockers": retained_blockers,
        "exit": {
            "latency_repair_result_complete": True,
            "latency_repair_passed": passed,
            "blocker_clearance_eligible_after_reconciliation": passed,
            "evidence_seal_required": True,
            "independent_reconciliation_required": True,
            "diagnostic_worker_deletion_required_after_reconciliation": passed,
            "next_gate": "separately_governed_r3_8_evidence_seal",
        },
    }
    report["receipt_sha256"] = canonical_sha256(report)
    return report


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise LatencyRepairError("environment", f"missing environment variable: {name}")
    return value


def _write(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(report) + "\n", encoding="utf-8")


def execute(
    evidence_zip: Path,
    wrangler_config: Path,
    receipt_path: Path,
    timeout: int = 60,
) -> int:
    started = utc_now()
    try:
        candidate = r35.build_calibration_candidate(evidence_zip)
        placement = validate_wrangler_config(
            wrangler_config,
            _required_environment("QDRANT_URL"),
        )
        with HttpWorkerInvoker(
            _required_environment("M23_R3_8_WORKER_URL"),
            _required_environment("M23_R3_8_OPERATOR_TOKEN"),
            float(timeout),
        ) as invoker:
            receipt = run_latency_repair(candidate, invoker, placement)
        receipt["started_at"] = started
        receipt["completed_at"] = utc_now()
        receipt.pop("receipt_sha256", None)
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        _write(receipt_path, receipt)
        return 0 if receipt["status"] == "pass_placed_worker_latency_repair" else 30
    except (LatencyRepairError, IntegrityError, OSError, json.JSONDecodeError) as exc:
        failure_code = exc.code if isinstance(exc, LatencyRepairError) else "input_or_integrity"
        receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "milestone": "M23.7-R3.8",
            "implementation_issue": IMPLEMENTATION_ISSUE,
            "parent_issue": PARENT_ISSUE,
            "status": "rejected_incomplete_latency_repair",
            "started_at": started,
            "completed_at": utc_now(),
            "failure_code": failure_code,
            "retained_blockers": [
                "blocked_pending_retrieval_quality",
                "blocked_pending_latency",
            ],
            "authority": {
                "retrieval_quality_blocker_cleared": False,
                "latency_blocker_cleared": False,
                "production_retrieval": "lexical",
            },
            "exit": {
                "latency_repair_result_complete": False,
                "latency_repair_passed": False,
                "next_gate": "repair_or_retry_required",
            },
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        _write(receipt_path, receipt)
        return 23 if failure_code in {"environment", "input_or_integrity"} else 30


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run M23.7-R3.8 placed diagnostic Worker latency repair"
    )
    parser.add_argument("--evidence-zip", required=True)
    parser.add_argument("--wrangler-config", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return execute(
        Path(args.evidence_zip).expanduser().resolve(),
        Path(args.wrangler_config).expanduser().resolve(),
        Path(args.receipt).expanduser().resolve(),
        args.timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
