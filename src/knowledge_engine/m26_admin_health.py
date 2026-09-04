from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, Request

from .m26_admin_contract import ADMIN_PREFIX, redact, utc_now
from .m26_admin_control_plane import request_id_from
from .m26_production_answer_bundle import load_production_answer_bundle
from .m26_translation_gateway_public_api import _public_health_payload

_ALLOWED_FRESHNESS = frozenset(
    {"live", "near_live", "delayed", "snapshot", "stale", "unknown"}
)
_ALLOWED_STATUS = frozenset(
    {
        "healthy",
        "degraded",
        "warning",
        "failed",
        "error",
        "unavailable",
        "read_only",
        "unknown",
    }
)
_SAFE_RUNTIME_IDENTITY_ENV = (
    "M26_DURABLE_GIT_COMMIT",
    "M26_RUNTIME_SHA256",
    "SOURCE_COMMIT",
    "GIT_COMMIT",
)


@dataclass(frozen=True)
class DependencyDefinition:
    key: str
    label: str


DEPENDENCIES = (
    DependencyDefinition("frontend", "Frontend commit identity"),
    DependencyDefinition("backend", "Backend durable / runtime identity"),
    DependencyDefinition("canonical_api", "Canonical API"),
    DependencyDefinition("production", "Production bundle / pointer"),
    DependencyDefinition("r2", "R2 bounded read"),
    DependencyDefinition("qdrant", "Qdrant bounded read / count"),
    DependencyDefinition("metadata", "Metadata / control plane"),
    DependencyDefinition("provider", "Cloudflare AI / MiniMax / provider"),
)


class HealthObserver(Protocol):
    def collect(self, request: Request) -> Mapping[str, Any]: ...


class UnavailableHealthObserver:
    def collect(self, request: Request) -> Mapping[str, Any]:
        del request
        return {}


@dataclass
class StaticHealthObserver:
    observations: Mapping[str, Any]

    def collect(self, request: Request) -> Mapping[str, Any]:
        del request
        return self.observations


def _availability(
    status: str, reason_code: str | None, detail: str
) -> dict[str, Any]:
    return {"status": status, "reason_code": reason_code, "detail": detail}


def _unavailable(definition: DependencyDefinition, reason_code: str) -> dict[str, Any]:
    detail = "No qualified authoritative observation is wired for this dependency."
    return {
        "key": definition.key,
        "label": definition.label,
        "status": "unavailable",
        "availability": _availability("unavailable", reason_code, detail),
        "source": "health_observation_unavailable",
        "observed_at": None,
        "freshness": "unknown",
        "latency_ms": None,
        "error_code": None,
        "detail": detail,
        "expected": None,
        "observed": None,
    }


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or not math.isfinite(float(value)):
        return None
    return value


def _iso_datetime(value: Any) -> str | None:
    candidate = _string(value)
    if candidate is None:
        return None
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return candidate


def _freshness(value: Any) -> str:
    candidate = _string(value)
    return candidate if candidate in _ALLOWED_FRESHNESS else "unknown"


def _scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int, float)):
        return value
    return None


def _normalize_observation(
    definition: DependencyDefinition, raw: Any
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return _unavailable(definition, "SYSTEM_HEALTH_OBSERVATION_UNAVAILABLE")

    source = _string(raw.get("source"))
    raw_status = _string(raw.get("status"))
    observed_at = _iso_datetime(raw.get("observed_at"))
    freshness = _freshness(raw.get("freshness"))
    error_code = _string(raw.get("error_code"))
    detail = _string(raw.get("detail")) or "No additional safe detail was returned."
    expected = _scalar(raw.get("expected"))
    observed = _scalar(raw.get("observed"))

    if source is None:
        return _unavailable(definition, "SYSTEM_HEALTH_SOURCE_UNQUALIFIED")

    status = raw_status if raw_status in _ALLOWED_STATUS else "unknown"
    reason_code: str | None = None

    if error_code == "429" or (error_code and "rate_limit" in error_code.lower()):
        status = "warning"
        reason_code = "SYSTEM_HEALTH_RATE_LIMITED"
    elif freshness == "stale" and status == "healthy":
        status = "warning"
        reason_code = "SYSTEM_HEALTH_STALE_EVIDENCE"
    elif expected is not None and observed is not None and expected != observed:
        status = "warning"
        reason_code = "SYSTEM_HEALTH_IDENTITY_MISMATCH"

    if status not in {"unknown", "unavailable"} and observed_at is None:
        status = "unknown"
        reason_code = "SYSTEM_HEALTH_OBSERVATION_TIME_REQUIRED"
    elif status == "healthy" and freshness == "unknown":
        status = "unknown"
        reason_code = "SYSTEM_HEALTH_FRESHNESS_REQUIRED"

    availability = "available"
    if status == "unavailable":
        availability = "unavailable"
    elif status == "unknown":
        availability = "partial" if observed_at is not None else "unavailable"

    if reason_code is None and availability != "available":
        reason_code = "SYSTEM_HEALTH_INCOMPLETE_EVIDENCE"

    return {
        "key": definition.key,
        "label": definition.label,
        "status": status,
        "availability": _availability(availability, reason_code, detail),
        "source": source,
        "observed_at": observed_at,
        "freshness": freshness,
        "latency_ms": _number(raw.get("latency_ms")),
        "error_code": error_code,
        "detail": redact(detail),
        "expected": redact(expected),
        "observed": redact(observed),
    }


def _backend_observation(request: Request, observed_at: str) -> dict[str, Any]:
    runtime_identity = next(
        (
            value
            for key in _SAFE_RUNTIME_IDENTITY_ENV
            if (value := os.environ.get(key, "").strip())
        ),
        None,
    )
    return {
        "status": "healthy",
        "source": "admin_runtime_in_process",
        "observed_at": observed_at,
        "freshness": "live",
        "latency_ms": 0,
        "detail": (
            "The authenticated admin request reached the backend process. "
            "This proves in-process liveness, not external edge reachability."
        ),
        "observed": runtime_identity,
        "resource_identity": {
            "title": request.app.title,
            "version": request.app.version,
        },
    }


def _canonical_api_observation(request: Request, observed_at: str) -> dict[str, Any]:
    started = perf_counter()
    try:
        payload = _public_health_payload(base_url=str(request.base_url).rstrip("/"))
        surface = payload.get("surface") if isinstance(payload, Mapping) else None
        answers_url = surface.get("canonical_answers_url") if isinstance(surface, Mapping) else None
        observed = (
            "/v1/answers"
            if isinstance(answers_url, str) and answers_url.endswith("/v1/answers")
            else None
        )
        healthy = payload.get("ok") is True and payload.get("status") == "ok"
        return {
            "status": "healthy" if healthy else "warning",
            "source": "public_ask_in_process_health",
            "observed_at": observed_at,
            "freshness": "live",
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "error_code": None if healthy else "SYSTEM_HEALTH_CANONICAL_API_NOT_OK",
            "detail": (
                "Canonical Public Ask health contract is healthy in-process; "
                "external edge/network reachability is not inferred."
                if healthy
                else "Canonical Public Ask in-process health did not report ok."
            ),
            "expected": "/v1/answers",
            "observed": observed,
        }
    except Exception:
        return {
            "status": "unavailable",
            "source": "public_ask_in_process_health",
            "observed_at": observed_at,
            "freshness": "live",
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "error_code": "SYSTEM_HEALTH_CANONICAL_API_UNAVAILABLE",
            "detail": "Canonical Public Ask health evidence could not be collected.",
        }


def _production_observation(request: Request, observed_at: str) -> dict[str, Any]:
    loader = getattr(
        request.app.state,
        "admin_health_bundle_loader",
        load_production_answer_bundle,
    )
    started = perf_counter()
    try:
        bundle = loader()
        release_id = _string(getattr(bundle, "release_id", None))
        pointer_sha = _string(getattr(bundle, "production_pointer_sha256", None))
        if release_id is None:
            raise ValueError("release identity unavailable")
        return {
            "status": "healthy",
            "source": "production_answer_bundle",
            "observed_at": observed_at,
            "freshness": "snapshot",
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "detail": (
                "The accepted production answer bundle was read through the "
                "existing integrity-checked loader; external traffic is not inferred."
            ),
            "observed": pointer_sha or release_id,
        }
    except Exception:
        return {
            "status": "unavailable",
            "source": "production_answer_bundle",
            "observed_at": observed_at,
            "freshness": "snapshot",
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "error_code": "SYSTEM_HEALTH_PRODUCTION_BUNDLE_UNAVAILABLE",
            "detail": (
                "The production answer bundle could not be read or integrity-validated; "
                "no production identity was inferred."
            ),
        }


def _builtin_observations(request: Request, observed_at: str) -> dict[str, Any]:
    return {
        "backend": _backend_observation(request, observed_at),
        "canonical_api": _canonical_api_observation(request, observed_at),
        "production": _production_observation(request, observed_at),
    }


def _observer_observations(
    request: Request, observer: HealthObserver | None
) -> Mapping[str, Any]:
    active = observer or getattr(
        request.app.state,
        "admin_health_observer",
        UnavailableHealthObserver(),
    )
    try:
        collected = active.collect(request)
    except Exception:
        return {}
    return collected if isinstance(collected, Mapping) else {}


def _aggregate_availability(rows: list[dict[str, Any]]) -> dict[str, Any]:
    states = [row["availability"]["status"] for row in rows]
    if states and all(state == "available" for state in states):
        return _availability(
            "available", None, "All required health observations are available."
        )
    if any(state in {"available", "partial"} for state in states):
        return _availability(
            "partial",
            "SYSTEM_HEALTH_PARTIAL_DEPENDENCIES",
            (
                "System health is partially observable; one or more required "
                "dependencies lack qualified evidence."
            ),
        )
    return _availability(
        "unavailable",
        "SYSTEM_HEALTH_UNAVAILABLE",
        "No required dependency has qualified health evidence.",
    )


def _aggregate_status(rows: list[dict[str, Any]]) -> str:
    statuses = [row["status"] for row in rows]
    if statuses and all(status == "healthy" for status in statuses):
        return "healthy"
    if any(status in {"error", "failed"} for status in statuses):
        return "degraded"
    if any(
        status in {"healthy", "warning", "degraded", "read_only"}
        for status in statuses
    ):
        return "degraded"
    return "unknown"


def _aggregate_freshness(rows: list[dict[str, Any]]) -> str:
    if any(row["availability"]["status"] != "available" for row in rows):
        return "unknown"
    values = {row["freshness"] for row in rows}
    if values == {"live"}:
        return "live"
    if "stale" in values:
        return "stale"
    if "delayed" in values:
        return "delayed"
    if "near_live" in values:
        return "near_live"
    if values == {"snapshot"}:
        return "snapshot"
    return "unknown"


def _latest_observed_at(rows: list[dict[str, Any]]) -> str | None:
    observations = [
        row["observed_at"]
        for row in rows
        if isinstance(row.get("observed_at"), str) and row["observed_at"]
    ]
    return max(observations) if observations else None


def build_health_payload(
    request: Request, observer: HealthObserver | None = None
) -> dict[str, Any]:
    observed_at = utc_now()
    raw: dict[str, Any] = _builtin_observations(request, observed_at)
    raw.update(_observer_observations(request, observer))
    rows = [
        _normalize_observation(definition, raw.get(definition.key))
        for definition in DEPENDENCIES
    ]
    latest = _latest_observed_at(rows)
    return {
        "request_id": request_id_from(request),
        "availability": _aggregate_availability(rows),
        "provenance": {
            "source": "m26_admin_system_health",
            "resource_identity": {
                "dependency_keys": [item.key for item in DEPENDENCIES]
            },
            "source_observed_at": latest,
        },
        "observed_at": latest,
        "freshness": _aggregate_freshness(rows),
        "data": {
            "overall_status": _aggregate_status(rows),
            "dependencies": rows,
        },
    }


def health_router() -> APIRouter:
    router = APIRouter(prefix=ADMIN_PREFIX, tags=["SystemHealth"])

    @router.get("/health", operation_id="getAdminHealth")
    async def health(request: Request) -> dict[str, Any]:
        return build_health_payload(request)

    return router


def install_admin_health(
    app: FastAPI, *, observer: HealthObserver | None = None
) -> FastAPI:
    if getattr(app.state, "admin_health_installed", False):
        return app
    app.state.admin_health_observer = observer or UnavailableHealthObserver()
    app.include_router(health_router())
    app.state.admin_health_installed = True
    return app


__all__ = [
    "DEPENDENCIES",
    "HealthObserver",
    "StaticHealthObserver",
    "build_health_payload",
    "health_router",
    "install_admin_health",
]
