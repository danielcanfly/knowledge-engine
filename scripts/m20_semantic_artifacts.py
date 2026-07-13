from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from knowledge_engine.m20_embedding_contract import load_json
from knowledge_engine.m20_semantic_artifacts import (
    SEMANTIC_METADATA_FILENAME,
    SEMANTIC_VECTOR_FILENAME,
    build_semantic_artifacts,
    flat_cosine_rank,
    load_verified_semantic_artifacts,
    verify_semantic_artifacts,
)


def _vector_mapping(path: Path) -> dict[str, list[float]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("vectors JSON must be an object keyed by section ID")
    result: dict[str, list[float]] = {}
    for section_id, values in raw.items():
        if not isinstance(section_id, str) or not isinstance(values, list):
            raise SystemExit("vectors JSON values must be arrays keyed by section ID")
        result[section_id] = values
    return result


def _vector(path: Path) -> list[float]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit("query vector JSON must be an array")
    return raw


def _write_json(value: Any, output: Path | None) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and verify immutable M20.2 artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build immutable semantic artifacts")
    build.add_argument("--suite", type=Path, required=True)
    build.add_argument("--provider-contract", type=Path, required=True)
    build.add_argument("--vectors", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--builder-engine-sha", required=True)

    verify = subparsers.add_parser("verify", help="verify semantic artifacts")
    verify.add_argument("--suite", type=Path, required=True)
    verify.add_argument("--provider-contract", type=Path, required=True)
    verify.add_argument("--artifact-dir", type=Path, required=True)
    verify.add_argument("--expected-builder-engine-sha")
    verify.add_argument("--output", type=Path)

    rank = subparsers.add_parser("rank", help="run flat-cosine correctness ranking")
    rank.add_argument("--suite", type=Path, required=True)
    rank.add_argument("--provider-contract", type=Path, required=True)
    rank.add_argument("--artifact-dir", type=Path, required=True)
    rank.add_argument("--query-vector", type=Path, required=True)
    rank.add_argument("--audience", action="append", required=True)
    rank.add_argument("--limit", type=int, default=10)
    rank.add_argument("--output", type=Path)

    args = parser.parse_args()
    suite = load_json(args.suite)
    contract = load_json(args.provider_contract)

    if args.command == "build":
        metadata = build_semantic_artifacts(
            suite,
            contract,
            _vector_mapping(args.vectors),
            args.output_dir,
            builder_engine_sha=args.builder_engine_sha,
        )
        _write_json(metadata, None)
        return 0

    if args.command == "verify":
        metadata = verify_semantic_artifacts(
            args.artifact_dir / SEMANTIC_METADATA_FILENAME,
            args.artifact_dir / SEMANTIC_VECTOR_FILENAME,
            suite,
            contract,
            expected_builder_engine_sha=args.expected_builder_engine_sha,
        )
        _write_json(
            {
                "schema_version": "knowledge-engine-semantic-verification/v1",
                "artifact_id": metadata["artifact_id"],
                "metadata_sha256": metadata["metadata_sha256"],
                "vectors_sha256": metadata["vectors"]["sha256"],
                "row_count": metadata["vectors"]["row_count"],
                "dimension": metadata["vectors"]["dimension"],
                "verified": True,
                "read_only": True,
                "production_authority": False,
            },
            args.output,
        )
        return 0

    metadata, vector_bytes = load_verified_semantic_artifacts(
        args.artifact_dir,
        suite,
        contract,
    )
    results = flat_cosine_rank(
        metadata,
        vector_bytes,
        _vector(args.query_vector),
        allowed_audiences=set(args.audience),
        limit=args.limit,
    )
    _write_json(
        {
            "schema_version": "knowledge-engine-flat-cosine-result/v1",
            "artifact_id": metadata["artifact_id"],
            "method": "deterministic-flat-cosine",
            "results": results,
            "read_only": True,
            "production_authority": False,
        },
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
