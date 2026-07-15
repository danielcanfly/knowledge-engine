from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_5_live_shadow import (
    EXPECTED_POINTS,
    VECTOR_DIMENSION,
    VECTOR_NAME,
)
from knowledge_engine.m23_7_r1_semantic_alignment import canonical_fixture_samples
from knowledge_engine.m23_7_r2_regional_binding import (
    WORKER_RESPONSE_SCHEMA,
    build_fixture_report,
    canonical_contract,
    canonical_sha256,
    run_regional_binding_comparison,
    validate_contract,
    validate_report,
    validate_wrangler_config,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "pilot/m23/m23-7-r2-regional-binding-contract.json"
FIXTURE_PATH = ROOT / "pilot/m23/m23-7-r2-regional-binding-fixture-report.json"


def _snapshot() -> dict[str, Any]:
    return {
        "status": "green",
        "points_count": EXPECTED_POINTS,
        "indexed_vectors_count": 0,
        "vector_name": VECTOR_NAME,
        "vector_dimension": VECTOR_DIMENSION,
        "distance": "Cosine",
        "sparse_vectors": None,
        "read_only": True,
    }


def _sample_payloads() -> list[dict[str, Any]]:
    samples = canonical_fixture_samples()
    for sample in samples:
        sample["payload"].update(
            {
                "vector_name": VECTOR_NAME,
                "vector_dimension": VECTOR_DIMENSION,
                "embedding_model": "@cf/baai/bge-m3",
            }
        )
    return samples


def _point(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": sample["point_id"],
        "score": 0.99,
        "payload": dict(sample["payload"]),
    }


class DeterministicClock:
    def __init__(self, step_ms: int = 100) -> None:
        self.value = 0
        self.step_ns = step_ms * 1_000_000

    def __call__(self) -> int:
        self.value += self.step_ns
        return self.value


class FakeDirectClient:
    def __init__(self) -> None:
        self.samples = _sample_payloads()

    def collection_snapshot(self) -> dict[str, Any]:
        return _snapshot()

    def sample_points(self, limit: int) -> list[dict[str, Any]]:
        return [
            {"id": sample["point_id"], "payload": dict(sample["payload"])}
            for sample in self.samples[:limit]
        ]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for index, _ in enumerate(texts):
            vector = [0.0] * VECTOR_DIMENSION
            vector[index] = 1.0
            vectors.append(vector)
        return vectors

    def query_batch(
        self,
        vectors: list[list[float]],
        top_k: int,
    ) -> list[list[dict[str, Any]]]:
        del vectors
        return [[_point(sample)][:top_k] for sample in self.samples]


class FakeWorkerInvoker:
    def __init__(self, shadow_ms: int = 900, ranking_drift: bool = False) -> None:
        self.shadow_ms = shadow_ms
        self.ranking_drift = ranking_drift

    def invoke(
        self,
        probes: list[dict[str, Any]],
        *,
        nonce: str,
        clock_ns: Any,
    ) -> dict[str, Any]:
        del clock_ns
        cases = []
        for index, probe in enumerate(probes):
            ranked = [probe["target_section_id"]]
            if self.ranking_drift and index == 0:
                ranked = ["unexpected-section"]
            cases.append(
                {
                    "probe_id": probe["probe_id"],
                    "query_digest": probe["query_digest"],
                    "target_section_id": probe["target_section_id"],
                    "ranked_section_ids": ranked,
                }
            )
        return {
            "payload": {
                "schema_version": WORKER_RESPONSE_SCHEMA,
                "status": "ok",
                "nonce": nonce,
                "query_digests": [probe["query_digest"] for probe in probes],
                "timings": {
                    "provider_ms": 300,
                    "qdrant_ms": max(0, self.shadow_ms - 300),
                    "shadow_ms": self.shadow_ms,
                },
                "collection_before": _snapshot(),
                "collection_after": _snapshot(),
                "cases": cases,
                "acceptance": {
                    "error_rate": 0.0,
                    "acl_violation_rate": 0.0,
                    "output_influence_rate": 0.0,
                },
                "authority": {
                    "production_retrieval": "lexical",
                    "protected_mutations_dispatched": False,
                },
                "external_calls": {
                    "workers_ai_binding": 1,
                    "qdrant_query_batch": 1,
                    "qdrant_write": 0,
                },
            },
            "operator_round_trip_ms": self.shadow_ms + 50,
            "cf_placement": "remote-NRT",
        }


def _placement_config() -> dict[str, Any]:
    return {
        "config_sha256": "1" * 64,
        "placement_hostname_sha256": "2" * 64,
        "ai_binding": "AI",
        "generated_config_committed": False,
    }


def test_committed_contract_is_canonical() -> None:
    committed = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert committed == canonical_contract()
    assert validate_contract(committed) == committed


def test_committed_fixture_report_is_canonical() -> None:
    committed = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert committed == build_fixture_report()
    assert validate_report(committed) == committed


def test_live_comparator_clears_only_latency_blocker() -> None:
    report = run_regional_binding_comparison(
        FakeDirectClient(),
        FakeWorkerInvoker(shadow_ms=900),
        direct_origin="fixture-direct",
        worker_origin="fixture-worker",
        placement_config=_placement_config(),
        nonce="a" * 32,
        clock_ns=DeterministicClock(),
    )
    assert report["status"] == "pass_regional_path_qualified"
    assert report["exit"]["r2_1_complete"] is True
    assert report["exit"]["latency_blocker_cleared"] is True
    assert report["exit"]["retrieval_quality_blocker_cleared"] is False
    assert report["remaining_blockers"] == ["blocked_pending_retrieval_quality"]
    assert report["authority"]["production_retrieval"] == "lexical"
    assert report["external_calls"]["qdrant_write"] == 0


def test_live_comparator_preserves_latency_blocker_above_budget() -> None:
    report = run_regional_binding_comparison(
        FakeDirectClient(),
        FakeWorkerInvoker(shadow_ms=1201),
        direct_origin="fixture-direct",
        worker_origin="fixture-worker",
        placement_config=_placement_config(),
        nonce="b" * 32,
        clock_ns=DeterministicClock(),
    )
    assert report["status"] == "rejected_regional_path"
    assert report["exit"]["r2_1_complete"] is False
    assert report["remaining_blockers"] == [
        "blocked_pending_latency",
        "blocked_pending_retrieval_quality",
    ]


def test_ranking_drift_fails_closed() -> None:
    with pytest.raises(IntegrityError, match="rankings drifted"):
        run_regional_binding_comparison(
            FakeDirectClient(),
            FakeWorkerInvoker(ranking_drift=True),
            direct_origin="fixture-direct",
            worker_origin="fixture-worker",
            placement_config=_placement_config(),
            nonce="c" * 32,
            clock_ns=DeterministicClock(),
        )


def test_report_tampering_fails_closed() -> None:
    report = build_fixture_report()
    tampered = copy.deepcopy(report)
    tampered["acceptance"]["canonical_max_shadow_p95_ms"] = 1300
    tampered["report_sha256"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "report_sha256"}
    )
    with pytest.raises(IntegrityError, match="canonical budget drifted"):
        validate_report(tampered)


def test_generated_wrangler_config_keeps_secrets_out(tmp_path: Path) -> None:
    config = {
        "$schema": "node_modules/wrangler/config-schema.json",
        "name": "knowledge-engine-m23-7-r2-binding",
        "main": "worker.mjs",
        "compatibility_date": "2026-07-15",
        "compatibility_flags": ["nodejs_compat"],
        "ai": {"binding": "AI"},
        "placement": {"hostname": "cluster.example.com"},
        "observability": {"enabled": True, "head_sampling_rate": 1},
    }
    path = tmp_path / "wrangler.local.jsonc"
    path.write_text(json.dumps(config), encoding="utf-8")
    result = validate_wrangler_config(path, "https://cluster.example.com")
    assert result["ai_binding"] == "AI"
    assert result["generated_config_committed"] is False
    assert len(result["config_sha256"]) == 64
    assert len(result["placement_hostname_sha256"]) == 64
