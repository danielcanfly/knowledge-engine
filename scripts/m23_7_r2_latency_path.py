from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from knowledge_engine.m23_7_5_live_shadow import (
    EXPECTED_POINTS,
    QDRANT_MANIFEST,
    QDRANT_RELEASE,
    VECTOR_DIMENSION,
    VECTOR_NAME,
)
from knowledge_engine.m23_7_r1_semantic_alignment import canonical_fixture_samples
from knowledge_engine.m23_7_r2_latency_path import (
    StrictModeSafeBatchLatencyClient,
    run_latency_path_comparison,
    validate_report,
)
from knowledge_engine.m23_cloudflare_qdrant import CloudflareConfig, QdrantConfig


class DeterministicFixtureClient:
    def __init__(self) -> None:
        self.samples = [
            {"id": item["point_id"], "payload": dict(item["payload"])}
            for item in canonical_fixture_samples()
        ]
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
    def _vector(index: int) -> list[float]:
        vector = [0.0] * VECTOR_DIMENSION
        vector[index % VECTOR_DIMENSION] = 1.0
        return vector

    def embed(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text:
            raise ValueError("fixture query is empty")
        return self._vector(self.query_index)

    def query(self, vector: list[float], top_k: int) -> list[dict[str, Any]]:
        del vector
        item = self.samples[self.query_index]
        self.query_index += 1
        return [{**item, "score": 0.99}][:top_k]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(index) for index, _ in enumerate(texts)]

    def query_batch(
        self, vectors: list[list[float]], top_k: int
    ) -> list[list[dict[str, Any]]]:
        del vectors
        return [[{**item, "score": 0.99}][:top_k] for item in self.samples]


class DeterministicClock:
    def __init__(self, step_ms: int = 50) -> None:
        self.value = 0
        self.step_ns = step_ms * 1_000_000

    def __call__(self) -> int:
        self.value += self.step_ns
        return self.value


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"M23.7-R2 missing required secret: {name}")
    return value


def _write(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run M23.7 repair R2 sequential-versus-batch latency qualification"
    )
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--origin-label", default="fixture-local")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.mode == "fixture":
        report = run_latency_path_comparison(
            DeterministicFixtureClient(),
            origin_label=args.origin_label,
            clock_ns=DeterministicClock(),
        )
    else:
        cloudflare = CloudflareConfig(
            account_id=_required_env("CLOUDFLARE_ACCOUNT_ID"),
            api_token=_required_env("CLOUDFLARE_API_TOKEN"),
            timeout_seconds=10.0,
        )
        qdrant = QdrantConfig(
            base_url=_required_env("QDRANT_URL"),
            api_key=_required_env("QDRANT_API_KEY"),
            collection_name="llm_wiki_m23_pilot_bge_m3_1024",
            timeout_seconds=10.0,
        )
        with StrictModeSafeBatchLatencyClient(cloudflare, qdrant) as client:
            report = run_latency_path_comparison(
                client,
                origin_label=args.origin_label,
            )

    validate_report(report)
    output = Path(args.output)
    _write(output, report)
    baseline = report["paths"]["baseline"]
    candidate = report["paths"]["candidate"]
    print(
        "M23.7_R2_LATENCY_PATH "
        f"status={report['status']} "
        f"baseline_p95_ms={baseline['shadow_p95_ms']} "
        f"batch_p95_ms={candidate['shadow_p95_ms']} "
        f"provider_batch_ms={candidate['provider_batch_ms']} "
        f"qdrant_batch_ms={candidate['qdrant_batch_ms']} "
        f"sha256={report['report_sha256']} output={output}"
    )
    return 0 if report["status"] == "pass_latency_path_qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
