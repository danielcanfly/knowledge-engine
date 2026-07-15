from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from . import m23_7_5_live_shadow as live_shadow
from .errors import IntegrityError
from .m23_7_5_qdrant_strict_mode import StrictModeSafeHttpLiveShadowClient
from .m23_7_r1_semantic_alignment import canonical_manifest as r1_manifest
from .m23_7_r1_semantic_alignment import compile_probe_plan
from .m23_cloudflare_qdrant import SectionInput, embed_sections

SCHEMA_VERSION = "knowledge-engine-m23-7-r2-latency-path/v1"
REPORT_SCHEMA_VERSION = "knowledge-engine-m23-7-r2-latency-path-report/v1"
ENTRY_ENGINE_SHA = "3a178469e6da3c8be47c4ed0b779609933f42fd5"
IMPLEMENTATION_ISSUE = 463
REPAIR_HANDOFF_SHA256 = (
    "7fb6fadf91f1a09110bf1d0e653652f52a298ebc0119aee3743180314e16f0b9"
)
R1_MANIFEST_SHA256 = (
    "ebff335d572461f4438ed06c4cc35288b0d0def8bbfc2b51e80bb262db12c576"
)
R1_REPORT_SHA256 = (
    "7ee8ddf6bf955cf0c1a10dd5442aa60d0b4b791bc2f3f4deba386213adf815e1"
)
SOURCE_PR_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
PREVIOUS_RECEIPT_SHA256 = (
    "493515fce1bdeb1c7155ea69c198f658c0cf05f83314a905bf2d945152dc4b3e"
)
SAMPLE_CAP = 8
TOP_K = 5
MAX_SHADOW_P95_MS = 1200
SEQUENTIAL_DATA_PLANE_CALLS = 16
BATCH_DATA_PLANE_CALLS = 2

BLOCKERS = (
    "blocked_pending_latency",
    "blocked_pending_retrieval_quality",
)

PROTECTED_MUTATIONS = (
    "answer_serving",
    "candidate_mode",
    "credential_rotation",
    "deployment",
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
        raise IntegrityError(f"M23.7-R2-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), 101, f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    valid = not isinstance(value, (str, bytes)) and isinstance(value, Sequence)
    _require(valid, 102, f"{label} must be a list")
    return tuple(value)


def _elapsed_ms(start_ns: int, end_ns: int) -> int:
    return max(0, math.ceil((end_ns - start_ns) / 1_000_000))


def _p95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    _require(bool(ordered), 103, "latency series is empty")
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def validate_origin_label(value: str) -> str:
    _require(isinstance(value, str), 104, "origin label must be a string")
    candidate = value.strip().lower()
    _require(
        bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{2,31}", candidate)),
        105,
        "origin label must be a bounded non-secret label",
    )
    _require(
        "http" not in candidate and "token" not in candidate,
        106,
        "origin label is unsafe",
    )
    return candidate


def canonical_contract() -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R2",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "workstream": "latency_path",
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "m23_7_8_decision": "repair",
            "m23_7_8_repair_handoff_sha256": REPAIR_HANDOFF_SHA256,
            "r1_manifest_sha256": R1_MANIFEST_SHA256,
            "r1_report_sha256": R1_REPORT_SHA256,
            "previous_live_receipt_sha256": PREVIOUS_RECEIPT_SHA256,
            "previous_provider_p95_ms": 1328,
            "previous_qdrant_p95_ms": 576,
            "previous_shadow_p95_ms": 1731,
            "source_pr_19": {
                "state": "open",
                "draft": True,
                "merged": False,
                "head_sha": SOURCE_PR_HEAD,
            },
        },
        "paths": {
            "baseline": {
                "id": "sequential-session-reuse",
                "provider_requests": SAMPLE_CAP,
                "qdrant_query_requests": SAMPLE_CAP,
                "data_plane_requests": SEQUENTIAL_DATA_PLANE_CALLS,
                "connection_reuse_required": True,
            },
            "candidate": {
                "id": "batch-session-reuse",
                "provider_requests": 1,
                "qdrant_query_requests": 1,
                "qdrant_endpoint": "/points/query/batch",
                "data_plane_requests": BATCH_DATA_PLANE_CALLS,
                "connection_reuse_required": True,
            },
            "ranked_result_equivalence_required": True,
            "same_origin_comparison_required": True,
        },
        "probe_contract": {
            "r1_manifest_sha256": R1_MANIFEST_SHA256,
            "probe_count": SAMPLE_CAP,
            "top_k": TOP_K,
            "raw_query_persisted": False,
            "raw_answer_persisted": False,
            "user_queries_allowed": False,
        },
        "budget": {
            "canonical_max_shadow_p95_ms": MAX_SHADOW_P95_MS,
            "budget_changed": False,
            "budget_inflation_allowed": False,
        },
        "exit_semantics": {
            "r2_complete_requires_live_receipt": True,
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
    _require(digest == canonical_sha256(root), 107, "contract digest mismatch")
    expected = canonical_contract()
    expected_digest = expected.pop("contract_sha256")
    _require(root == expected, 108, "contract drifted")
    _require(digest == expected_digest, 109, "contract identity drifted")
    return {**root, "contract_sha256": digest}


class LatencyPathClient(Protocol):
    def collection_snapshot(self) -> Mapping[str, Any]: ...

    def sample_points(self, limit: int) -> Sequence[Mapping[str, Any]]: ...

    def embed(self, text: str) -> Sequence[float]: ...

    def query(
        self, vector: Sequence[float], top_k: int
    ) -> Sequence[Mapping[str, Any]]: ...

    def embed_batch(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...

    def query_batch(
        self, vectors: Sequence[Sequence[float]], top_k: int
    ) -> Sequence[Sequence[Mapping[str, Any]]]: ...


class StrictModeSafeBatchLatencyClient(StrictModeSafeHttpLiveShadowClient):
    """Add two-call batch data plane to the accepted session-reuse client."""

    def embed_batch(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self._ensure_open()
        _require(len(texts) == SAMPLE_CAP, 110, "batch embedding requires eight texts")
        sections = [
            SectionInput(
                section_id=f"m23-7-r2-live-probe-{index:02d}",
                text=text,
                payload={},
            )
            for index, text in enumerate(texts, start=1)
        ]
        try:
            rows = embed_sections(
                sections,
                self.cloudflare,
                client=self._cloudflare_http,
            )
        except httpx.TimeoutException as exc:
            raise live_shadow.ShadowFailure("cloudflare-timeout") from exc
        except (httpx.HTTPError, IntegrityError) as exc:
            raise live_shadow.ShadowFailure("cloudflare-unavailable") from exc
        if len(rows) != SAMPLE_CAP:
            raise live_shadow.ShadowFailure("response-shape-drift")
        return rows

    def query_batch(
        self, vectors: Sequence[Sequence[float]], top_k: int
    ) -> Sequence[Sequence[Mapping[str, Any]]]:
        self._ensure_open()
        _require(len(vectors) == SAMPLE_CAP, 111, "batch query requires eight vectors")
        url = (
            f"{self.qdrant.base_url.rstrip('/')}/collections/"
            f"{quote(live_shadow.COLLECTION, safe='')}/points/query/batch"
        )
        searches = [
            {
                "query": list(vector),
                "using": live_shadow.VECTOR_NAME,
                "limit": top_k,
                "with_payload": True,
                "with_vector": False,
            }
            for vector in vectors
        ]
        try:
            response = self._qdrant_http.post(
                url,
                headers={"api-key": self.qdrant.api_key},
                json={"searches": searches},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise live_shadow.ShadowFailure("qdrant-timeout") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise live_shadow.ShadowFailure("qdrant-unavailable") from exc
        if not isinstance(payload, Mapping):
            raise live_shadow.ShadowFailure("response-shape-drift")
        result = payload.get("result")
        if not isinstance(result, list) or len(result) != SAMPLE_CAP:
            raise live_shadow.ShadowFailure("response-shape-drift")
        output: list[list[Mapping[str, Any]]] = []
        for item in result:
            points = item.get("points") if isinstance(item, Mapping) else None
            if not isinstance(points, list) or any(
                not isinstance(point, Mapping) for point in points
            ):
                raise live_shadow.ShadowFailure("response-shape-drift")
            output.append(points)
        return output


def _validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "status": "green",
        "points_count": live_shadow.EXPECTED_POINTS,
        "vector_name": live_shadow.VECTOR_NAME,
        "vector_dimension": live_shadow.VECTOR_DIMENSION,
        "distance": "Cosine",
        "sparse_vectors": None,
        "read_only": True,
    }
    for key, value in expected.items():
        _require(
            snapshot.get(key) == value,
            112,
            f"collection identity drifted: {key}",
        )
    indexed = snapshot.get("indexed_vectors_count")
    _require(isinstance(indexed, int) and indexed >= 0, 113, "indexed count invalid")
    return {**expected, "indexed_vectors_count": indexed}


def _ranked_ids(points: Sequence[Mapping[str, Any]]) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for raw in points:
        payload = _mapping(raw.get("payload"), "ranked payload")
        expected = {
            "audience": "public",
            "source_membership": "evaluation-only-pending-proposal",
            "release_id": live_shadow.QDRANT_RELEASE,
            "release_manifest_sha256": live_shadow.QDRANT_MANIFEST,
            "vector_name": live_shadow.VECTOR_NAME,
            "vector_dimension": live_shadow.VECTOR_DIMENSION,
            "embedding_model": "@cf/baai/bge-m3",
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
        }
        for key, value in expected.items():
            _require(
                payload.get(key) == value,
                114,
                f"ranked point drifted: {key}",
            )
        section_id = payload.get("section_id")
        score = raw.get("score")
        _require(
            isinstance(section_id, str) and bool(section_id),
            115,
            "ranked section missing",
        )
        _require(
            isinstance(score, (int, float)) and not isinstance(score, bool),
            116,
            "ranked score invalid",
        )
        number = float(score)
        _require(
            math.isfinite(number) and -1.0 <= number <= 1.0,
            117,
            "ranked score invalid",
        )
        ranked.append((number, section_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [section_id for _, section_id in ranked]


def run_latency_path_comparison(
    client: LatencyPathClient,
    *,
    origin_label: str,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> dict[str, Any]:
    contract = validate_contract(canonical_contract())
    origin = validate_origin_label(origin_label)
    before = _validate_snapshot(client.collection_snapshot())
    raw_samples = list(client.sample_points(SAMPLE_CAP))
    _require(
        len(raw_samples) == SAMPLE_CAP,
        118,
        "exactly eight live samples are required",
    )
    probes = compile_probe_plan(r1_manifest(), raw_samples)
    _require(len(probes) == SAMPLE_CAP, 119, "R1 probe compilation drifted")

    sequential_cases: list[dict[str, Any]] = []
    sequential_rankings: list[list[str]] = []
    for probe in probes:
        provider_start = clock_ns()
        vector = client.embed(probe["query_text"])
        provider_end = clock_ns()
        qdrant_start = clock_ns()
        ranked = _ranked_ids(client.query(vector, TOP_K))
        qdrant_end = clock_ns()
        sequential_rankings.append(ranked)
        sequential_cases.append(
            {
                "probe_id": probe["probe_id"],
                "query_digest": probe["query_digest"],
                "target_section_id": probe["target_section_id"],
                "ranked_section_ids": ranked,
                "target_in_top_5": probe["target_section_id"] in ranked[:TOP_K],
                "provider_latency_ms": _elapsed_ms(provider_start, provider_end),
                "qdrant_latency_ms": _elapsed_ms(qdrant_start, qdrant_end),
                "shadow_latency_ms": _elapsed_ms(provider_start, qdrant_end),
                "raw_query_persisted": False,
                "output_influenced": False,
            }
        )

    query_texts = [probe["query_text"] for probe in probes]
    batch_start = clock_ns()
    vectors = list(client.embed_batch(query_texts))
    provider_end = clock_ns()
    _require(len(vectors) == SAMPLE_CAP, 120, "batch embedding count drifted")
    qdrant_start = clock_ns()
    batch_results = list(client.query_batch(vectors, TOP_K))
    qdrant_end = clock_ns()
    _require(len(batch_results) == SAMPLE_CAP, 121, "batch result count drifted")
    batch_rankings = [_ranked_ids(points) for points in batch_results]
    _require(
        batch_rankings == sequential_rankings,
        122,
        "batch ranking drifted from baseline",
    )

    after = _validate_snapshot(client.collection_snapshot())
    _require(before == after, 123, "collection changed during read-only comparison")

    batch_provider_ms = _elapsed_ms(batch_start, provider_end)
    batch_qdrant_ms = _elapsed_ms(qdrant_start, qdrant_end)
    batch_shadow_ms = _elapsed_ms(batch_start, qdrant_end)
    sequential_shadow_p95 = _p95(
        [case["shadow_latency_ms"] for case in sequential_cases]
    )
    latency_pass = batch_shadow_ms <= MAX_SHADOW_P95_MS
    remaining_blockers = ["blocked_pending_retrieval_quality"]
    if not latency_pass:
        remaining_blockers.insert(0, "blocked_pending_latency")

    batch_cases = [
        {
            "probe_id": probe["probe_id"],
            "query_digest": probe["query_digest"],
            "target_section_id": probe["target_section_id"],
            "ranked_section_ids": ranked,
            "target_in_top_5": probe["target_section_id"] in ranked[:TOP_K],
            "raw_query_persisted": False,
            "output_influenced": False,
        }
        for probe, ranked in zip(probes, batch_rankings, strict=True)
    ]

    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": (
            "pass_latency_path_qualified"
            if latency_pass
            else "rejected_latency_path"
        ),
        "milestone": "M23.7-R2",
        "workstream": "latency_path",
        "contract_sha256": contract["contract_sha256"],
        "origin_label": origin,
        "collection_before": before,
        "collection_after": after,
        "paths": {
            "baseline": {
                "id": "sequential-session-reuse",
                "data_plane_requests": SEQUENTIAL_DATA_PLANE_CALLS,
                "provider_p95_ms": _p95(
                    [case["provider_latency_ms"] for case in sequential_cases]
                ),
                "qdrant_p95_ms": _p95(
                    [case["qdrant_latency_ms"] for case in sequential_cases]
                ),
                "shadow_p95_ms": sequential_shadow_p95,
                "cases": sequential_cases,
            },
            "candidate": {
                "id": "batch-session-reuse",
                "data_plane_requests": BATCH_DATA_PLANE_CALLS,
                "provider_batch_ms": batch_provider_ms,
                "qdrant_batch_ms": batch_qdrant_ms,
                "shadow_p95_ms": batch_shadow_ms,
                "cases": batch_cases,
            },
        },
        "comparison": {
            "ranked_results_equivalent": True,
            "same_origin": True,
            "connection_reuse_preserved": True,
            "data_plane_request_reduction": (
                SEQUENTIAL_DATA_PLANE_CALLS - BATCH_DATA_PLANE_CALLS
            ),
            "shadow_p95_improvement_ms": sequential_shadow_p95 - batch_shadow_ms,
        },
        "acceptance": {
            "canonical_max_shadow_p95_ms": MAX_SHADOW_P95_MS,
            "canonical_budget_changed": False,
            "budget_inflation_used": False,
            "batch_shadow_budget_pass": latency_pass,
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
        "exit": {
            "r2_complete": latency_pass,
            "latency_blocker_cleared": latency_pass,
            "retrieval_quality_blocker_cleared": False,
            "r3_ready": latency_pass,
            "new_promotion_decision_required": True,
            "promotion_eligibility_granted": False,
        },
        "remaining_blockers": remaining_blockers,
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "semantic_output_served": False,
            "production_authority": False,
            "protected_mutations_dispatched": False,
        },
        "external_calls": {
            "provider_read_only": SAMPLE_CAP + 1,
            "qdrant_read_only": SAMPLE_CAP + 4,
            "qdrant_write": 0,
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


def validate_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(_mapping(payload, "report"))
    digest = root.pop("report_sha256", None)
    _require(digest == canonical_sha256(root), 124, "report digest mismatch")
    _require(
        root.get("contract_sha256") == canonical_contract()["contract_sha256"],
        125,
        "contract identity drifted",
    )
    status = root.get("status")
    _require(
        status in {"pass_latency_path_qualified", "rejected_latency_path"},
        126,
        "unsupported report status",
    )
    acceptance = _mapping(root.get("acceptance"), "acceptance")
    _require(
        acceptance.get("canonical_max_shadow_p95_ms") == MAX_SHADOW_P95_MS,
        127,
        "canonical budget drifted",
    )
    _require(
        acceptance.get("canonical_budget_changed") is False,
        128,
        "budget changed",
    )
    _require(
        acceptance.get("budget_inflation_used") is False,
        129,
        "budget inflated",
    )
    comparison = _mapping(root.get("comparison"), "comparison")
    _require(
        comparison.get("ranked_results_equivalent") is True,
        130,
        "ranking equivalence missing",
    )
    _require(
        comparison.get("connection_reuse_preserved") is True,
        131,
        "connection reuse missing",
    )
    paths = _mapping(root.get("paths"), "paths")
    baseline = _mapping(paths.get("baseline"), "baseline path")
    candidate = _mapping(paths.get("candidate"), "candidate path")
    _require(
        baseline.get("data_plane_requests") == 16,
        132,
        "baseline request count drifted",
    )
    _require(
        candidate.get("data_plane_requests") == 2,
        133,
        "batch request count drifted",
    )
    latency_pass = (
        candidate.get("shadow_p95_ms", MAX_SHADOW_P95_MS + 1)
        <= MAX_SHADOW_P95_MS
    )
    _require(
        acceptance.get("batch_shadow_budget_pass") is latency_pass,
        134,
        "budget result drifted",
    )
    exit_state = _mapping(root.get("exit"), "exit")
    _require(
        exit_state.get("r2_complete") is latency_pass,
        135,
        "R2 exit drifted",
    )
    _require(
        exit_state.get("latency_blocker_cleared") is latency_pass,
        136,
        "latency blocker drifted",
    )
    _require(
        exit_state.get("retrieval_quality_blocker_cleared") is False,
        137,
        "retrieval blocker cleared",
    )
    _require(
        exit_state.get("promotion_eligibility_granted") is False,
        138,
        "promotion claimed",
    )
    remaining = list(_sequence(root.get("remaining_blockers"), "remaining blockers"))
    expected_remaining = ["blocked_pending_retrieval_quality"]
    if not latency_pass:
        expected_remaining.insert(0, "blocked_pending_latency")
    _require(remaining == expected_remaining, 139, "remaining blockers drifted")
    authority = _mapping(root.get("authority"), "authority")
    _require(
        authority.get("production_retrieval") == "lexical",
        140,
        "production retrieval drifted",
    )
    _require(
        authority.get("candidate_mode_enabled") is False,
        141,
        "candidate mode enabled",
    )
    _require(
        authority.get("protected_mutations_dispatched") is False,
        142,
        "protected mutation dispatched",
    )
    privacy = _mapping(root.get("privacy"), "privacy")
    _require(
        all(value is False for value in privacy.values()),
        143,
        "privacy boundary drifted",
    )
    external = _mapping(root.get("external_calls"), "external calls")
    _require(external.get("qdrant_write") == 0, 144, "Qdrant write detected")
    return {**root, "report_sha256": digest}
