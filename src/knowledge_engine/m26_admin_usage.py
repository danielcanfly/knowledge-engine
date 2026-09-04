from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, Request

from .m26_admin_contract import ADMIN_PREFIX, redact
from .m26_admin_control_plane import request_id_from

_ALLOWED_FRESHNESS = frozenset(
    {"live", "near_live", "delayed", "snapshot", "stale", "unknown"}
)

WORKERS_AI_POLICY_VERIFIED_ON = "2026-09-05T00:00:00Z"
WORKERS_AI_FREE_ALLOCATION = 10_000
WORKERS_AI_POLICY_SOURCE = "cloudflare_workers_ai_pricing_docs_2026-08-28"


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    label: str
    unit: str
    window: str


METRIC_DEFINITIONS = (
    MetricDefinition("requests_minute", "Requests / minute", "requests", "minute"),
    MetricDefinition("requests_hour", "Requests / hour", "requests", "hour"),
    MetricDefinition("tokens_minute", "Tokens / minute", "tokens", "minute"),
    MetricDefinition("tokens_hour", "Tokens / hour", "tokens", "hour"),
    MetricDefinition("cache_reads_day", "Cache reads / day", "reads", "day"),
    MetricDefinition("cache_writes_day", "Cache writes / day", "writes", "day"),
    MetricDefinition(
        "workers_ai_neurons_day",
        "Workers AI daily neurons",
        "neurons",
        "day",
    ),
)


class UsageProvider(Protocol):
    def collect(self, request: Request) -> Mapping[str, Any]: ...


class UnavailableUsageProvider:
    def collect(self, request: Request) -> Mapping[str, Any]:
        del request
        return {}


@dataclass
class StaticUsageProvider:
    payload: Mapping[str, Any]

    def collect(self, request: Request) -> Mapping[str, Any]:
        del request
        return self.payload


def _availability(status: str, reason_code: str | None, detail: str) -> dict[str, Any]:
    return {"status": status, "reason_code": reason_code, "detail": detail}


def _provenance(
    source: str,
    *,
    observed_at: str | None,
    resource_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "resource_identity": redact(resource_identity),
        "source_observed_at": observed_at,
    }


def _valid_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _freshness(value: Any) -> str:
    return value if isinstance(value, str) and value in _ALLOWED_FRESHNESS else "unknown"


def _iso_datetime(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    try:
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    return candidate


def _unavailable_metric(definition: MetricDefinition, reason_code: str, detail: str) -> dict[str, Any]:
    return {
        "key": definition.key,
        "label": definition.label,
        "value": None,
        "unit": definition.unit,
        "window": definition.window,
        "availability": _availability("unavailable", reason_code, detail),
        "provenance": _provenance("usage_source_unavailable", observed_at=None),
        "observed_at": None,
        "freshness": "unknown",
        "limit": None,
        "remaining": None,
        "coverage": None,
    }


def _normalize_limit(raw: Any, definition: MetricDefinition) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("value")
    source = raw.get("source")
    verified = raw.get("verified") is True
    if not _valid_number(value) or not isinstance(source, str) or not source.strip():
        return None
    unit = raw.get("unit", definition.unit)
    window = raw.get("window", definition.window)
    if unit != definition.unit or window != definition.window:
        return None
    return {
        "value": value,
        "unit": definition.unit,
        "window": definition.window,
        "source": source.strip(),
        "verified": verified,
    }


def _normalize_coverage(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    start = _iso_datetime(raw.get("start"))
    end = _iso_datetime(raw.get("end"))
    complete = raw.get("complete")
    if start is None and end is None and not isinstance(complete, bool):
        return None
    return {"start": start, "end": end, "complete": complete if isinstance(complete, bool) else None}


def _normalize_metric(definition: MetricDefinition, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return _unavailable_metric(
            definition,
            "USAGE_METRIC_SOURCE_UNAVAILABLE",
            "No qualified telemetry observation is wired for this metric.",
        )

    value = raw.get("value")
    unit = raw.get("unit")
    window = raw.get("window")
    source = raw.get("source")
    if (
        not _valid_number(value)
        or unit != definition.unit
        or window != definition.window
        or not isinstance(source, str)
        or not source.strip()
    ):
        return _unavailable_metric(
            definition,
            "USAGE_METRIC_INVALID_OR_UNQUALIFIED",
            "Telemetry was rejected because value, source, unit, or window was not trustworthy.",
        )

    observed_at = _iso_datetime(raw.get("observed_at"))
    freshness = _freshness(raw.get("freshness"))
    coverage = _normalize_coverage(raw.get("coverage"))
    limit = _normalize_limit(raw.get("limit"), definition)

    remaining = None
    if limit is not None and limit["verified"]:
        remaining = {
            "value": max(float(limit["value"]) - float(value), 0.0),
            "unit": definition.unit,
            "state": "derived",
            "formula": "max(verified_limit - observed_usage, 0)",
        }

    incomplete_coverage = coverage is not None and coverage.get("complete") is False
    status = "available"
    reason_code = None
    detail = "Qualified telemetry observation."
    if observed_at is None or freshness == "unknown" or incomplete_coverage:
        status = "partial"
        reason_code = "USAGE_METRIC_PARTIAL_EVIDENCE"
        detail = (
            "Usage is reported, but freshness, observation time, or time-window coverage is incomplete."
        )

    return {
        "key": definition.key,
        "label": definition.label,
        "value": value,
        "unit": definition.unit,
        "window": definition.window,
        "availability": _availability(status, reason_code, detail),
        "provenance": _provenance(source.strip(), observed_at=observed_at),
        "observed_at": observed_at,
        "freshness": freshness,
        "limit": limit,
        "remaining": remaining,
        "coverage": coverage,
    }


def _workers_ai_policy() -> dict[str, Any]:
    return {
        "availability": _availability(
            "available",
            None,
            "Verified Workers AI free allocation policy snapshot; this is allocation, not live usage.",
        ),
        "provenance": _provenance(
            WORKERS_AI_POLICY_SOURCE,
            observed_at=WORKERS_AI_POLICY_VERIFIED_ON,
            resource_identity={"policy": "workers_ai_free_allocation"},
        ),
        "observed_at": WORKERS_AI_POLICY_VERIFIED_ON,
        "freshness": "snapshot",
        "allocation": {
            "value": WORKERS_AI_FREE_ALLOCATION,
            "unit": "neurons",
            "window": "day",
            "state": "verified",
            "reset_boundary": "00:00 UTC",
        },
    }


def _unavailable_policy() -> dict[str, Any]:
    return {
        "availability": _availability(
            "unavailable",
            "USAGE_RATE_LIMIT_POLICY_UNAVAILABLE",
            "No qualified current public rate-limit policy source is wired.",
        ),
        "provenance": _provenance("rate_limit_policy_source_unavailable", observed_at=None),
        "observed_at": None,
        "freshness": "unknown",
        "limits": None,
    }


def _normalize_policy(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return _unavailable_policy()
    source = raw.get("source")
    observed_at = _iso_datetime(raw.get("observed_at"))
    freshness = _freshness(raw.get("freshness"))
    limits = raw.get("limits")
    if not isinstance(source, str) or not source.strip() or not isinstance(limits, Mapping):
        return _unavailable_policy()
    safe_limits = {
        key: value
        for key, value in limits.items()
        if isinstance(key, str) and _valid_number(value)
    }
    if not safe_limits:
        return _unavailable_policy()
    status = "available" if observed_at is not None and freshness != "unknown" else "partial"
    return {
        "availability": _availability(
            status,
            None if status == "available" else "USAGE_RATE_LIMIT_POLICY_PARTIAL_EVIDENCE",
            "Qualified current rate-limit policy." if status == "available" else "Policy is present but freshness evidence is incomplete.",
        ),
        "provenance": _provenance(source.strip(), observed_at=observed_at),
        "observed_at": observed_at,
        "freshness": freshness,
        "limits": safe_limits,
    }


def _unavailable_gateway() -> dict[str, Any]:
    return {
        "availability": _availability(
            "unavailable",
            "USAGE_AI_GATEWAY_SOURCE_UNAVAILABLE",
            "AI Gateway billing/coverage telemetry is not wired; traffic coverage is not inferred.",
        ),
        "provenance": _provenance("ai_gateway_usage_source_unavailable", observed_at=None),
        "observed_at": None,
        "freshness": "unknown",
        "value": None,
    }


def _aggregate_availability(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    states = [metric["availability"]["status"] for metric in metrics]
    if states and all(state == "available" for state in states):
        return _availability("available", None, "All required usage metrics are available.")
    if any(state in {"available", "partial"} for state in states):
        return _availability(
            "partial",
            "USAGE_PARTIAL_TELEMETRY",
            "Partial usage telemetry: one or more required metrics are unavailable or incomplete.",
        )
    return _availability(
        "unavailable",
        "USAGE_TELEMETRY_UNAVAILABLE",
        "No qualified required usage telemetry source is currently available.",
    )


def _aggregate_freshness(metrics: list[dict[str, Any]]) -> str:
    values = {metric["freshness"] for metric in metrics if metric["value"] is not None}
    if not values:
        return "unknown"
    if "stale" in values:
        return "stale"
    if "unknown" in values:
        return "unknown"
    if len(values) == 1:
        return values.pop()
    if "delayed" in values:
        return "delayed"
    if "near_live" in values:
        return "near_live"
    return "unknown"


def _latest_observed_at(metrics: list[dict[str, Any]]) -> str | None:
    observations = [
        metric["observed_at"]
        for metric in metrics
        if isinstance(metric.get("observed_at"), str)
    ]
    return max(observations) if observations else None


def build_usage_payload(request: Request, provider: UsageProvider | None = None) -> dict[str, Any]:
    active_provider = provider or getattr(
        request.app.state,
        "admin_usage_provider",
        UnavailableUsageProvider(),
    )
    try:
        raw = active_provider.collect(request)
    except Exception:
        raw = {}
    raw_metrics = raw.get("metrics", {}) if isinstance(raw, Mapping) else {}
    if not isinstance(raw_metrics, Mapping):
        raw_metrics = {}

    metrics = [
        _normalize_metric(definition, raw_metrics.get(definition.key))
        for definition in METRIC_DEFINITIONS
    ]
    observed_at = _latest_observed_at(metrics)
    return {
        "request_id": request_id_from(request),
        "availability": _aggregate_availability(metrics),
        "provenance": _provenance(
            "m26_admin_usage",
            observed_at=observed_at,
            resource_identity={"metric_keys": [item.key for item in METRIC_DEFINITIONS]},
        ),
        "observed_at": observed_at,
        "freshness": _aggregate_freshness(metrics),
        "data": {
            "metrics": metrics,
            "rate_limit_policy": _normalize_policy(raw.get("rate_limit_policy") if isinstance(raw, Mapping) else None),
            "workers_ai_policy": _workers_ai_policy(),
            "ai_gateway": raw.get("ai_gateway") if isinstance(raw, Mapping) and isinstance(raw.get("ai_gateway"), Mapping) else _unavailable_gateway(),
        },
    }


def usage_router() -> APIRouter:
    router = APIRouter(prefix=ADMIN_PREFIX, tags=["Usage"])

    @router.get("/usage", operation_id="getUsage")
    async def usage(request: Request) -> dict[str, Any]:
        return build_usage_payload(request)

    return router


def install_admin_usage(app: FastAPI, *, provider: UsageProvider | None = None) -> FastAPI:
    if getattr(app.state, "admin_usage_installed", False):
        return app
    app.state.admin_usage_provider = provider or UnavailableUsageProvider()
    app.include_router(usage_router())
    app.state.admin_usage_installed = True
    return app


__all__ = [
    "METRIC_DEFINITIONS",
    "StaticUsageProvider",
    "UnavailableUsageProvider",
    "WORKERS_AI_FREE_ALLOCATION",
    "build_usage_payload",
    "install_admin_usage",
    "usage_router",
]
