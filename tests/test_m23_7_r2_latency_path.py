from __future__ import annotations

import importlib.util
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
from knowledge_engine.m23_7_r2_latency_path import (
    StrictModeSafeBatchLatencyClient,
    canonical_contract,
    canonical_sha256,
    run_latency_path_comparison,
    validate_contract,
    validate_origin_label,
    validate_report,
)
from knowledge_engine.m23_cloudflare_qdrant import CloudflareConfig, QdrantConfig

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "pilot/m23/m23-7-r2-latency-path-contract.json"
FIXTURE_REPORT_PATH = ROOT / "pilot/m23/m23-7-r2-latency-path-fixture-report.json"
CLI_PATH = ROOT / "scripts/m23_7_r2_latency_path.py"


class FixtureClient:
    def __init__(self) -> None:
        self.samples: list[dict[str, Any]] = []
        for item in canonical_fixture_samples():
            payload = {
                **dict(item["payload"]),
                "vector_name": VECTOR_NAME,
                "vector_dimension": VECTOR_DIMENSION,
                "embedding_model": "@cf/baai/bge-m3",
            }
            self.samples.append({"id": item["point_id"], "payload": payload})
        self.query_index = 0

    def collection_snapshot(self) -> dict[str, Any]:
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

    def sample_points(self, limit: int) -> list[dict[str, Any]]:
        return self.samples[:limit]

    @staticmethod
    def vector(index: int) -> list[float]:
        row = [0.0] * VECTOR_DIMENSION
        row[index % VECTOR_DIMENSION] = 1.0
        return row

    def embed(self, text: str) -> list[float]:
        assert text
        return self.vector(self.query_index)

    def query(self, vector: list[float], top_k: int) -> list[dict[str, Any]]:
        del vector
        item = self.samples[self.query_index]
        self.query_index += 1
        return [{**item, "score": 0.99}][:top_k]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.vector(index) for index, _ in enumerate(texts)]

    def query_batch(
        self, vectors: list[list[float]], top_k: int
    ) -> list[list[dict[str, Any]]]:
        del vectors
        return [[{**item, "score": 0.99}][:top_k] for item in self.samples]


class DriftClient(FixtureClient):
    def query_batch(
        self, vectors: list[list[float]], top_k: int
    ) -> list[list[dict[str, Any]]]:
        output = super().query_batch(vectors, top_k)
        output[0] = output[1]
        return output


class ShortSampleClient(FixtureClient):
    def sample_points(self, limit: int) -> list[dict[str, Any]]:
        return self.samples[: limit - 1]


class StepClock:
    def __init__(self, step_ms: int) -> None:
        self.value = 0
        self.step_ns = step_ms * 1_000_000

    def __call__(self) -> int:
        self.value += self.step_ns
        return self.value


def _fixture_report(step_ms: int = 50) -> dict[str, Any]:
    return run_latency_path_comparison(
        FixtureClient(),
        origin_label="fixture-local",
        clock_ns=StepClock(step_ms),
    )


def _redigest(payload: dict[str, Any], digest_key: str) -> dict[str, Any]:
    payload[digest_key] = canonical_sha256(
        {key: value for key, value in payload.items() if key != digest_key}
    )
    return payload


def test_canonical_contract_matches_committed_artifact() -> None:
    committed = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert committed == canonical_contract()
    assert validate_contract(committed) == committed
    assert committed["budget"] == {
        "canonical_max_shadow_p95_ms": 1200,
        "budget_changed": False,
        "budget_inflation_allowed": False,
    }


def test_fixture_report_matches_committed_artifact() -> None:
    report = _fixture_report()
    committed = json.loads(FIXTURE_REPORT_PATH.read_text(encoding="utf-8"))
    assert report == committed
    assert validate_report(report) == report
    assert report["paths"]["baseline"]["data_plane_requests"] == 16
    assert report["paths"]["candidate"]["data_plane_requests"] == 2
    assert report["comparison"]["ranked_results_equivalent"] is True


def test_fixture_report_contains_no_raw_queries_or_answers() -> None:
    report = _fixture_report()
    encoded = json.dumps(report, sort_keys=True)
    assert "What does" not in encoded
    assert "What is" not in encoded
    assert "How does" not in encoded
    assert "Which source" not in encoded
    assert report["privacy"] == {
        "compiled_raw_queries_persisted": False,
        "raw_answers_persisted": False,
        "credentials_persisted": False,
        "service_urls_persisted": False,
        "arbitrary_exception_text_persisted": False,
    }


def test_slow_batch_path_is_rejected_without_budget_inflation() -> None:
    report = _fixture_report(step_ms=500)
    assert report["status"] == "rejected_latency_path"
    assert report["paths"]["candidate"]["shadow_p95_ms"] == 1500
    assert report["acceptance"]["canonical_max_shadow_p95_ms"] == 1200
    assert report["acceptance"]["canonical_budget_changed"] is False
    assert report["acceptance"]["budget_inflation_used"] is False
    assert report["remaining_blockers"] == [
        "blocked_pending_latency",
        "blocked_pending_retrieval_quality",
    ]
    assert validate_report(report) == report


def test_contract_tampering_fails_closed() -> None:
    payload = canonical_contract()
    payload["budget"]["canonical_max_shadow_p95_ms"] = 1800
    _redigest(payload, "contract_sha256")
    with pytest.raises(IntegrityError, match="contract drifted"):
        validate_contract(payload)


def test_batch_ranking_drift_fails_closed() -> None:
    with pytest.raises(IntegrityError, match="batch ranking drifted"):
        run_latency_path_comparison(
            DriftClient(),
            origin_label="fixture-local",
            clock_ns=StepClock(50),
        )


def test_sample_count_drift_fails_closed() -> None:
    with pytest.raises(IntegrityError, match="exactly eight live samples"):
        run_latency_path_comparison(
            ShortSampleClient(),
            origin_label="fixture-local",
            clock_ns=StepClock(50),
        )


@pytest.mark.parametrize(
    "value",
    ["https://example.com", "api-token", "x", "UPPER CASE", "bad_label"],
)
def test_origin_label_rejects_urls_secrets_and_unbounded_values(value: str) -> None:
    with pytest.raises(IntegrityError):
        validate_origin_label(value)


def test_report_blocker_removal_fails_closed() -> None:
    report = _fixture_report(step_ms=500)
    report["remaining_blockers"] = ["blocked_pending_retrieval_quality"]
    _redigest(report, "report_sha256")
    with pytest.raises(IntegrityError, match="remaining blockers drifted"):
        validate_report(report)


def test_report_promotion_claim_fails_closed() -> None:
    report = _fixture_report()
    report["exit"]["promotion_eligibility_granted"] = True
    _redigest(report, "report_sha256")
    with pytest.raises(IntegrityError, match="promotion claimed"):
        validate_report(report)


def test_report_qdrant_write_claim_fails_closed() -> None:
    report = _fixture_report()
    report["external_calls"]["qdrant_write"] = 1
    _redigest(report, "report_sha256")
    with pytest.raises(IntegrityError, match="Qdrant write detected"):
        validate_report(report)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeHttpClient:
    instances: list[FakeHttpClient] = []
    payloads: list[dict[str, Any]] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.instances.append(self)

    @classmethod
    def reset(cls, payloads: list[dict[str, Any]]) -> None:
        cls.instances = []
        cls.payloads = list(payloads)

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(self.payloads.pop(0))

    def close(self) -> None:
        self.closed = True


def _live_client() -> StrictModeSafeBatchLatencyClient:
    return StrictModeSafeBatchLatencyClient(
        CloudflareConfig(account_id="account", api_token="provider-token"),
        QdrantConfig(
            base_url="https://qdrant.example",
            api_key="qdrant-key",
            collection_name="llm_wiki_m23_pilot_bge_m3_1024",
        ),
    )


def test_batch_provider_uses_one_request_for_eight_texts(monkeypatch) -> None:
    vector = [1.0] + [0.0] * (VECTOR_DIMENSION - 1)
    FakeHttpClient.reset(
        [{"success": True, "result": {"data": [vector for _ in range(8)]}}]
    )
    monkeypatch.setattr(
        "knowledge_engine.m23_7_5_qdrant_strict_mode.httpx.Client",
        FakeHttpClient,
    )
    with _live_client() as client:
        rows = client.embed_batch([f"semantic query {index}" for index in range(8)])
    provider_http, qdrant_http = FakeHttpClient.instances
    assert len(rows) == 8
    assert len(provider_http.calls) == 1
    assert len(provider_http.calls[0]["json"]["text"]) == 8
    assert qdrant_http.calls == []
    assert provider_http.closed is True
    assert qdrant_http.closed is True


def test_qdrant_batch_query_uses_one_read_only_request(monkeypatch) -> None:
    FakeHttpClient.reset(
        [{"result": [{"points": []} for _ in range(8)], "status": "ok"}]
    )
    monkeypatch.setattr(
        "knowledge_engine.m23_7_5_qdrant_strict_mode.httpx.Client",
        FakeHttpClient,
    )
    vectors = [[1.0] + [0.0] * (VECTOR_DIMENSION - 1) for _ in range(8)]
    with _live_client() as client:
        result = client.query_batch(vectors, 5)
    provider_http, qdrant_http = FakeHttpClient.instances
    assert len(result) == 8
    assert provider_http.calls == []
    assert len(qdrant_http.calls) == 1
    call = qdrant_http.calls[0]
    assert call["url"].endswith("/points/query/batch")
    assert call["headers"] == {"api-key": "qdrant-key"}
    assert len(call["json"]["searches"]) == 8
    assert all(search["using"] == "default" for search in call["json"]["searches"])
    assert all(search["limit"] == 5 for search in call["json"]["searches"])
    assert all("filter" not in search for search in call["json"]["searches"])
    assert "delete" not in call["url"]
    assert "upsert" not in call["url"]


def test_operator_cli_imports() -> None:
    spec = importlib.util.spec_from_file_location("m23_7_r2_cli", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.main)
