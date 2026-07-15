from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from knowledge_engine.m23_incremental_ingestion import (
    ExistingPoint,
    build_message,
    canonical_json_bytes,
    plan_batch,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "pilot/m23/m23-6-4-worker-queue-contract.json"
MESSAGE_SCHEMA = ROOT / "schemas/m23-incremental-ingestion-message-v1.schema.json"
RECEIPT_SCHEMA = ROOT / "schemas/m23-incremental-ingestion-receipt-v1.schema.json"
WORKER = ROOT / "packages/m23-pilot-ingestion-worker/src/index.ts"
WRANGLER = ROOT / "packages/m23-pilot-ingestion-worker/wrangler.jsonc"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(name: str, text: str, previous: str | None = None) -> dict[str, Any]:
    text_sha = hashlib.sha256(text.encode()).hexdigest()
    article = name.split("#", 1)[0]
    return {
        "section_id": name,
        "point_id": str(uuid5(NAMESPACE_URL, f"m23:{name}")),
        "expected_previous_text_sha256": previous,
        "text": text,
        "text_sha256": text_sha,
        "payload": {
            "payload_schema_version": "knowledge-engine-m23-qdrant-payload/v1",
            "section_id": name,
            "article_id": article,
            "document_id": article,
            "concept_id": f"concept:{article}",
            "source_path": f"proposals/{article}.md",
            "source_sha256": "a" * 64,
            "text_sha256": text_sha,
            "audience": "internal",
            "source_membership": "evaluation-only-pending-proposal",
            "release_id": "m23pilot-acceptance",
            "release_manifest_sha256": "b" * 64,
            "graph_node_id": f"concept:{article}",
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
    assert contract["worker"]["deployment_authorized"] is False
    assert contract["worker"]["execution_enabled_default"] is False
    assert all(value is False for value in contract["authority"].values())
    consumer = wrangler["queues"]["consumers"][0]
    assert consumer == {
        "queue": "llm-wiki-m23-pilot-embed",
        "max_batch_size": 4,
        "max_batch_timeout": 10,
        "max_retries": 2,
        "dead_letter_queue": "llm-wiki-m23-pilot-embed-dlq",
        "max_concurrency": 2,
    }
    assert wrangler["workers_dev"] is False
    assert wrangler["preview_urls"] is False
    assert wrangler["vars"]["EXECUTION_ENABLED"] == "false"

    worker_surface = WORKER.read_text() + "\n" + WRANGLER.read_text()
    required_worker_tokens = [
        "message.ack()",
        "item.raw.retry(",
        "batch.ackAll()",
        "wait=true&ordering=strong",
        "optimistic-precondition-mismatch",
        "EXECUTION_ENABLED",
        "@cf/baai/bge-m3",
    ]
    assert all(token in worker_surface for token in required_worker_tokens)
    forbidden_worker_tokens = [
        "passThroughOnException",
        "Math.random(",
        "llamaindex_demo_hybrid",
        "DELETE",
        "production_authority: true",
        "canonical_knowledge: true",
    ]
    assert not [token for token in forbidden_worker_tokens if token in worker_surface]

    old_sha = hashlib.sha256(b"old").hexdigest()
    inserted = section("insert#one", "insert")
    duplicate = section("duplicate#one", "same")
    replaced = section("replace#one", "new", old_sha)
    stale = section("stale#one", "late", "c" * 64)
    message = build_message(
        release_id="m23pilot-acceptance",
        source_commit_sha="d" * 40,
        emitted_at="2026-07-15T00:00:00Z",
        estimated_usd=0.04,
        sections=[inserted, duplicate, replaced, stale],
    )
    existing = {
        str(duplicate["point_id"]): ExistingPoint(
            point_id=str(duplicate["point_id"]),
            section_id=str(duplicate["section_id"]),
            text_sha256=str(duplicate["text_sha256"]),
        ),
        str(replaced["point_id"]): ExistingPoint(
            point_id=str(replaced["point_id"]),
            section_id=str(replaced["section_id"]),
            text_sha256=old_sha,
        ),
        str(stale["point_id"]): ExistingPoint(
            point_id=str(stale["point_id"]),
            section_id=str(stale["section_id"]),
            text_sha256=old_sha,
        ),
    }
    receipt = plan_batch([message], existing)
    assert [item["action"] for item in receipt["outcomes"]] == [
        "insert",
        "skip-duplicate",
        "replace",
        "reject-stale",
    ]
    return {
        "schema_version": "knowledge-engine-m23-incremental-ingestion-acceptance/v1",
        "milestone": "M23.6.4",
        "status": "pass",
        "files": {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in (CONTRACT, MESSAGE_SCHEMA, RECEIPT_SCHEMA, WORKER, WRANGLER)
        },
        "limits": contract["limits"],
        "queue": contract["queue"],
        "sample": {
            "message_id": message["message_id"],
            "receipt_sha256": receipt["receipt_sha256"],
            "actions": [item["action"] for item in receipt["outcomes"]],
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
