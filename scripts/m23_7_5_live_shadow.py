from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from knowledge_engine.m23_7_5_live_shadow import (
    EXPECTED_POINTS,
    QDRANT_MANIFEST,
    QDRANT_RELEASE,
    SAMPLE_CAP,
    VECTOR_DIMENSION,
    VECTOR_NAME,
    ShadowFailure,
    run_bounded_observation,
)
from knowledge_engine.m23_7_5_qdrant_strict_mode import (
    StrictModeSafeHttpLiveShadowClient,
)
from knowledge_engine.m23_cloudflare_qdrant import CloudflareConfig, QdrantConfig


class DeterministicFixtureClient:
    def __init__(self) -> None:
        self.points = [self._point(index) for index in range(1, SAMPLE_CAP + 1)]
        self.query_index = 0

    @staticmethod
    def _point(index: int) -> dict:
        return {
            "id": f"00000000-0000-0000-0000-{index:012d}",
            "score": 1.0 - index / 1000,
            "payload": {
                "section_id": f"pilot/live-shadow#section-{index:03d}",
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
        return self.points[:limit]

    def embed(self, text: str) -> list[float]:
        if not text.startswith("pilot/live-shadow#section-"):
            raise ShadowFailure("response-shape-drift")
        return [1.0] + [0.0] * (VECTOR_DIMENSION - 1)

    def query(self, vector: list[float], top_k: int) -> list[dict]:
        del vector
        point = self.points[self.query_index]
        self.query_index += 1
        return [point][:top_k]


class DeterministicClock:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        self.value += 1_000_000
        return self.value


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"M23.7.5 missing required secret: {name}")
    return value


def _write(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run M23.7.5 privacy-safe bounded live shadow")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.mode == "fixture":
        report = run_bounded_observation(
            DeterministicFixtureClient(),
            clock_ns=DeterministicClock(),
        )
    else:
        cloudflare = CloudflareConfig(
            account_id=_required_env("CLOUDFLARE_ACCOUNT_ID"),
            api_token=_required_env("CLOUDFLARE_API_TOKEN"),
            timeout_seconds=5.0,
        )
        qdrant = QdrantConfig(
            base_url=_required_env("QDRANT_URL"),
            api_key=_required_env("QDRANT_API_KEY"),
            collection_name="llm_wiki_m23_pilot_bge_m3_1024",
            timeout_seconds=5.0,
        )
        report = run_bounded_observation(
            StrictModeSafeHttpLiveShadowClient(cloudflare, qdrant)
        )

    output = Path(args.output)
    _write(output, report)
    print(
        "M23.7.5_LIVE_SHADOW_PASS "
        f"mode={args.mode} samples={report['metrics']['sample_count']} "
        f"sha256={report['live_shadow_sha256']} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
