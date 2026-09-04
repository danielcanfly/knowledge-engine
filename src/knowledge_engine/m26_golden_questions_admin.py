from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, Request

from .m26_admin_contract import AdminAPIError, redact
from .m26_admin_control_plane import (
    actor_from,
    append_audit_event,
    build_audit_event,
    request_id_from,
    require_capability,
)

ADMIN_PREFIX = "/v1/admin"
CANONICAL_OPENAPI_VERSION = "1.1.0-gate-a-repair-a"
GOLDEN_READ_CAPABILITY = "evaluation.golden.read"
RUNS_READ_CAPABILITY = "evaluation.runs.read"
RUN_START_CAPABILITY = "evaluation.run.start"
RUN_REQUEST_SCHEMA_REASON = "GOLDEN_RUN_REQUEST_SCHEMA_REQUIRED"
_ALLOWED_FRESHNESS = frozenset(
    {"live", "near_live", "delayed", "snapshot", "stale", "unknown"}
)
_ALLOWED_DATASET_STATES = frozenset({"draft", "active", "superseded"})
_ALLOWED_RUN_STATES = frozenset({"queued", "running", "pass", "warn", "fail", "cancelled"})
_ALLOWED_CASE_STATES = frozenset({"pass", "warn", "fail", "error", "not_run"})


class GoldenEvaluationProvider(Protocol):
    def list_golden_sets(self, request: Request) -> Mapping[str, Any]: ...

    def list_evaluation_runs(self, request: Request) -> Mapping[str, Any]: ...


class UnavailableGoldenEvaluationProvider:
    def list_golden_sets(self, request: Request) -> Mapping[str, Any]:
        del request
        return {}

    def list_evaluation_runs(self, request: Request) -> Mapping[str, Any]:
        del request
        return {}


@dataclass
class StaticGoldenEvaluationProvider:
    golden: Mapping[str, Any]
    runs: Mapping[str, Any]

    def list_golden_sets(self, request: Request) -> Mapping[str, Any]:
        del request
        return self.golden

    def list_evaluation_runs(self, request: Request) -> Mapping[str, Any]:
        del request
        return self.runs


def _availability(status: str, reason_code: str | None, detail: str) -> dict[str, Any]:
    return {"status": status, "reason_code": reason_code, "detail": detail}


def _provenance(
    source: str,
    *,
    observed_at: str | None,
    resource_identity: Mapping[str, Any] | None = None,
    evidence_digest: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "resource_identity": redact(resource_identity),
        "evidence_digest": evidence_digest,
        "source_observed_at": observed_at,
    }


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _freshness(value: Any) -> str:
    return value if isinstance(value, str) and value in _ALLOWED_FRESHNESS else "unknown"


def _scoring_contract(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    version = _text(raw.get("version"))
    contract_hash = _text(raw.get("hash"))
    if version is None or contract_hash is None:
        return None
    metrics = _string_list(raw.get("metrics"))
    return {"version": version, "hash": contract_hash, "metrics": metrics}


def _normalize_case(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    case_id = _text(raw.get("case_id"))
    question = _text(raw.get("question"))
    expectation_hash = _text(raw.get("expectation_hash"))
    if case_id is None or question is None or expectation_hash is None:
        return None
    return {
        "case_id": case_id,
        "question": question,
        "expectation_hash": expectation_hash,
        "expected_source_ids": _string_list(raw.get("expected_source_ids")),
        "expected_traits": _string_list(raw.get("expected_traits")),
        "tags": _string_list(raw.get("tags")),
    }


def _normalize_set(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    dataset_id = _text(raw.get("dataset_id"))
    version = _text(raw.get("version"))
    dataset_hash = _text(raw.get("dataset_hash"))
    state = raw.get("state")
    scoring = _scoring_contract(raw.get("scoring_contract"))
    if (
        dataset_id is None
        or version is None
        or dataset_hash is None
        or state not in _ALLOWED_DATASET_STATES
        or scoring is None
    ):
        return None
    raw_cases = raw.get("cases")
    cases = []
    if isinstance(raw_cases, Sequence) and not isinstance(raw_cases, (str, bytes)):
        for item in raw_cases:
            normalized = _normalize_case(item)
            if normalized is not None:
                cases.append(normalized)
    return {
        "dataset_id": dataset_id,
        "version": version,
        "dataset_hash": dataset_hash,
        "state": state,
        "scoring_contract": scoring,
        "cases": cases,
    }


def _identity(raw: Any, required: Sequence[str]) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    value: dict[str, Any] = {}
    for key in required:
        item = _text(raw.get(key))
        if item is None:
            return None
        value[key] = item
    for key in ("provider_config_hash", "runtime_sha256", "collection", "manifest_sha256"):
        item = _text(raw.get(key))
        if item is not None:
            value[key] = item
    return value


def _normalize_case_result(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    case_id = _text(raw.get("case_id"))
    state = raw.get("state")
    if case_id is None or state not in _ALLOWED_CASE_STATES:
        return None
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), Mapping) else {}
    safe_metrics: dict[str, Any] = {}
    for key in (
        "faithfulness",
        "completeness",
        "unsupported",
        "contradiction",
        "unknown",
        "stability",
        "latency_ms",
    ):
        value = metrics.get(key)
        if isinstance(value, (int, float, bool, str)) or value is None:
            safe_metrics[key] = value
    error = raw.get("error") if isinstance(raw.get("error"), Mapping) else None
    return {
        "case_id": case_id,
        "state": state,
        "answer": _text(raw.get("answer")),
        "retrieval": redact(raw.get("retrieval")),
        "evidence": redact(raw.get("evidence")),
        "metrics": safe_metrics,
        "trace_id": _text(raw.get("trace_id")),
        "error": redact(error),
    }


def _normalize_run(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    run_id = _text(raw.get("run_id"))
    state = raw.get("state")
    mode = raw.get("mode")
    dataset = _identity(raw.get("dataset"), ("dataset_id", "version", "dataset_hash"))
    release = _identity(raw.get("release"), ("release_id", "index_identity", "config_identity"))
    scoring = _scoring_contract(raw.get("scoring_contract"))
    created_at = _text(raw.get("created_at"))
    if (
        run_id is None
        or state not in _ALLOWED_RUN_STATES
        or mode not in {"selected", "all", "retrieval_only"}
        or dataset is None
        or release is None
        or scoring is None
        or created_at is None
    ):
        return None
    raw_results = raw.get("case_results")
    results = []
    if isinstance(raw_results, Sequence) and not isinstance(raw_results, (str, bytes)):
        for item in raw_results:
            normalized = _normalize_case_result(item)
            if normalized is not None:
                results.append(normalized)
    progress = raw.get("progress") if isinstance(raw.get("progress"), Mapping) else {}
    summary = raw.get("summary") if isinstance(raw.get("summary"), Mapping) else {}
    return {
        "run_id": run_id,
        "state": state,
        "mode": mode,
        "dataset": dataset,
        "release": release,
        "scoring_contract": scoring,
        "created_at": created_at,
        "completed_at": _text(raw.get("completed_at")),
        "progress": redact(progress),
        "summary": redact(summary),
        "case_results": results,
    }


def _read_payload(
    request: Request,
    *,
    raw: Mapping[str, Any],
    collection_key: str,
    normalizer: Any,
    unavailable_reason: str,
    unavailable_detail: str,
) -> dict[str, Any]:
    observed_at = _text(raw.get("observed_at"))
    source = _text(raw.get("source"))
    freshness = _freshness(raw.get("freshness"))
    evidence_digest = _text(raw.get("evidence_digest"))
    resource_identity = raw.get("resource_identity")
    raw_items = raw.get(collection_key)
    if source is None or not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        return {
            "request_id": request_id_from(request),
            "availability": _availability("unavailable", unavailable_reason, unavailable_detail),
            "provenance": _provenance("golden_evaluation_source_unavailable", observed_at=None),
            "observed_at": None,
            "freshness": "unknown",
            "data": {
                collection_key: [],
                "run_request_contract": {
                    "status": "blocked",
                    "reason_code": RUN_REQUEST_SCHEMA_REASON,
                    "canonical_openapi_version": CANONICAL_OPENAPI_VERSION,
                },
            },
        }
    normalized = [item for item in (normalizer(value) for value in raw_items) if item is not None]
    status = "available"
    reason_code = None
    detail = "Qualified immutable evaluation metadata."
    if len(normalized) != len(raw_items) or observed_at is None or freshness == "unknown":
        status = "partial"
        reason_code = "GOLDEN_EVALUATION_PARTIAL_EVIDENCE"
        detail = "Some evaluation records or observation metadata were rejected as incomplete."
    return {
        "request_id": request_id_from(request),
        "availability": _availability(status, reason_code, detail),
        "provenance": _provenance(
            source,
            observed_at=observed_at,
            resource_identity=resource_identity if isinstance(resource_identity, Mapping) else None,
            evidence_digest=evidence_digest,
        ),
        "observed_at": observed_at,
        "freshness": freshness,
        "data": {
            collection_key: normalized,
            "run_request_contract": {
                "status": "blocked",
                "reason_code": RUN_REQUEST_SCHEMA_REASON,
                "canonical_openapi_version": CANONICAL_OPENAPI_VERSION,
            },
        },
    }


def golden_router() -> APIRouter:
    router = APIRouter(prefix=ADMIN_PREFIX, tags=["Evaluation"])

    @router.get("/evaluations/golden", operation_id="listGoldenSets")
    async def list_golden_sets(request: Request) -> dict[str, Any]:
        require_capability(request, GOLDEN_READ_CAPABILITY)
        provider = getattr(request.app.state, "admin_golden_evaluation_provider", UnavailableGoldenEvaluationProvider())
        try:
            raw = provider.list_golden_sets(request)
        except Exception:
            raw = {}
        return _read_payload(
            request,
            raw=raw if isinstance(raw, Mapping) else {},
            collection_key="sets",
            normalizer=_normalize_set,
            unavailable_reason="GOLDEN_DATASET_SOURCE_UNAVAILABLE",
            unavailable_detail="No qualified Golden dataset registry is wired.",
        )

    @router.get("/evaluations/runs", operation_id="listEvaluationRuns")
    async def list_evaluation_runs(request: Request) -> dict[str, Any]:
        require_capability(request, RUNS_READ_CAPABILITY)
        provider = getattr(request.app.state, "admin_golden_evaluation_provider", UnavailableGoldenEvaluationProvider())
        try:
            raw = provider.list_evaluation_runs(request)
        except Exception:
            raw = {}
        return _read_payload(
            request,
            raw=raw if isinstance(raw, Mapping) else {},
            collection_key="runs",
            normalizer=_normalize_run,
            unavailable_reason="GOLDEN_RUN_HISTORY_SOURCE_UNAVAILABLE",
            unavailable_detail="No qualified immutable evaluation-run history source is wired.",
        )

    @router.post("/evaluations/runs", operation_id="startEvaluationRun", status_code=202)
    async def start_evaluation_run(request: Request) -> dict[str, Any]:
        require_capability(request, RUN_START_CAPABILITY, mutation=True)
        actor = actor_from(request)
        operation_id, replayed = request.app.state.admin_idempotency.begin(
            actor_id=actor.actor_id,
            method=request.method,
            path=request.url.path,
            idempotency_key=request.headers.get("idempotency-key", ""),
            request_payload={},
        )
        append_audit_event(
            request,
            build_audit_event(
                actor=actor,
                action="evaluation.run.start.blocked",
                object_type="evaluation_run",
                object_id=None,
                request_id=request_id_from(request),
                operation_id=operation_id,
                outcome="blocked",
                reason_code=RUN_REQUEST_SCHEMA_REASON,
                metadata={
                    "canonical_openapi_version": CANONICAL_OPENAPI_VERSION,
                    "replayed": replayed,
                },
            ),
        )
        raise AdminAPIError(
            status_code=409,
            code=RUN_REQUEST_SCHEMA_REASON,
            message=(
                "The frozen canonical startEvaluationRun operation has no request schema for dataset, "
                "release, or selected/all identity. Starting a run is fail-closed until the shared "
                "contract is repaired."
            ),
            details={"canonical_openapi_version": CANONICAL_OPENAPI_VERSION},
        )

    return router


def install_golden_questions_admin(
    app: FastAPI, *, provider: GoldenEvaluationProvider | None = None
) -> FastAPI:
    if getattr(app.state, "admin_golden_questions_installed", False):
        return app
    app.state.admin_golden_evaluation_provider = provider or UnavailableGoldenEvaluationProvider()
    app.include_router(golden_router())
    app.state.admin_golden_questions_installed = True
    return app


__all__ = [
    "CANONICAL_OPENAPI_VERSION",
    "GOLDEN_READ_CAPABILITY",
    "RUNS_READ_CAPABILITY",
    "RUN_START_CAPABILITY",
    "RUN_REQUEST_SCHEMA_REASON",
    "StaticGoldenEvaluationProvider",
    "UnavailableGoldenEvaluationProvider",
    "golden_router",
    "install_golden_questions_admin",
]
