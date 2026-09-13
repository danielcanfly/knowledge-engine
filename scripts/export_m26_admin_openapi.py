from __future__ import annotations

import argparse
import copy
import hashlib
from pathlib import Path

import yaml

from knowledge_engine.m26_admin_settings import CANONICAL_ADMIN_OPENAPI_SHA256
from knowledge_engine.m26_console_api import app

PREDECESSOR_PATH = Path("schemas/m26-admin-openapi-v1.2.0-l3b-qa-inbox-sq.yaml")
PREDECESSOR_SHA256 = "75430530c91b704c4e1d8451bb2f1f528f5811210af8c72ce417babf6b118444"
CANONICAL_VERSION = "1.3.0-l2-final-convergence"


def _errors(*, conflict: bool = False) -> dict[str, dict[str, str]]:
    statuses = ["400", "401", "403", "422", "503"]
    if conflict:
        statuses.insert(3, "409")
    return {status: {"$ref": "#/components/responses/AdminError"} for status in statuses}


def _success(description: str, schema: str) -> dict[str, object]:
    return {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": schema}}},
        "headers": {"X-Request-Id": {"$ref": "#/components/headers/RequestId"}},
    }


def _assert_live_operation(path: str, method: str, operation_id: str) -> None:
    operation = app.openapi()["paths"][path][method]
    if operation["operationId"] != operation_id:
        raise RuntimeError(f"live operation drifted for {method.upper()} {path}")


def merged_openapi_document(predecessor_path: Path = PREDECESSOR_PATH) -> dict[str, object]:
    predecessor_bytes = predecessor_path.read_bytes()
    if hashlib.sha256(predecessor_bytes).hexdigest() != PREDECESSOR_SHA256:
        raise RuntimeError("frozen v1.2 Admin OpenAPI predecessor digest drifted")
    schema = yaml.safe_load(predecessor_bytes)
    merged = copy.deepcopy(schema)
    merged["info"]["version"] = CANONICAL_VERSION
    merged["info"]["description"] += (
        " L2 Final Convergence adds the accepted L3A index-health, one-click sync, and "
        "retry operations without changing predecessor L3B or public contract surfaces."
    )

    live = app.openapi()
    sync_schema = copy.deepcopy(live["components"]["schemas"]["SyncBlogRequest"])
    merged["components"]["schemas"]["SyncBlogRequest"] = sync_schema

    _assert_live_operation("/v1/admin/index/health", "get", "getIndexHealth")
    merged["paths"]["/v1/admin/index/health"] = {
        "get": {
            "tags": ["Health"],
            "operationId": "getIndexHealth",
            "summary": "Truthful active-index health and finalization evidence",
            "responses": {
                "200": _success("Active index health observation", "#/components/schemas/Envelope"),
                **_errors(),
            },
            "x-m26-capability-id": "index.health.read",
            "x-m26-public-contract-separate": True,
            "x-m26-state-changing": False,
            "parameters": [{"$ref": "#/components/parameters/ClientRequestId"}],
        }
    }

    _assert_live_operation("/v1/admin/ingestion/sync", "post", "syncBlog")
    merged["paths"]["/v1/admin/ingestion/sync"] = {
        "post": {
            "tags": ["Ingestion"],
            "operationId": "syncBlog",
            "summary": "Start one-click blog synchronization against an exact plan",
            "parameters": [
                {"$ref": "#/components/parameters/IdempotencyKey"},
                {"$ref": "#/components/parameters/ClientRequestId"},
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/SyncBlogRequest"}}
                },
            },
            "responses": {
                "202": _success(
                    "Sync operation accepted", "#/components/schemas/OperationAccepted"
                ),
                **_errors(conflict=True),
            },
            "x-m26-capability-id": "ingestion.job.confirm",
            "x-m26-public-contract-separate": True,
            "x-m26-state-changing": True,
        }
    }

    retry_path = "/v1/admin/ingestion/jobs/{job_id}/retry"
    _assert_live_operation(retry_path, "post", "retryIngestionJob")
    merged["paths"][retry_path] = {
        "post": {
            "tags": ["Jobs"],
            "operationId": "retryIngestionJob",
            "summary": "Retry a failed durable ingestion job",
            "parameters": [
                {"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}},
                {"$ref": "#/components/parameters/IdempotencyKey"},
                {"$ref": "#/components/parameters/ClientRequestId"},
            ],
            "responses": {
                "202": _success(
                    "Retry operation accepted", "#/components/schemas/OperationAccepted"
                ),
                **_errors(),
            },
            "x-m26-capability-id": "ingestion.job.confirm",
            "x-m26-public-contract-separate": True,
            "x-m26-state-changing": True,
        }
    }
    return merged


def canonical_openapi_bytes() -> bytes:
    rendered = yaml.safe_dump(
        merged_openapi_document(), sort_keys=False, allow_unicode=True, width=100
    )
    return rendered.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the canonical combined Admin OpenAPI")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    payload = canonical_openapi_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != CANONICAL_ADMIN_OPENAPI_SHA256:
        raise SystemExit(
            f"generated OpenAPI digest does not match CANONICAL_ADMIN_OPENAPI_SHA256: {digest}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(f"{digest}  {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
