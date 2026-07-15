from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from knowledge_engine.m23_candidate_semantic_runtime import (
    QUERY_SCHEMA,
    RELEASE_ID,
    RELEASE_MANIFEST_SHA256,
    canonical_json_bytes,
    shape_response,
    shape_shadow_response,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "pilot/m23/m23-6-5-candidate-runtime-contract.json"
QUERY_SCHEMA_PATH = ROOT / "schemas/m23-candidate-semantic-query-v1.schema.json"
RESPONSE_SCHEMA_PATH = ROOT / "schemas/m23-candidate-semantic-response-v1.schema.json"
SHADOW_SCHEMA_PATH = ROOT / "schemas/m23-candidate-shadow-response-v1.schema.json"
WORKER = ROOT / "packages/m23-candidate-runtime/src/index.ts"
WRANGLER = ROOT / "packages/m23-candidate-runtime/wrangler.jsonc"
PACKAGE = ROOT / "packages/m23-candidate-runtime/package.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def point(point_id: str, score: float) -> dict[str, Any]:
    return {
        "id": point_id,
        "score": score,
        "payload": {
            "section_id": f"section:{point_id}",
            "article_id": "article:one",
            "document_id": "document:one",
            "concept_id": "concept:one",
            "source_path": "proposals/m23-4/one.md",
            "source_sha256": "a" * 64,
            "text_sha256": "b" * 64,
            "audience": "internal",
            "source_membership": "evaluation-only-pending-proposal",
            "release_id": RELEASE_ID,
            "release_manifest_sha256": RELEASE_MANIFEST_SHA256,
            "graph_node_id": "concept:one",
            "embedding_provider": "cloudflare-workers-ai",
            "embedding_model": "@cf/baai/bge-m3",
            "vector_dimension": 1024,
            "vector_name": "default",
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
        },
    }


def build_report() -> dict[str, Any]:
    contract = json.loads(CONTRACT.read_text())
    wrangler = json.loads(WRANGLER.read_text())
    package = json.loads(PACKAGE.read_text())
    assert contract["runtime"]["deployment_authorized"] is False
    assert contract["runtime"]["runtime_enabled_default"] is False
    assert contract["runtime"]["shadow_enabled_default"] is False
    assert contract["runtime"]["read_only"] is True
    assert contract["shadow"]["lexical_output_authoritative"] is True
    assert contract["shadow"]["semantic_output_served_to_production"] is False
    assert all(value is False for value in contract["authority"].values())
    assert wrangler["workers_dev"] is False
    assert wrangler["preview_urls"] is False
    assert wrangler["vars"]["CANDIDATE_RUNTIME_ENABLED"] == "false"
    assert wrangler["vars"]["SHADOW_SEMANTIC_ENABLED"] == "false"
    assert package["dependencies"]["jose"] == "6.1.2"

    worker = WORKER.read_text()
    required = [
        "createRemoteJWKSet",
        "jwtVerify",
        "Cf-Access-Jwt-Assertion",
        "/points/query",
        "using: VECTOR_NAME",
        "with_payload: true",
        "with_vector: false",
        "CANDIDATE_RUNTIME_ENABLED",
        "SHADOW_SEMANTIC_ENABLED",
        "lexical_output_authoritative: true",
        "semantic_output_served_to_production: false",
    ]
    missing = [token for token in required if token not in worker]
    assert not missing, missing
    forbidden = [
        'method: "PUT"',
        'method: "DELETE"',
        "wait=true",
        "passThroughOnException",
        "Math.random(",
        "llamaindex_demo_hybrid",
        "production_authority: true",
        "canonical_knowledge: true",
    ]
    found = [token for token in forbidden if token in worker]
    assert not found, found

    request = {
        "schema_version": QUERY_SCHEMA,
        "request_id": "m23qry-acceptance",
        "query": "How should assumptions be tested?",
        "top_k": 3,
    }
    raw_points = [point("b", 0.8), point("a", 0.9), point("c", 0.7)]
    semantic = shape_response(request, raw_points)
    shadow = shape_shadow_response(
        {**request, "lexical_point_ids": ["a", "x", "b"]}, raw_points
    )
    assert [item["point_id"] for item in semantic["results"]] == ["a", "b", "c"]
    assert shadow["lexical_point_ids"] == ["a", "x", "b"]
    assert shadow["overlap_count"] == 2
    assert shadow["authority"]["lexical_output_authoritative"] is True

    return {
        "schema_version": "knowledge-engine-m23-candidate-runtime-acceptance/v1",
        "milestone": "M23.6.5",
        "status": "pass",
        "files": {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in (
                CONTRACT,
                QUERY_SCHEMA_PATH,
                RESPONSE_SCHEMA_PATH,
                SHADOW_SCHEMA_PATH,
                WORKER,
                WRANGLER,
                PACKAGE,
            )
        },
        "runtime": contract["runtime"],
        "semantic_query": contract["semantic_query"],
        "shadow": contract["shadow"],
        "sample": {
            "semantic_response_sha256": semantic["response_sha256"],
            "shadow_sha256": shadow["shadow_sha256"],
            "semantic_point_ids": [item["point_id"] for item in semantic["results"]],
            "lexical_point_ids": shadow["lexical_point_ids"],
            "overlap_count": shadow["overlap_count"],
        },
        "authority": contract["authority"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json_bytes(report) + b"\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
