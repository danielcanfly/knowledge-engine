from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from typing import Any

from . import m26_ask_api as ask_api
from . import m26_pa7_arbitrary_query_runtime as legacy
from . import m26_public_api as public_api
from .m26_cloudflare_provider_router import (
    CLOUDFLARE_MODEL,
    CLOUDFLARE_PROVIDER,
    MINIMAX_MODEL,
    MINIMAX_PROVIDER,
    SEMANTIC_REVIEW_CALL_CLASS,
    CloudflareFallbackRequired,
)

_TRUTH_STAGES = {"closure", "review", "repair", "verification"}
_TLS = threading.local()

_ORIGINAL_BUILD_PROVIDER_ROUTING_CLIENT = getattr(
    ask_api,
    "_track1_original_build_provider_routing_client",
    ask_api.build_provider_routing_client,
)
_ORIGINAL_VERIFY_MULTI_EVIDENCE_PROVIDER_OUTPUT = getattr(
    legacy,
    "_track1_original_verify_multi_evidence_provider_output",
    legacy._verify_multi_evidence_provider_output,
)
_ORIGINAL_PUBLIC_RUN_OWNER_QUERY_FOR_WEB = getattr(
    public_api,
    "_track1_original_run_owner_query_for_web",
    public_api.run_owner_query_for_web,
)

ask_api._track1_original_build_provider_routing_client = (  # type: ignore[attr-defined]
    _ORIGINAL_BUILD_PROVIDER_ROUTING_CLIENT
)
legacy._track1_original_verify_multi_evidence_provider_output = (  # type: ignore[attr-defined]
    _ORIGINAL_VERIFY_MULTI_EVIDENCE_PROVIDER_OUTPUT
)
public_api._track1_original_run_owner_query_for_web = (  # type: ignore[attr-defined]
    _ORIGINAL_PUBLIC_RUN_OWNER_QUERY_FOR_WEB
)


def _raw_sink() -> Any:
    return getattr(_TLS, "raw_sink", None)


def _emit(event_type: str, **fields: Any) -> None:
    legacy._emit_runtime_event(_raw_sink(), event_type, **fields)


def _truth_filter(event_sink: Any):
    if event_sink is None:
        return None

    def filtered(event: Mapping[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        stage = str(event.get("stage", ""))
        if event_type in {"model.started", "model.completed", "repair.started"}:
            return
        if event_type in {"stage.started", "stage.completed"} and stage in _TRUTH_STAGES:
            return
        event_sink(event)

    return filtered


def _route_identity(inner: Any, call_class: str) -> tuple[str, str, str, bool, str]:
    if call_class == SEMANTIC_REVIEW_CALL_CLASS:
        return "semantic_reviewer", MINIMAX_PROVIDER, MINIMAX_MODEL, False, "NONE"

    route, reason = inner.state.route_before_call()
    if route == MINIMAX_PROVIDER or inner.cloudflare is None:
        fallback_reason = str(reason)
        if inner.cloudflare is None and fallback_reason == "NONE":
            fallback_reason = "DISABLED_CONFIGURATION"
        return "closure", MINIMAX_PROVIDER, MINIMAX_MODEL, True, fallback_reason
    return "closure", CLOUDFLARE_PROVIDER, CLOUDFLARE_MODEL, False, "NONE"


class ExecutionBoundaryProviderClient:
    """Observability-only proxy around the accepted provider routing client."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def telemetry(self) -> dict[str, Any]:
        return self._inner.telemetry()

    def call(self, payload: Mapping[str, Any], call_class: str) -> dict[str, Any]:
        attempt = 2 if call_class == "aq_semantic_closure_repair" else 1
        role, provider, model, fallback_used, fallback_reason = _route_identity(
            self._inner, call_class
        )
        _TLS.attempt = attempt

        if attempt == 2 and role == "closure":
            _emit("repair.started", reason_codes=[])

        stage = "review" if role == "semantic_reviewer" else "closure"
        _emit("stage.started", stage=stage, attempt=attempt)
        _emit(
            "model.started",
            role=role,
            provider=provider,
            model=model,
            attempt=attempt,
            status="started",
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
        started = time.monotonic()
        try:
            result = self._inner.call(payload, call_class)
        except CloudflareFallbackRequired as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            _emit(
                "model.completed",
                role=role,
                provider=provider,
                model=model,
                attempt=attempt,
                status="fallback_required",
                latency_ms=latency_ms,
                fallback_used=True,
                fallback_reason=str(getattr(self._inner, "fallback_reason", "") or exc.reason),
            )
            _emit(
                "stage.completed",
                stage=stage,
                attempt=attempt,
                status="fallback_required",
            )
            raise
        except Exception as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            _emit(
                "model.completed",
                role=role,
                provider=provider,
                model=model,
                attempt=attempt,
                status="failed",
                latency_ms=latency_ms,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                error_class=type(exc).__name__,
            )
            _emit(
                "stage.completed",
                stage=stage,
                attempt=attempt,
                status="failed",
            )
            raise

        latency_ms = int(result.get("latency_ms", int((time.monotonic() - started) * 1000)))
        _emit(
            "model.completed",
            role=role,
            provider=provider,
            model=model,
            attempt=attempt,
            status="completed",
            latency_ms=latency_ms,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
        _emit(
            "stage.completed",
            stage=stage,
            attempt=attempt,
            status="completed",
        )
        return result


def _build_provider_routing_client(*args: Any, **kwargs: Any) -> ExecutionBoundaryProviderClient:
    return ExecutionBoundaryProviderClient(
        _ORIGINAL_BUILD_PROVIDER_ROUTING_CLIENT(*args, **kwargs)
    )


def _verify_multi_evidence_provider_output(*args: Any, **kwargs: Any) -> Any:
    attempt = int(getattr(_TLS, "attempt", 1) or 1)
    _emit("stage.started", stage="verification", attempt=attempt)
    try:
        result = _ORIGINAL_VERIFY_MULTI_EVIDENCE_PROVIDER_OUTPUT(*args, **kwargs)
    except Exception as exc:
        _emit(
            "stage.completed",
            stage="verification",
            attempt=attempt,
            status="failed",
            error_code=str(getattr(exc, "code", type(exc).__name__)),
        )
        raise
    _emit(
        "stage.completed",
        stage="verification",
        attempt=attempt,
        status="verified",
    )
    return result


def _run_owner_query_for_web(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raw_event_sink = kwargs.get("event_sink")
    previous_sink = getattr(_TLS, "raw_sink", None)
    previous_attempt = getattr(_TLS, "attempt", 1)
    _TLS.raw_sink = raw_event_sink
    _TLS.attempt = 1
    kwargs["event_sink"] = _truth_filter(raw_event_sink)

    # Track 1 staging is contractually bound to the frozen remote dense path.
    # A local dense channel must never be injected as an availability fallback.
    kwargs.pop("dense_channel", None)
    kwargs["require_remote_dense"] = True

    try:
        return _ORIGINAL_PUBLIC_RUN_OWNER_QUERY_FOR_WEB(*args, **kwargs)
    finally:
        _TLS.raw_sink = previous_sink
        _TLS.attempt = previous_attempt


# Install process-local observability/safety adapters for the isolated public façade only.
ask_api.build_provider_routing_client = _build_provider_routing_client
legacy._verify_multi_evidence_provider_output = _verify_multi_evidence_provider_output
public_api.run_owner_query_for_web = _run_owner_query_for_web

# Never reconstruct executed model events from a final DTO. Model events above are emitted
# at the provider execution boundary with the route selected for that exact call.
public_api._model_events_from_dto = lambda dto: []

app = public_api.app
