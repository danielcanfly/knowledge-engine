from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, FastAPI, Request

from .m26_admin_contract import ADMIN_PREFIX, redact, utc_now
from .m26_admin_control_plane import request_id_from
from .m26_production_answer_bundle import load_production_answer_bundle
from .m26_translation_gateway_public_api import _public_health_payload

OVERVIEW_SECTION_IDS = (
    "environment_identity",
    "release_index",
    "public_ask",
    "index_audit",
    "qa_exceptions_24h",
    "ingestion_jobs",
    "usage_rate_limits",
    "golden_evaluation",
)

_SAFE_RUNTIME_IDENTITY_ENV = (
    "M26_DURABLE_GIT_COMMIT",
    "M26_RUNTIME_SHA256",
    "SOURCE_COMMIT",
    "GIT_COMMIT",
)


def _section(
    *,
    availability: str,
    reason_code: str | None,
    status: str,
    source: str,
    detail: str,
    observed_at: str | None = None,
    freshness: str = "unknown",
    value: Any = None,
    resource_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "availability": {
            "status": availability,
            "reason_code": reason_code,
            "detail": detail,
        },
        "provenance": {
            "source": source,
            "resource_identity": redact(resource_identity),
            "source_observed_at": observed_at,
        },
        "observed_at": observed_at,
        "freshness": freshness,
        "status": status,
        "value": redact(value),
        "detail": detail,
    }


def _unavailable_section(
    *, reason_code: str, source: str, detail: str
) -> dict[str, Any]:
    return _section(
        availability="unavailable",
        reason_code=reason_code,
        status="unavailable",
        source=source,
        detail=detail,
        observed_at=None,
        freshness="unknown",
        value=None,
    )


def _runtime_identity_section(request: Request, observed_at: str) -> dict[str, Any]:
    explicit_identity = {
        key: value
        for key in _SAFE_RUNTIME_IDENTITY_ENV
        if (value := os.environ.get(key, "").strip())
    }
    app_identity = {
        "title": request.app.title,
        "version": request.app.version,
    }
    if explicit_identity:
        return _section(
            availability="available",
            reason_code=None,
            status="unknown",
            source="admin_runtime_identity",
            detail=(
                "Backend runtime identity includes an explicit deployment/build "
                "identifier; identity alone does not prove health."
            ),
            observed_at=observed_at,
            freshness="live",
            value={"backend": app_identity, "runtime": explicit_identity},
            resource_identity=explicit_identity,
        )
    return _section(
        availability="partial",
        reason_code="OVERVIEW_BACKEND_BUILD_ID_UNAVAILABLE",
        status="unknown",
        source="admin_runtime_identity",
        detail=(
            "Backend process identity is observable, but no explicit runtime "
            "git/image identifier is configured."
        ),
        observed_at=observed_at,
        freshness="live",
        value={"backend": app_identity, "runtime": None},
        resource_identity=app_identity,
    )


def _release_section(request: Request) -> dict[str, Any]:
    loader: Callable[[], Any] = getattr(
        request.app.state,
        "admin_overview_bundle_loader",
        load_production_answer_bundle,
    )
    try:
        bundle = loader()
        release_id = bundle.release_id
        observed_at = getattr(bundle, "loaded_at", None)
        value = {
            "release_id": release_id,
            "manifest_sha256": getattr(bundle, "manifest_sha256", None),
            "production_pointer_sha256": getattr(
                bundle, "production_pointer_sha256", None
            ),
        }
        return _section(
            availability="available",
            reason_code=None,
            status="unknown",
            source="production_answer_bundle",
            detail=(
                "Accepted production answer bundle loaded through the existing "
                "read-only integrity-checked loader. Readability identifies the "
                "release but does not independently prove runtime health."
            ),
            observed_at=observed_at,
            freshness="snapshot",
            value=value,
            resource_identity={"release_id": release_id},
        )
    except Exception:
        return _unavailable_section(
            reason_code="OVERVIEW_PRODUCTION_BUNDLE_UNAVAILABLE",
            source="production_answer_bundle",
            detail=(
                "The accepted production answer bundle could not be read or "
                "integrity-validated. No release identity was inferred."
            ),
        )


def _public_ask_section(request: Request, observed_at: str) -> dict[str, Any]:
    builder: Callable[..., Mapping[str, Any]] = getattr(
        request.app.state,
        "admin_overview_public_health_builder",
        _public_health_payload,
    )
    try:
        payload = builder(base_url=str(request.base_url).rstrip("/"))
        status = (
            "healthy"
            if payload.get("ok") is True and payload.get("status") == "ok"
            else "warning"
        )
        reason_code = (
            None if status == "healthy" else "OVERVIEW_PUBLIC_ASK_HEALTH_NOT_OK"
        )
        return _section(
            availability="available",
            reason_code=reason_code,
            status=status,
            source="public_ask_in_process_health",
            detail=(
                "Canonical Public Ask health contract is healthy in-process. "
                "This observation does not claim external edge/network reachability."
                if status == "healthy"
                else "Canonical Public Ask in-process health did not report ok."
            ),
            observed_at=observed_at,
            freshness="live",
            value={
                "ok": payload.get("ok"),
                "status": payload.get("status"),
                "surface": payload.get("surface"),
            },
            resource_identity={"route": "/v1/answers/health"},
        )
    except Exception:
        return _unavailable_section(
            reason_code="OVERVIEW_PUBLIC_ASK_HEALTH_UNAVAILABLE",
            source="public_ask_in_process_health",
            detail=(
                "Public Ask health evidence could not be collected; health was not "
                "inferred."
            ),
        )


def _optional_sources() -> dict[str, dict[str, Any]]:
    return {
        "index_audit": _unavailable_section(
            reason_code="OVERVIEW_INDEX_AUDIT_SOURCE_UNAVAILABLE",
            source="index_audit_read_model",
            detail=(
                "No Gate-A-qualified current index-audit read source is wired into "
                "this backend base."
            ),
        ),
        "qa_exceptions_24h": _unavailable_section(
            reason_code="OVERVIEW_QA_EXCEPTIONS_SOURCE_UNAVAILABLE",
            source="qa_exception_read_model",
            detail=(
                "No qualified 24-hour QA exception event source is wired. No "
                "generic numeric QA score or zero count is fabricated."
            ),
        ),
        "ingestion_jobs": _unavailable_section(
            reason_code="OVERVIEW_INGESTION_JOBS_SOURCE_UNAVAILABLE",
            source="ingestion_job_read_model",
            detail=(
                "No qualified recent ingestion/job ledger is wired into this "
                "backend base."
            ),
        ),
        "usage_rate_limits": _unavailable_section(
            reason_code="OVERVIEW_USAGE_SOURCE_UNAVAILABLE",
            source="usage_read_model",
            detail=(
                "No qualified usage/rate-limit telemetry source is wired; zero "
                "usage is not inferred."
            ),
        ),
        "golden_evaluation": _unavailable_section(
            reason_code="OVERVIEW_GOLDEN_EVAL_SOURCE_UNAVAILABLE",
            source="golden_evaluation_read_model",
            detail=(
                "No qualified current Golden evaluation result source is wired "
                "into this backend base."
            ),
        ),
    }


def _aggregate_availability(
    sections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    states = [
        str(section.get("availability", {}).get("status", "unavailable"))
        for section in sections.values()
    ]
    if states and all(state == "available" for state in states):
        return {
            "status": "available",
            "reason_code": None,
            "detail": "All Overview sources are available.",
        }
    if any(state in {"available", "partial"} for state in states):
        return {
            "status": "partial",
            "reason_code": "OVERVIEW_PARTIAL_DEPENDENCIES",
            "detail": (
                "Overview is usable, but one or more dependency read models are "
                "unavailable or partial."
            ),
        }
    return {
        "status": "unavailable",
        "reason_code": "OVERVIEW_ALL_DEPENDENCIES_UNAVAILABLE",
        "detail": "No Overview dependency read model is currently available.",
    }


def _aggregate_freshness(sections: Mapping[str, Mapping[str, Any]]) -> str:
    if any(
        section.get("availability", {}).get("status") != "available"
        for section in sections.values()
    ):
        return "unknown"
    freshness = {
        str(section.get("freshness", "unknown")) for section in sections.values()
    }
    if len(freshness) == 1:
        return freshness.pop()
    if "stale" in freshness:
        return "stale"
    return "unknown"


def _latest_observed_at(sections: Mapping[str, Mapping[str, Any]]) -> str | None:
    observations = [
        value
        for section in sections.values()
        if isinstance((value := section.get("observed_at")), str) and value
    ]
    return max(observations) if observations else None


def build_overview_payload(request: Request) -> dict[str, Any]:
    observed_at = utc_now()
    sections: dict[str, dict[str, Any]] = {
        "environment_identity": _runtime_identity_section(request, observed_at),
        "release_index": _release_section(request),
        "public_ask": _public_ask_section(request, observed_at),
        **_optional_sources(),
    }
    return {
        "request_id": request_id_from(request),
        "availability": _aggregate_availability(sections),
        "provenance": {
            "source": "m26_admin_overview",
            "resource_identity": {"section_ids": list(OVERVIEW_SECTION_IDS)},
            "source_observed_at": _latest_observed_at(sections),
        },
        "observed_at": _latest_observed_at(sections),
        "freshness": _aggregate_freshness(sections),
        "data": {"sections": sections},
    }


def overview_router() -> APIRouter:
    router = APIRouter(prefix=ADMIN_PREFIX, tags=["Overview"])

    @router.get("/overview", operation_id="getOverview")
    async def overview(request: Request) -> dict[str, Any]:
        return build_overview_payload(request)

    return router


def install_admin_overview(app: FastAPI) -> FastAPI:
    if getattr(app.state, "admin_overview_installed", False):
        return app
    app.include_router(overview_router())
    app.state.admin_overview_installed = True
    return app


__all__ = [
    "OVERVIEW_SECTION_IDS",
    "build_overview_payload",
    "install_admin_overview",
    "overview_router",
]
