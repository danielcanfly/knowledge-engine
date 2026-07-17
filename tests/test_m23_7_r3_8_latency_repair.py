from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from knowledge_engine import m23_7_r3_8_latency_repair as subject


def _candidate() -> dict[str, Any]:
    points = [
        {
            "id": f"00000000-0000-0000-0000-{index:012d}",
            "payload": {"section_id": f"section-{index:03d}"},
        }
        for index in range(subject.EXPECTED_POINT_COUNT)
    ]
    probes = []
    for probe_index in range(subject.PROBE_COUNT):
        variants = []
        for variant_index in range(subject.VARIANTS_PER_PROBE):
            text = f"probe {probe_index} variant {variant_index}"
            variants.append(
                {
                    "variant_id": (
                        f"r1-probe-{probe_index + 1:02d}-v{variant_index + 1}"
                    ),
                    "query_text": text,
                    "query_text_sha256": hashlib.sha256(
                        text.encode("utf-8")
                    ).hexdigest(),
                }
            )
        probes.append(
            {
                "probe_id": f"r1-probe-{probe_index + 1:02d}",
                "offline_case_id": tuple(subject.EXPECTED_TARGET_RANKS)[
                    probe_index
                ],
                "query_class": "direct-fact",
                "target_section_id": f"section-{probe_index:03d}",
                "variants": variants,
            }
        )
    return {
        "candidate_artifact_sha256": (
            subject.r36.R3_5_CANDIDATE_ARTIFACT_SHA256
        ),
        "points": points,
        "probe_plan": probes,
        "lexical_documents": [],
    }


def _snapshot() -> dict[str, Any]:
    return {
        "status": "green",
        "points_count": subject.EXPECTED_POINT_COUNT,
        "indexed_vectors_count": 0,
        "vector_name": subject.VECTOR_NAME,
        "vector_size": subject.VECTOR_DIMENSION,
        "vector_distance": "Cosine",
        "sparse_vectors": None,
        "read_only": True,
    }


def _worker_payload(
    request: Mapping[str, Any],
    *,
    shadow_ms: int = 781,
) -> dict[str, Any]:
    ranked_ids = [
        f"section-{index:03d}" for index in range(subject.DENSE_LIMIT)
    ]
    return {
        "schema_version": subject.WORKER_RESPONSE_SCHEMA,
        "status": "ok",
        "nonce": request["nonce"],
        "collection_before": _snapshot(),
        "collection_after": _snapshot(),
        "timings": {
            "provider_ms": 431,
            "qdrant_ms": shadow_ms - 431,
            "shadow_ms": shadow_ms,
        },
        "variants": [
            {
                "variant_id": item["variant_id"],
                "query_sha256": item["query_sha256"],
                "ranked_section_ids": ranked_ids,
                "raw_query_persisted": False,
                "raw_answer_persisted": False,
            }
            for item in request["variants"]
        ],
        "acceptance": {
            "error_rate": 0.0,
            "acl_violation_rate": 0.0,
            "output_influence_rate": 0.0,
        },
        "privacy": {
            "raw_queries_persisted": False,
            "raw_answers_persisted": False,
            "credentials_persisted": False,
            "service_urls_persisted": False,
            "service_hostnames_persisted": False,
            "arbitrary_exception_text_persisted": False,
        },
        "authority": {
            "production_retrieval": "lexical",
            "semantic_output_served": False,
            "production_authority": False,
            "protected_mutations_dispatched": False,
            "retrieval_quality_blocker_cleared": False,
            "latency_blocker_cleared": False,
        },
        "external_calls": {
            "workers_ai_binding": 1,
            "qdrant_collection_reads": 2,
            "qdrant_query_batch": 1,
            "qdrant_vector_scroll": 0,
            "qdrant_write": 0,
            "qdrant_delete": 0,
            "qdrant_reindex": 0,
        },
    }


class FakeInvoker:
    def __init__(self, *, shadow_ms: int = 781) -> None:
        self.shadow_ms = shadow_ms

    def invoke(
        self,
        request_body: Mapping[str, Any],
        *,
        clock_ns: Any,
    ) -> tuple[Mapping[str, Any], int]:
        del clock_ns
        return _worker_payload(
            request_body,
            shadow_ms=self.shadow_ms,
        ), 921


def _evaluation() -> dict[str, Any]:
    return {
        "metrics": dict(subject.EXPECTED_METRICS),
        "target_ranks": dict(subject.EXPECTED_TARGET_RANKS),
        "maximum_top10_hub_frequency": 3,
        "cases": [],
    }


def test_contract_freezes_placed_worker_and_unchanged_budget() -> None:
    contract = subject.canonical_contract()
    assert contract["contract_sha256"] == subject.CONTRACT_SHA256
    assert contract["latency"]["maximum_worker_internal_shadow_ms"] == 1200
    assert contract["latency"]["threshold_changed"] is False
    assert contract["queries"]["workers_ai_binding_calls"] == 1
    assert contract["queries"]["qdrant_query_batch_calls"] == 1
    assert contract["queries"]["qdrant_vector_scroll_calls"] == 0
    assert contract["authority"]["qdrant_write_authorized"] is False
    assert contract["authority"]["retrieval_quality_blocker_cleared"] is False


def test_worker_request_has_24_unique_target_unaware_variants() -> None:
    request = subject.build_worker_request(
        _candidate(),
        nonce="0" * 32,
    )
    assert len(request["variants"]) == 24
    assert len({item["query_sha256"] for item in request["variants"]}) == 24
    encoded = subject.canonical_json(request)
    for forbidden in (
        "target_section_id",
        "expected_relevant_ids",
        "offline_case_id",
        "probe_id",
    ):
        assert forbidden not in encoded


def test_passing_worker_result_keeps_blockers_until_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject.r37,
        "evaluate_live_dense_rankings",
        lambda *_args, **_kwargs: _evaluation(),
    )
    report = subject.run_latency_repair(
        _candidate(),
        FakeInvoker(shadow_ms=781),
        {
            "config_sha256": "a" * 64,
            "placement_hostname_sha256": "b" * 64,
        },
        nonce="1" * 32,
    )
    assert report["status"] == "pass_placed_worker_latency_repair"
    assert all(report["gates"].values()), report["gates"]
    assert report["worker"]["shadow_ms"] == 781
    assert report["worker"]["operator_round_trip_informational"] is True
    assert report["retained_blockers"] == [
        "blocked_pending_retrieval_quality",
        "blocked_pending_latency",
    ]
    assert (
        report["exit"]["blocker_clearance_eligible_after_reconciliation"]
        is True
    )
    assert report["authority"]["retrieval_quality_blocker_cleared"] is False


def test_latency_failure_is_complete_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject.r37,
        "evaluate_live_dense_rankings",
        lambda *_args, **_kwargs: _evaluation(),
    )
    report = subject.run_latency_repair(
        _candidate(),
        FakeInvoker(shadow_ms=1301),
        {
            "config_sha256": "a" * 64,
            "placement_hostname_sha256": "b" * 64,
        },
        nonce="2" * 32,
    )
    assert report["status"] == "completed_fail_closed_latency_repair"
    assert report["gates"]["worker_internal_shadow"] is False
    assert report["gates"]["accepted_metric_parity"] is True
    assert (
        report["exit"]["blocker_clearance_eligible_after_reconciliation"]
        is False
    )


def test_http_worker_invoker_preserves_bounded_worker_error_code() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={"status": "error", "code": "qdrant-batch-unavailable"},
        )

    invoker = subject.HttpWorkerInvoker("https://worker.example.test/observe", "a" * 32)
    invoker._http.close()
    invoker._http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(subject.LatencyRepairError) as exc:
        invoker.invoke({"schema_version": "test"}, clock_ns=lambda: 1)
    assert exc.value.code == "worker_http_502_qdrant_batch_unavailable"


def test_http_worker_invoker_bounds_unsafe_worker_error_code() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"status": "error", "code": "secret shaped text"},
        )

    invoker = subject.HttpWorkerInvoker("https://worker.example.test/observe", "a" * 32)
    invoker._http.close()
    invoker._http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(subject.LatencyRepairError) as exc:
        invoker.invoke({"schema_version": "test"}, clock_ns=lambda: 1)
    assert exc.value.code == "worker_http_500"


def test_duplicate_worker_variant_is_rejected() -> None:
    candidate = _candidate()
    request = subject.build_worker_request(candidate, nonce="3" * 32)
    payload = _worker_payload(request)
    payload["variants"][1]["variant_id"] = payload["variants"][0][
        "variant_id"
    ]
    with pytest.raises(
        subject.LatencyRepairError,
        match="query identity drifted|variant duplicated",
    ):
        subject._validate_worker_response(payload, candidate, request)


def test_wrangler_config_requires_placement_and_persists_no_secret(
    tmp_path: Path,
) -> None:
    config = {
        "name": "knowledge-engine-m23-7-r3-8-latency",
        "main": "worker.mjs",
        "ai": {"binding": "AI"},
        "placement": {"hostname": "example.qdrant.io"},
    }
    path = tmp_path / "wrangler.local.jsonc"
    path.write_text(json.dumps(config), encoding="utf-8")
    validated = subject.validate_wrangler_config(
        path,
        "https://example.qdrant.io",
    )
    assert validated["generated_config_committed"] is False
    assert validated["ai_binding"] == "AI"
