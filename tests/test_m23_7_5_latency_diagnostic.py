from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

from knowledge_engine.m23_7_5_latency_diagnostic import (
    CANONICAL_MAX_SHADOW_P95_MS,
    run_latency_diagnostic,
)
from knowledge_engine.m23_7_5_live_shadow import (
    EXPECTED_POINTS,
    QDRANT_MANIFEST,
    QDRANT_RELEASE,
    SAMPLE_CAP,
    VECTOR_DIMENSION,
    VECTOR_NAME,
)


def point(index: int) -> dict:
    section_id = f"pilot/live-shadow#section-{index:03d}"
    return {
        "id": f"00000000-0000-0000-0000-{index:012d}",
        "score": 1.0 - index / 1000,
        "payload": {
            "section_id": section_id,
            "article_id": "pilot/live-shadow",
            "document_id": "pilot/live-shadow",
            "concept_id": f"concept-{index:03d}",
            "source_path": "pilot/live-shadow.md",
            "source_sha256": "a" * 64,
            "text_sha256": "b" * 64,
            "graph_node_id": f"node-{index:03d}",
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
        },
    }


class FakeClient:
    def __init__(self) -> None:
        self.points = [point(index) for index in range(1, SAMPLE_CAP + 1)]
        self.query_index = 0

    def collection_snapshot(self) -> dict:
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

    def sample_points(self, limit: int) -> list[dict]:
        return copy.deepcopy(self.points[:limit])

    def embed(self, text: str) -> list[float]:
        assert text.startswith("pilot/live-shadow#section-")
        return [1.0] + [0.0] * (VECTOR_DIMENSION - 1)

    def query(self, vector: list[float], top_k: int) -> list[dict]:
        assert len(vector) == VECTOR_DIMENSION
        item = copy.deepcopy(self.points[self.query_index])
        self.query_index += 1
        return [item][:top_k]


class Clock:
    def __init__(self, step_ns: int) -> None:
        self.value = 0
        self.step_ns = step_ns

    def __call__(self) -> int:
        self.value += self.step_ns
        return self.value


def test_cli_module_imports_actual_strict_mode_client():
    script = Path(__file__).parents[1] / "scripts" / "m23_7_5_latency_diagnostic.py"
    spec = importlib.util.spec_from_file_location("m23_7_5_latency_diagnostic_cli", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.main)


def test_fast_receipt_passes_without_changing_canonical_budget():
    report = run_latency_diagnostic(FakeClient(), clock_ns=Clock(1_000_000))
    assert report["status"] == "pass"
    assert report["acceptance"]["canonical_max_shadow_p95_ms"] == 1200
    assert report["acceptance"]["canonical_budget_changed"] is False
    assert report["acceptance"]["budget_violations"] == []


def test_slow_receipt_is_written_as_rejected_and_remains_redacted():
    report = run_latency_diagnostic(FakeClient(), clock_ns=Clock(700_000_000))
    assert report["status"] == "rejected"
    assert report["metrics"]["shadow_p95_ms"] > CANONICAL_MAX_SHADOW_P95_MS
    assert "shadow-latency" in report["acceptance"]["budget_violations"]
    assert report["raw_queries_persisted"] is False
    assert report["raw_answers_persisted"] is False
    assert report["service_urls_persisted"] is False
    assert report["protected_mutations_dispatched"] is False
    encoded = repr(report)
    assert "query_text" not in encoded
    assert "answer_text" not in encoded
    assert "https://" not in encoded
    assert len(report["latency_diagnostic_sha256"]) == 64
