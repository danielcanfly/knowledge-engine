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
    VECTOR_DIMENSION,
    VECTOR_NAME,
)
from .m23_7_r1_semantic_alignment import (
    canonical_fixture_samples,
    compile_probe_plan,
)
from .m23_7_r1_semantic_alignment import canonical_manifest as r1_manifest

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-bounded-live-reobservation/v1"
REPORT_SCHEMA_VERSION = (
    "knowledge-engine-m23-7-r3-bounded-live-reobservation-report/v1"
)
WORKER_REQUEST_SCHEMA = "knowledge-engine-m23-7-r3-worker-request/v1"
WORKER_RESPONSE_SCHEMA = "knowledge-engine-m23-7-r3-worker-response/v1"
ENTRY_ENGINE_SHA = "5870e4dd3d10076ef7d35a1eb485b358179d9305"
IMPLEMENTATION_ISSUE = 474
REPAIR_HANDOFF_SHA256 = (
    "7fb6fadf91f1a09110bf1d0e653652f52a298ebc0119aee3743180314e16f0b9"
)
R1_MANIFEST_SHA256 = (
    "ebff335d572461f4438ed06c4cc35288b0d0def8bbfc2b51e80bb262db12c576"
)
R1_REPORT_SHA256 = (
    "7ee8ddf6bf955cf0c1a10dd5442aa60d0b4b791bc2f3f4deba386213adf815e1"
)
R2_LIVE_RECEIPT_SHA256 = (
    "aa56655d19cb617177bd8e4708c02e1cd6ce02189fcfee32a5b397ef0eba67db"
)
QUALITY_CONTRACT_SHA256 = (
    "7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1"
)
OFFLINE_EVALUATION_SHA256 = (
    "9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce"
)
SOURCE_PR_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
SAMPLE_CAP = 8
TOP_K = 10
MAX_SHADOW_P95_MS = 1200
MIN_RECALL_AT_5 = 0.82
MIN_MRR_AT_10 = 0.68
MIN_NDCG_AT_10 = 0.72
MAX_WORKER_RESPONSE_BYTES = 160_000

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
        raise IntegrityError(f"M23.7-R3-{code} {message}")


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
    _require(
        "http" not in candidate and "token" not in candidate,
        105,
        f"{label} is unsafe",
    )
    return candidate


def canonical_contract() -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R3",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "workstream": "bounded_live_reobservation",
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "m23_7_8_repair_handoff_sha256": REPAIR_HANDOFF_SHA256,
            "r1_manifest_sha256": R1_MANIFEST_SHA256,
            "r1_report_sha256": R1_REPORT_SHA256,
            "r2_1_live_receipt_sha256": R2_LIVE_RECEIPT_SHA256,
            "r2_1_worker_internal_shadow_ms": 781,
            "m23_7_1_quality_contract_sha256": QUALITY_CONTRACT_SHA256,
            "m23_7_2_offline_evaluation_sha256": OFFLINE_EVALUATION_SHA256,
            "prior_misaligned_overlap_at_5": 0.25,
            "prior_misaligned_overlap_drift": -0.70,
            "source_pr_19": {
                "state": "open",
                "draft": True,
                "merged": False,
                "head_sha": SOURCE_PR_HEAD,
            },
        },
        "probe_contract": {
            "probe_count": SAMPLE_CAP,
            "maximum_probe_count": SAMPLE_CAP,
            "source": "r1-deterministic-semantic-probes",
            "expected_relevance": "exact-bound-target-section-id",
            "top_k": TOP_K,
            "raw_query_persisted": False,
            "raw_answer_persisted": False,
            "user_queries_allowed": False,
        },
        "worker_contract": {
            "model": "@cf/baai/bge-m3",
            "ai_binding": "AI",
            "qdrant_endpoint": "/points/query/batch",
            "workers_ai_binding_calls": 1,
            "qdrant_query_batch_calls": 1,
            "request_auth": "timing-safe-bearer-secret",
            "placement": "hostname-generated-at-operator-time",
            "generated_config_committed": False,
            "service_hostname_persisted": False,
            "diagnostic_deployment_delete_after_reconciliation": True,
        },
        "thresholds": {
            "min_recall_at_5": MIN_RECALL_AT_5,
            "min_mrr_at_10": MIN_MRR_AT_10,
            "min_ndcg_at_10": MIN_NDCG_AT_10,
            "max_worker_internal_shadow_ms": MAX_SHADOW_P95_MS,
            "max_error_rate": 0.0,
            "max_acl_violation_rate": 0.0,
            "max_output_influence_rate": 0.0,
            "budget_changed": False,
            "budget_inflation_allowed": False,
        },
        "exit_semantics": {
            "r3_complete_requires_live_receipt": True,
            "retrieval_quality_blocker_cleared_only_on_all_gates": True,
            "all_repair_blockers_cleared_only_on_r3_pass": True,
            "new_explicit_promotion_decision_required": True,
            "promotion_eligibility_granted": False,
        },
        "carry_forward_blockers": ["blocked_pending_retrieval_quality"],
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
    _require(
        parsed.scheme == "https" and bool(parsed.hostname),
        109,
        "Qdrant URL must use HTTPS",
    )
    raw = path.read_text(encoding="utf-8")
    _require(len(raw) <= 30_000, 110, "Wrangler config is too large")
    root = _mapping(json.loads(raw), "Wrangler config")
    placement = _mapping(root.get("placement"), "Wrangler placement")
    ai = _mapping(root.get("ai"), "Wrangler AI binding")
    _require(
        root.get("name") == "knowledge-engine-m23-7-r3-observation",
        111,
        "Worker name drifted",
    )
    _require(
        placement.get("hostname") == parsed.hostname,
        112,
        "placement hostname drifted",
    )
    _require(ai.get("binding") == "AI", 113, "Workers AI binding drifted")
    _require(root.get("main") == "worker.mjs", 114, "Worker entrypoint drifted")
    encoded = canonical_json(root)
    for forbidden in ("QDRANT_API_KEY", "M23_R3_OPERATOR_TOKEN", qdrant_url):
        _require(forbidden not in encoded, 115, "secret or service URL persisted")
    return {
        "config_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "placement_hostname_sha256": hashlib.sha256(
            parsed.hostname.encode()
        ).hexdigest(),
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
        _require(
            snapshot.get(key) == value,
            116,
            f"collection identity drifted: {key}",
        )
    indexed = snapshot.get("indexed_vectors_count")
    _require(
        isinstance(indexed, int) and indexed >= 0,
        117,
        "indexed vector count invalid",
    )
    return {**expected, "indexed_vectors_count": indexed}


class R3WorkerInvoker(Protocol):
    def invoke(
        self,
        probes: Sequence[Mapping[str, Any]],
        *,
        nonce: str,
        clock_ns: Callable[[], int],
    ) -> dict[str, Any]: ...


class HttpR3WorkerInvoker:
    def __init__(
        self,
        endpoint: str,
        operator_token: str,
        timeout_seconds: float = 45.0,
    ) -> None:
        parsed = urlparse(endpoint)
        _require(
            parsed.scheme == "https" and bool(parsed.netloc),
            118,
            "Worker endpoint must use HTTPS",
        )
        _require(len(endpoint) <= 2_000, 119, "Worker endpoint is too long")
        _require(len(operator_token) >= 32, 120, "operator token is too short")
        self._endpoint = endpoint
        self._operator_token = operator_token
        self._http = httpx.Client(timeout=timeout_seconds)
        self._closed = False

    def __enter__(self) -> HttpR3WorkerInvoker:
        _require(not self._closed, 121, "Worker invoker is closed")
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
        _require(not self._closed, 122, "Worker invoker is closed")
        body = {
            "schema_version": WORKER_REQUEST_SCHEMA,
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
            raise IntegrityError("M23.7-R3-123 diagnostic Worker timed out") from exc
        except httpx.HTTPError as exc:
            raise IntegrityError(
                "M23.7-R3-124 diagnostic Worker unavailable"
            ) from exc
        finished = clock_ns()
        _require(
            len(response.content) <= MAX_WORKER_RESPONSE_BYTES,
            125,
            "Worker response too large",
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrityError(
                "M23.7-R3-126 Worker response is not JSON"
            ) from exc
        root = dict(_mapping(payload, "Worker response"))
        encoded = canonical_json(root)
        for probe in probes:
            _require(
                probe["query_text"] not in encoded,
                127,
                "Worker reflected raw query text",
            )
        placement = response.headers.get("cf-placement")
        if placement is not None:
            _require(
                bool(re.fullmatch(r"(?:local|remote)-[A-Z0-9]{3}", placement)),
                128,
                "placement header is invalid",
            )
        return {
            "payload": root,
            "operator_round_trip_ms": _elapsed_ms(started, finished),
            "cf_placement": placement,
        }


def _reciprocal_rank(target: str, ranked: Sequence[str]) -> float:
    for index, section_id in enumerate(ranked[:TOP_K], start=1):
        if section_id == target:
            return 1.0 / index
    return 0.0


def _ndcg(target: str, ranked: Sequence[str]) -> float:
    for index, section_id in enumerate(ranked[:TOP_K], start=1):
        if section_id == target:
            return 1.0 / math.log2(index + 1)
    return 0.0


def _validate_worker_result(
    worker_result: Mapping[str, Any],
    probes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = _mapping(worker_result.get("payload"), "Worker payload")
    _require(
        payload.get("schema_version") == WORKER_RESPONSE_SCHEMA,
        129,
        "Worker schema drifted",
    )
    _require(payload.get("status") == "ok", 130, "Worker status is not ok")
    nonce = payload.get("nonce")
    _require(isinstance(nonce, str) and bool(nonce), 131, "Worker nonce missing")
    expected_digests = [probe["query_digest"] for probe in probes]
    observed_digests = list(
        _sequence(payload.get("query_digests"), "Worker query digests")
    )
    _require(
        observed_digests == expected_digests,
        132,
        "Worker query identity drifted",
    )

    raw_cases = list(_sequence(payload.get("cases"), "Worker cases"))
    _require(len(raw_cases) == SAMPLE_CAP, 133, "Worker case count drifted")
    cases: list[dict[str, Any]] = []
    for probe, raw_case in zip(probes, raw_cases, strict=True):
        case = _mapping(raw_case, "Worker case")
        _require(
            case.get("probe_id") == probe["probe_id"],
            134,
            "Worker probe id drifted",
        )
        _require(
            case.get("query_digest") == probe["query_digest"],
            135,
            "Worker digest drifted",
        )
        _require(
            case.get("target_section_id") == probe["target_section_id"],
            136,
            "Worker target drifted",
        )
        ranked = list(
            _sequence(case.get("ranked_section_ids"), "Worker rankings")
        )
        _require(
            len(ranked) <= TOP_K
            and all(isinstance(item, str) and item for item in ranked),
            137,
            "Worker ranking invalid",
        )
        _require(len(ranked) == len(set(ranked)), 138, "duplicate ranked section")
        cases.append(
            {
                "probe_id": probe["probe_id"],
                "query_digest": probe["query_digest"],
                "query_class": probe["query_class"],
                "target_section_id": probe["target_section_id"],
                "ranked_section_ids": ranked,
                "target_rank": (
                    ranked.index(probe["target_section_id"]) + 1
                    if probe["target_section_id"] in ranked
                    else None
                ),
                "target_in_top_5": probe["target_section_id"] in ranked[:5],
                "reciprocal_rank_at_10": _reciprocal_rank(
                    probe["target_section_id"], ranked
                ),
                "ndcg_at_10": _ndcg(probe["target_section_id"], ranked),
                "raw_query_persisted": False,
                "output_influenced": False,
            }
        )

    before = _validate_snapshot(
        _mapping(payload.get("collection_before"), "Worker collection before")
    )
    after = _validate_snapshot(
        _mapping(payload.get("collection_after"), "Worker collection after")
    )
    _require(before == after, 139, "collection changed during observation")

    timings = _mapping(payload.get("timings"), "Worker timings")
    provider_ms = timings.get("provider_ms")
    qdrant_ms = timings.get("qdrant_ms")
    shadow_ms = timings.get("shadow_ms")
    for value in (provider_ms, qdrant_ms, shadow_ms):
        _require(
            isinstance(value, int) and value >= 0,
            140,
            "Worker timing invalid",
        )
    _require(
        shadow_ms >= provider_ms and shadow_ms >= qdrant_ms,
        141,
        "Worker timing drifted",
    )

    acceptance = _mapping(payload.get("acceptance"), "Worker acceptance")
    _require(acceptance.get("error_rate") == 0.0, 142, "error rate drifted")
    _require(
        acceptance.get("acl_violation_rate") == 0.0,
        143,
        "ACL violation rate drifted",
    )
    _require(
        acceptance.get("output_influence_rate") == 0.0,
        144,
        "output influence rate drifted",
    )
    authority = _mapping(payload.get("authority"), "Worker authority")
    _require(
        authority.get("production_retrieval") == "lexical",
        145,
        "production retrieval drifted",
    )
    _require(
        authority.get("protected_mutations_dispatched") is False,
        146,
        "protected mutation detected",
    )
    external = _mapping(payload.get("external_calls"), "Worker external calls")
    _require(
        external.get("workers_ai_binding") == 1,
        147,
        "Workers AI call count drifted",
    )
    _require(
        external.get("qdrant_query_batch") == 1,
        148,
        "Qdrant batch count drifted",
    )
    _require(external.get("qdrant_write") == 0, 149, "Qdrant write detected")

    return {
        "nonce": nonce,
        "cases": cases,
        "collection_before": before,
        "collection_after": after,
        "provider_ms": provider_ms,
        "qdrant_ms": qdrant_ms,
        "shadow_ms": shadow_ms,
        "operator_round_trip_ms": worker_result["operator_round_trip_ms"],
        "cf_placement": worker_result.get("cf_placement"),
        "error_rate": acceptance["error_rate"],
        "acl_violation_rate": acceptance["acl_violation_rate"],
        "output_influence_rate": acceptance["output_influence_rate"],
    }


def build_report(
    *,
    contract: Mapping[str, Any],
    probes: Sequence[Mapping[str, Any]],
    worker: Mapping[str, Any],
    worker_origin: str,
    placement_config: Mapping[str, Any],
) -> dict[str, Any]:
    validated_contract = validate_contract(contract)
    _require(len(probes) == SAMPLE_CAP, 150, "probe count drifted")
    result = _validate_worker_result(worker, probes)
    cases = result["cases"]
    recall_at_5 = sum(case["target_in_top_5"] for case in cases) / SAMPLE_CAP
    mrr_at_10 = sum(case["reciprocal_rank_at_10"] for case in cases) / SAMPLE_CAP
    ndcg_at_10 = sum(case["ndcg_at_10"] for case in cases) / SAMPLE_CAP
    metrics = {
        "recall_at_5": recall_at_5,
        "mrr_at_10": mrr_at_10,
        "ndcg_at_10": ndcg_at_10,
        "worker_internal_shadow_ms": result["shadow_ms"],
        "error_rate": result["error_rate"],
        "acl_violation_rate": result["acl_violation_rate"],
        "output_influence_rate": result["output_influence_rate"],
    }
    gates = {
        "recall_at_5": recall_at_5 >= MIN_RECALL_AT_5,
        "mrr_at_10": mrr_at_10 >= MIN_MRR_AT_10,
        "ndcg_at_10": ndcg_at_10 >= MIN_NDCG_AT_10,
        "worker_internal_shadow": result["shadow_ms"] <= MAX_SHADOW_P95_MS,
        "error_rate": result["error_rate"] == 0.0,
        "acl_violation_rate": result["acl_violation_rate"] == 0.0,
        "output_influence_rate": result["output_influence_rate"] == 0.0,
    }
    passed = all(gates.values())
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": (
            "pass_bounded_live_reobservation"
            if passed
            else "rejected_bounded_live_reobservation"
        ),
        "milestone": "M23.7-R3",
        "workstream": "bounded_live_reobservation",
        "contract_sha256": validated_contract["contract_sha256"],
        "placement_config": dict(placement_config),
        "path": {
            "id": "workers-ai-binding-qdrant-placement-top-10",
            "origin_label": _bounded_label(worker_origin, "Worker origin"),
            "data_plane_requests": 2,
            "provider_ms": result["provider_ms"],
            "qdrant_ms": result["qdrant_ms"],
            "shadow_ms": result["shadow_ms"],
            "operator_round_trip_ms": result["operator_round_trip_ms"],
            "cf_placement": result.get("cf_placement"),
            "collection_before": result["collection_before"],
            "collection_after": result["collection_after"],
        },
        "cases": cases,
        "metrics": metrics,
        "thresholds": {
            "min_recall_at_5": MIN_RECALL_AT_5,
            "min_mrr_at_10": MIN_MRR_AT_10,
            "min_ndcg_at_10": MIN_NDCG_AT_10,
            "max_worker_internal_shadow_ms": MAX_SHADOW_P95_MS,
            "max_error_rate": 0.0,
            "max_acl_violation_rate": 0.0,
            "max_output_influence_rate": 0.0,
        },
        "gates": gates,
        "privacy": {
            "compiled_raw_queries_persisted": False,
            "raw_answers_persisted": False,
            "credentials_persisted": False,
            "service_urls_persisted": False,
            "service_hostnames_persisted": False,
            "arbitrary_exception_text_persisted": False,
        },
        "exit": {
            "r3_complete": passed,
            "retrieval_quality_blocker_cleared": passed,
            "all_repair_blockers_cleared": passed,
            "diagnostic_worker_delete_after_reconciliation": True,
            "new_explicit_promotion_decision_required": True,
            "promotion_eligibility_granted": False,
        },
        "remaining_blockers": [] if passed else ["blocked_pending_retrieval_quality"],
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "semantic_output_served": False,
            "production_authority": False,
            "protected_mutations_dispatched": False,
        },
        "external_calls": {
            "workers_ai_binding": 1,
            "qdrant_collection_reads": 2,
            "qdrant_query_batch": 1,
            "qdrant_write": 0,
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


def validate_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(_mapping(payload, "report"))
    digest = root.pop("report_sha256", None)
    _require(digest == canonical_sha256(root), 151, "report digest mismatch")
    _require(
        root.get("contract_sha256") == canonical_contract()["contract_sha256"],
        152,
        "contract identity drifted",
    )
    status = root.get("status")
    _require(
        status
        in {
            "pass_bounded_live_reobservation",
            "rejected_bounded_live_reobservation",
        },
        153,
        "unsupported report status",
    )
    metrics = _mapping(root.get("metrics"), "metrics")
    gates = _mapping(root.get("gates"), "gates")
    expected_gates = {
        "recall_at_5": metrics.get("recall_at_5", 0.0) >= MIN_RECALL_AT_5,
        "mrr_at_10": metrics.get("mrr_at_10", 0.0) >= MIN_MRR_AT_10,
        "ndcg_at_10": metrics.get("ndcg_at_10", 0.0) >= MIN_NDCG_AT_10,
        "worker_internal_shadow": (
            metrics.get("worker_internal_shadow_ms", MAX_SHADOW_P95_MS + 1)
            <= MAX_SHADOW_P95_MS
        ),
        "error_rate": metrics.get("error_rate") == 0.0,
        "acl_violation_rate": metrics.get("acl_violation_rate") == 0.0,
        "output_influence_rate": metrics.get("output_influence_rate") == 0.0,
    }
    _require(dict(gates) == expected_gates, 154, "gate evaluation drifted")
    passed = all(expected_gates.values())
    _require(
        (status == "pass_bounded_live_reobservation") is passed,
        155,
        "status drifted",
    )
    cases = list(_sequence(root.get("cases"), "cases"))
    _require(len(cases) == SAMPLE_CAP, 156, "case count drifted")
    _require(
        all(case.get("raw_query_persisted") is False for case in cases),
        157,
        "raw query persisted",
    )
    exit_state = _mapping(root.get("exit"), "exit")
    for key in (
        "r3_complete",
        "retrieval_quality_blocker_cleared",
        "all_repair_blockers_cleared",
    ):
        _require(exit_state.get(key) is passed, 158, f"exit drifted: {key}")
    _require(
        exit_state.get("promotion_eligibility_granted") is False,
        159,
        "promotion claimed",
    )
    remaining = list(
        _sequence(root.get("remaining_blockers"), "remaining blockers")
    )
    _require(
        remaining == ([] if passed else ["blocked_pending_retrieval_quality"]),
        160,
        "remaining blockers drifted",
    )
    authority = _mapping(root.get("authority"), "authority")
    _require(
        authority.get("production_retrieval") == "lexical",
        161,
        "production authority drifted",
    )
    _require(
        authority.get("protected_mutations_dispatched") is False,
        162,
        "protected mutation detected",
    )
    privacy = _mapping(root.get("privacy"), "privacy")
    _require(
        all(value is False for value in privacy.values()),
        163,
        "privacy boundary drifted",
    )
    external = _mapping(root.get("external_calls"), "external calls")
    _require(external.get("qdrant_write") == 0, 164, "Qdrant write detected")
    return {**root, "report_sha256": digest}


def run_bounded_live_reobservation(
    worker_invoker: R3WorkerInvoker,
    *,
    samples: Sequence[Mapping[str, Any]],
    worker_origin: str,
    placement_config: Mapping[str, Any],
    nonce: str | None = None,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> dict[str, Any]:
    contract = validate_contract(canonical_contract())
    raw_samples = list(samples)
    _require(len(raw_samples) == SAMPLE_CAP, 165, "exactly eight samples required")
    probes = compile_probe_plan(r1_manifest(), raw_samples)
    _require(len(probes) == SAMPLE_CAP, 166, "R1 probe compilation drifted")
    safe_nonce = nonce or secrets.token_hex(16)
    _require(
        bool(re.fullmatch(r"[a-f0-9]{32}", safe_nonce)),
        167,
        "nonce is invalid",
    )
    raw_worker = worker_invoker.invoke(
        probes,
        nonce=safe_nonce,
        clock_ns=clock_ns,
    )
    report = build_report(
        contract=contract,
        probes=probes,
        worker=raw_worker,
        worker_origin=worker_origin,
        placement_config=placement_config,
    )
    return validate_report(report)


class FixtureWorkerInvoker:
    def __init__(
        self,
        *,
        ranks: Sequence[int | None] = (1, 1, 2, 1, 2, 1, 1, 2),
        shadow_ms: int = 780,
    ) -> None:
        self.ranks = tuple(ranks)
        self.shadow_ms = shadow_ms

    def invoke(
        self,
        probes: Sequence[Mapping[str, Any]],
        *,
        nonce: str,
        clock_ns: Callable[[], int],
    ) -> dict[str, Any]:
        del clock_ns
        cases = []
        for index, (probe, rank) in enumerate(
            zip(probes, self.ranks, strict=True),
            start=1,
        ):
            distractors = [
                f"fixture/distractor-{index:02d}-{slot:02d}"
                for slot in range(1, TOP_K + 1)
            ]
            if rank is not None:
                distractors[rank - 1] = probe["target_section_id"]
            cases.append(
                {
                    "probe_id": probe["probe_id"],
                    "query_digest": probe["query_digest"],
                    "target_section_id": probe["target_section_id"],
                    "ranked_section_ids": distractors,
                    "raw_query_persisted": False,
                    "output_influenced": False,
                }
            )
        snapshot = {
            "status": "green",
            "points_count": EXPECTED_POINTS,
            "indexed_vectors_count": 107,
            "vector_name": VECTOR_NAME,
            "vector_dimension": VECTOR_DIMENSION,
            "distance": "Cosine",
            "sparse_vectors": None,
            "read_only": True,
        }
        return {
            "payload": {
                "schema_version": WORKER_RESPONSE_SCHEMA,
                "status": "ok",
                "nonce": nonce,
                "query_digests": [probe["query_digest"] for probe in probes],
                "timings": {
                    "provider_ms": 230,
                    "qdrant_ms": 550,
                    "shadow_ms": self.shadow_ms,
                },
                "collection_before": snapshot,
                "collection_after": snapshot,
                "cases": cases,
                "acceptance": {
                    "error_rate": 0.0,
                    "acl_violation_rate": 0.0,
                    "output_influence_rate": 0.0,
                },
                "privacy": {
                    "compiled_raw_queries_persisted": False,
                    "raw_answers_persisted": False,
                    "credentials_persisted": False,
                    "service_urls_persisted": False,
                    "arbitrary_exception_text_persisted": False,
                },
                "authority": {
                    "production_retrieval": "lexical",
                    "candidate_mode_enabled": False,
                    "semantic_output_served": False,
                    "production_authority": False,
                    "protected_mutations_dispatched": False,
                },
                "external_calls": {
                    "workers_ai_binding": 1,
                    "qdrant_collection_reads": 2,
                    "qdrant_query_batch": 1,
                    "qdrant_write": 0,
                },
            },
            "operator_round_trip_ms": 1500,
            "cf_placement": "local-NRT",
        }


def canonical_fixture_report() -> dict[str, Any]:
    return run_bounded_live_reobservation(
        FixtureWorkerInvoker(),
        samples=canonical_fixture_samples(),
        worker_origin="fixture-placement-worker",
        placement_config={
            "config_sha256": "0" * 64,
            "placement_hostname_sha256": "1" * 64,
            "ai_binding": "AI",
            "generated_config_committed": False,
        },
        nonce="a" * 32,
    )
