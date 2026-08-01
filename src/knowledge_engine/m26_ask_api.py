from __future__ import annotations

import argparse
import os
import time
from collections.abc import Mapping
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status

from .config import Settings
from .m26_pa7_arbitrary_query_runtime import (
    MAX_QUERY_CHARS,
    DenseChannel,
    ProviderClient,
    run_owner_arbitrary_query,
)
from .m26_production_promotion_closure import load_json
from .m26_retrieval_envelope import sha256_value
from .m26_verified_answer_citation_gate import canonical_sha256
from .runtime import Runtime
from .storage import create_object_store

WEB_RESPONSE_SCHEMA = "knowledge-engine-m26-pa7-ask-web-response/v1"
WEB_HEALTH_SCHEMA = "knowledge-engine-m26-pa7-ask-web-health/v1"
WEB_GRAPH_SCHEMA = "knowledge-engine-m26-pa7-owner-full-graph/v1"
DEFAULT_GATE_PATH = Path("pilot/m26/m26-pa-7-resolved-production-gate.json")
OWNER_HASH_HEADER = "x-m26-owner-subject-hash"
BACKEND_TOKEN_HEADER = "authorization"
RUNTIME_ENTRYPOINT = "knowledge_engine.m26_pa7_arbitrary_query_runtime.run_owner_arbitrary_query"
MAX_BODY_BYTES = 4096
RATE_WINDOW_SECONDS = 60
RATE_WINDOW_MAX_REQUESTS = 12
MAX_OWNER_GRAPH_NODES = 50_000
MAX_OWNER_GRAPH_EDGES = 100_000


class M26AskApiError(ValueError):
    """Sanitized error for the owner-only M26 Ask API adapter."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


_RATE_BUCKETS: dict[str, list[float]] = {}


@lru_cache(maxsize=1)
def _owner_graph_runtime() -> Runtime:
    settings = Settings.from_env()
    return Runtime(
        create_object_store(settings),
        settings.cache_dir,
        settings.channel,
        relation_aware_expansion_enabled=(
            settings.relation_aware_expansion_enabled
        ),
    )


def validate_query_request(payload: Any, *, max_chars: int = MAX_QUERY_CHARS) -> str:
    if not isinstance(payload, Mapping):
        raise M26AskApiError(
            "M26_ASK_REQUEST_NOT_JSON_OBJECT",
            "request body must be a JSON object",
        )
    question = payload.get("question")
    if not isinstance(question, str):
        raise M26AskApiError("M26_ASK_QUESTION_MISSING", "question must be a string")
    normalized = " ".join(question.strip().split())
    if not normalized:
        raise M26AskApiError("M26_ASK_QUESTION_EMPTY", "question must not be empty")
    if len(normalized) > max_chars:
        raise M26AskApiError("M26_ASK_QUESTION_TOO_LONG", "question exceeds owner-only bound")
    return normalized


def run_owner_query_for_web(
    *,
    root: Path,
    gate_path: Path,
    request_payload: Mapping[str, Any],
    owner_subject_hash: str,
    public_request: bool = False,
    provider_client: ProviderClient | None = None,
    dense_channel: DenseChannel | None = None,
    require_remote_dense: bool = False,
    max_provider_calls: int = 2,
    max_cost: Decimal = Decimal("0.10"),
) -> dict[str, Any]:
    question = validate_query_request(request_payload)
    runtime_response = run_owner_arbitrary_query(
        root=root,
        gate=load_json(gate_path),
        question=question,
        owner_subject_hash=owner_subject_hash,
        public_request=public_request,
        provider_client=provider_client,
        dense_channel=dense_channel,
        require_remote_dense=require_remote_dense,
        max_provider_calls=max_provider_calls,
        max_cost=max_cost,
    )
    return build_web_query_dto(runtime_response)


def build_web_query_dto(runtime_response: Mapping[str, Any]) -> dict[str, Any]:
    citations = _web_citations(runtime_response)
    return {
        "schema_version": WEB_RESPONSE_SCHEMA,
        "canonical_runtime": {
            "schema_version": runtime_response.get("schema_version"),
            "entrypoint": RUNTIME_ENTRYPOINT,
            "build_sha": os.environ.get("M26_QUERY_BUILD_SHA", "local_unset"),
            "runtime_response_sha256": canonical_sha256(dict(runtime_response)),
        },
        "status": str(runtime_response.get("status", "")),
        "terminal_status": str(runtime_response.get("terminal_status", "")),
        "trace_id": str(runtime_response.get("trace_id", "")),
        "question_sha256": str(runtime_response.get("question_sha256", "")),
        "answer_text": str(runtime_response.get("answer_text", "")),
        "safe_abstention": bool(runtime_response.get("safe_abstention", True)),
        "reason_codes": _string_list(runtime_response.get("reason_codes")),
        "citations": citations,
        "sources": _source_cards(citations),
        "answer_claims": _object_list(runtime_response.get("answer_claims")),
        "relationship_summary": dict(_mapping(runtime_response.get("relationship_summary"))),
        "multi_evidence_verification": dict(
            _mapping(runtime_response.get("multi_evidence_verification"))
        ),
        "selected_evidence": _object_list(runtime_response.get("selected_evidence")),
        "identities": {
            "production_release_id": runtime_response.get("production_release_id"),
            "production_manifest_sha256": runtime_response.get("production_manifest_sha256"),
            "production_pointer_digest": runtime_response.get("production_pointer_digest"),
            "resolved_gate_self_sha256": runtime_response.get("resolved_gate_self_sha256"),
        },
        "retrieval": {
            "mode_summary": dict(_mapping(runtime_response.get("retrieval_mode_summary"))),
            "backend_identity": dict(_mapping(runtime_response.get("retrieval_backend_identity"))),
            "candidate_count_by_channel": dict(
                _mapping(runtime_response.get("candidate_count_by_channel"))
            ),
            "selected_evidence_count": runtime_response.get("selected_evidence_count", 0),
            "distinct_source_count": runtime_response.get("distinct_source_count", 0),
            "distinct_source_identities": _string_list(
                runtime_response.get("distinct_source_identities")
            ),
        },
        "accounting": {
            "provider_invoked": bool(runtime_response.get("provider_invoked", False)),
            "provider_call_count": int(runtime_response.get("provider_call_count", 0)),
            "payg_equivalent_cost_usd": str(
                runtime_response.get("payg_equivalent_cost_usd", "0")
            ),
            "latency_ms": int(runtime_response.get("latency_ms", 0)),
        },
        "privacy": dict(_mapping(runtime_response.get("privacy"))),
        "mutations": dict(_mapping(runtime_response.get("mutations"))),
    }


def build_health_dto(*, root: Path, gate_path: Path) -> dict[str, Any]:
    gate = load_json(gate_path)
    identities = _mapping(gate.get("production_identities"))
    return {
        "schema_version": WEB_HEALTH_SCHEMA,
        "status": "ok",
        "canonical_runtime": {
            "entrypoint": RUNTIME_ENTRYPOINT,
            "build_sha": os.environ.get("M26_QUERY_BUILD_SHA", "local_unset"),
            "root_sha256": sha256_value(str(root.resolve())),
        },
        "route": {
            "ask_url": "https://m24-internal.danielcanfly.com/ask",
            "full_graph_url": "https://m24-internal.danielcanfly.com/full-graph.html",
            "api_query_path": "/api/m26/query",
            "api_health_path": "/api/m26/health",
            "api_graph_path": "/api/m26/graph",
            "owner_only_route": identities.get("owner_only_route"),
        },
        "resolved_gate_self_sha256": gate.get("self_sha256"),
        "privacy": {
            "raw_query_persisted": False,
            "full_provider_response_persisted": False,
            "browser_secret_delivery": False,
        },
        "mutations": {
            "canonical_writes": 0,
            "production_pointer_mutations": 0,
            "qdrant_write_operations": 0,
        },
    }


def build_owner_graph_dto(active: Any) -> dict[str, Any]:
    graph = getattr(active, "graph_v2", None)
    if not isinstance(graph, Mapping):
        raise M26AskApiError(
            "M26_OWNER_GRAPH_UNAVAILABLE",
            "current production relation graph is unavailable",
        )
    nodes = _object_list(graph.get("nodes"))
    edges = _object_list(graph.get("edges"))
    if len(nodes) > MAX_OWNER_GRAPH_NODES or len(edges) > MAX_OWNER_GRAPH_EDGES:
        raise M26AskApiError(
            "M26_OWNER_GRAPH_BOUND_EXCEEDED",
            "current production graph exceeds the owner browser bound",
        )
    return {
        "schema_version": WEB_GRAPH_SCHEMA,
        "status": "ok",
        "graph_scope": "full_current_production_relation_graph",
        "release_id": str(getattr(active, "release_id", "")),
        "manifest_sha256": str(getattr(active, "manifest_sha256", "")),
        "loaded_at": str(getattr(active, "loaded_at", "")),
        "renderer_neutral": bool(graph.get("renderer_neutral", True)),
        "counts": {"nodes": len(nodes), "edges": len(edges)},
        "nodes": nodes,
        "edges": edges,
        "available_actions": [
            "select_node",
            "search_node",
            "filter_relation",
            "one_hop",
            "two_hop",
        ],
        "authority": {
            "owner_only": True,
            "read_only": True,
            "production_pointer_mutations": 0,
            "corpus_index_content_mutations": 0,
        },
    }


def create_app(
    *,
    root: Path | None = None,
    gate_path: Path | None = None,
    require_remote_dense: bool | None = None,
) -> FastAPI:
    app = FastAPI(title="M26 PA7 Owner Ask API", version="1.0.0")
    return register_m26_ask_routes(
        app,
        root=root,
        gate_path=gate_path,
        require_remote_dense=require_remote_dense,
    )


def register_m26_ask_routes(
    app: FastAPI,
    *,
    root: Path | None = None,
    gate_path: Path | None = None,
    require_remote_dense: bool | None = None,
) -> FastAPI:
    app_root = (root or Path(os.environ.get("KNOWLEDGE_ENGINE_ROOT", "."))).resolve()
    resolved_gate_path = (
        gate_path
        or Path(os.environ.get("M26_PA7_GATE_PATH", DEFAULT_GATE_PATH.as_posix()))
    )
    if not resolved_gate_path.is_absolute():
        resolved_gate_path = app_root / resolved_gate_path
    remote_dense_required = (
        require_remote_dense
        if require_remote_dense is not None
        else os.environ.get("M26_QUERY_REQUIRE_REMOTE_DENSE", "").lower() == "true"
    )

    @app.get("/api/m26/health")
    async def health(request: Request) -> dict[str, Any]:
        _authorize_backend_request(request)
        return build_health_dto(root=app_root, gate_path=resolved_gate_path)

    @app.get("/api/m26/graph")
    async def graph(request: Request) -> dict[str, Any]:
        _authorize_backend_request(request)
        try:
            active = _owner_graph_runtime().ensure_loaded()
            return build_owner_graph_dto(active)
        except M26AskApiError as exc:
            raise _http_error(status.HTTP_503_SERVICE_UNAVAILABLE, exc.reason_code) from exc
        except Exception as exc:
            raise _http_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "M26_OWNER_GRAPH_LOAD_FAILED",
            ) from exc

    @app.post("/api/m26/query")
    async def query(request: Request) -> dict[str, Any]:
        owner_subject_hash = _authorize_backend_request(request)
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise _http_error(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "M26_ASK_BODY_TOO_LARGE",
            )
        try:
            payload = await request.json()
            question = validate_query_request(payload)
        except M26AskApiError as exc:
            raise _http_error(status.HTTP_400_BAD_REQUEST, exc.reason_code) from exc
        except Exception as exc:  # pragma: no cover - Starlette JSON variants differ.
            raise _http_error(status.HTTP_400_BAD_REQUEST, "M26_ASK_INVALID_JSON") from exc
        _rate_limit(owner_subject_hash, question)
        return run_owner_query_for_web(
            root=app_root,
            gate_path=resolved_gate_path,
            request_payload={"question": question},
            owner_subject_hash=owner_subject_hash,
            require_remote_dense=remote_dense_required,
        )

    return app


def _authorize_backend_request(request: Request) -> str:
    expected_token = os.environ.get("M26_QUERY_BACKEND_TOKEN", "")
    supplied_authorization = request.headers.get(BACKEND_TOKEN_HEADER, "")
    if expected_token:
        if supplied_authorization != f"Bearer {expected_token}":
            raise _http_error(status.HTTP_403_FORBIDDEN, "M26_BACKEND_TOKEN_DENIED")
    elif os.environ.get("M26_ALLOW_LOCAL_BACKEND_AUTH_BYPASS", "").lower() != "true":
        raise _http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "M26_BACKEND_TOKEN_UNCONFIGURED")

    owner_subject_hash = request.headers.get(OWNER_HASH_HEADER, "").strip().lower()
    expected_owner_hash = os.environ.get("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "").lower()
    if not owner_subject_hash or owner_subject_hash != expected_owner_hash:
        raise _http_error(status.HTTP_403_FORBIDDEN, "M26_OWNER_IDENTITY_DENIED")
    return owner_subject_hash


def _rate_limit(owner_subject_hash: str, question: str) -> None:
    now = time.monotonic()
    bucket_id = canonical_sha256(
        {
            "owner_subject_hash": owner_subject_hash,
            "question_sha256": canonical_sha256(question),
        }
    )
    bucket = [
        item
        for item in _RATE_BUCKETS.get(bucket_id, [])
        if now - item < RATE_WINDOW_SECONDS
    ]
    if len(bucket) >= RATE_WINDOW_MAX_REQUESTS:
        _RATE_BUCKETS[bucket_id] = bucket
        raise _http_error(status.HTTP_429_TOO_MANY_REQUESTS, "M26_ASK_RATE_LIMITED")
    bucket.append(now)
    _RATE_BUCKETS[bucket_id] = bucket


def _http_error(status_code: int, reason_code: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "schema_version": "knowledge-engine-m26-pa7-ask-web-error/v1",
            "status": "error",
            "reason_code": reason_code,
        },
    )


def _web_citations(runtime_response: Mapping[str, Any]) -> list[dict[str, Any]]:
    citations = []
    for index, citation in enumerate(_object_list(runtime_response.get("citations")), start=1):
        citations.append(
            {
                "number": index,
                "citation_id": citation.get("citation_id"),
                "claim_id": citation.get("claim_id"),
                "claim_role": citation.get("claim_role"),
                "evidence_id": citation.get("evidence_id"),
                "evidence_type": citation.get("evidence_type"),
                "locator_id": citation.get("locator_id"),
                "source_id": citation.get("source_id"),
                "source_identity": citation.get("source_identity"),
                "section_id": citation.get("section_id"),
                "concept_id": citation.get("concept_id"),
                "release_id": citation.get("release_id"),
                "source_locator": citation.get("source_locator"),
                "source_artifact_sha256": citation.get("source_artifact_sha256"),
                "support_text_sha256": citation.get("support_text_sha256"),
                "exact_quote_sha256": citation.get("exact_quote_sha256"),
                "provenance_record_sha256": citation.get("provenance_record_sha256"),
                "runtime_owned_locator": bool(citation.get("runtime_owned_locator")),
            }
        )
    return citations


def _source_cards(citations: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for citation in citations:
        source_identity = str(
            citation.get("source_identity")
            or citation.get("source_id")
            or citation.get("evidence_id")
            or ""
        )
        if not source_identity:
            continue
        card = seen.setdefault(
            source_identity,
            {
                "source_identity": source_identity,
                "source_id": citation.get("source_id"),
                "evidence_types": set(),
                "section_ids": set(),
                "concept_ids": set(),
                "citation_numbers": [],
                "source_artifact_sha256": citation.get("source_artifact_sha256"),
                "release_id": citation.get("release_id"),
            },
        )
        card["evidence_types"].add(str(citation.get("evidence_type", "")))
        if citation.get("section_id"):
            card["section_ids"].add(str(citation["section_id"]))
        if citation.get("concept_id"):
            card["concept_ids"].add(str(citation["concept_id"]))
        card["citation_numbers"].append(citation["number"])
    return [
        {
            **card,
            "evidence_types": sorted(card["evidence_types"]),
            "section_ids": sorted(card["section_ids"]),
            "concept_ids": sorted(card["concept_ids"]),
        }
        for card in seen.values()
    ]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge-m26-ask-api")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8789")))
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("KNOWLEDGE_ENGINE_ROOT", ".")),
    )
    parser.add_argument(
        "--gate",
        type=Path,
        default=Path(os.environ.get("M26_PA7_GATE_PATH", DEFAULT_GATE_PATH.as_posix())),
    )
    parser.add_argument("--require-remote-dense", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    uvicorn.run(
        create_app(
            root=args.root,
            gate_path=args.gate,
            require_remote_dense=args.require_remote_dense,
        ),
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
