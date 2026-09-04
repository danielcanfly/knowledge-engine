from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from .m26_admin_control_plane import (
    ADMIN_PREFIX,
    AdminAPIError,
    actor_from,
    request_id_from,
    require_capability,
)
from .m26_ask_api import DEFAULT_GATE_PATH, run_owner_query_for_web
from .m26_pa5_v8_live import LiveGateError, MiniMaxClient
from .m26_pa7_arbitrary_query_runtime import (
    _has_meaningful_overlap,
    _intent_class,
    _normalize_request_question,
    _retrieval_response_fields,
    _run_lexical_primary_retrieval,
    _select_evidence,
    _validate_gate,
)
from .m26_production_answer_bundle import (
    FULL_PRODUCTION_RELEASE_ID,
    load_production_answer_bundle,
)
from .m26_production_promotion_closure import evaluate_owner_admission, load_json
from .m26_translation_gateway import run_translation_gateway
from .m26_translation_gateway_public_api import _app_translation_provider
from .m26_verified_answer_citation_gate import canonical_sha256

_STAGE_NAMES = (
    "translation_normalization",
    "retrieval",
    "evidence_organization",
    "generation_provider",
    "validation_citations",
    "final_response",
)


class PlaygroundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    release_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


def _owner_subject_hash(request: Request) -> str:
    return hashlib.sha256(actor_from(request).subject.encode()).hexdigest()


def _canonical_envelope(
    request: Request,
    *,
    data: Mapping[str, Any],
    status: str,
    reason_code: str | None = None,
    detail: str | None = None,
    source: str = "m26_pa7_arbitrary_query_runtime",
    freshness: str = "live",
) -> dict[str, Any]:
    return {
        "request_id": request_id_from(request),
        "observed_at": None,
        "availability": {
            "status": status,
            "reason_code": reason_code,
            "detail": detail,
        },
        "provenance": {"source": source, "freshness": freshness},
        "data": dict(data),
    }


def _blank_trace() -> list[dict[str, Any]]:
    return [
        {
            "stage": stage,
            "status": "not_run",
            "reason_code": None,
            "detail": None,
            "duration_ms": None,
        }
        for stage in _STAGE_NAMES
    ]


def _set_stage(
    trace: list[dict[str, Any]],
    stage: str,
    status: str,
    *,
    reason_code: str | None = None,
    detail: str | None = None,
    duration_ms: int | None = None,
) -> None:
    item = next(row for row in trace if row["stage"] == stage)
    item.update(
        status=status,
        reason_code=reason_code,
        detail=detail,
        duration_ms=duration_ms,
    )


def _validate_release(release_id: str | None) -> None:
    if release_id and release_id != FULL_PRODUCTION_RELEASE_ID:
        raise AdminAPIError(
            status_code=400,
            code="PLAYGROUND_RELEASE_NOT_ACTIVE",
            message="Ask Playground may target only the active qualified production release",
            details={"requested_release_id": release_id},
        )


def _runtime_events_to_stage_map(events: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for event in events:
        runtime_stage = str(event.get("stage", ""))
        if runtime_stage == "retrieval":
            mapped["retrieval"] = dict(event)
        elif runtime_stage in {"synthesis", "closure"}:
            mapped["generation_provider"] = dict(event)
        elif runtime_stage in {"publication", "citation", "verification"}:
            mapped["validation_citations"] = dict(event)
    return mapped


def _retrieval_only_after_translation(
    *,
    root: Path,
    gate_path: Path,
    translated_question: str,
    owner_subject_hash: str,
    top_k: int,
    event_sink: Any = None,
) -> dict[str, Any]:
    started = time.monotonic()
    normalized_question = _normalize_request_question(translated_question)
    gate = _validate_gate(root, load_json(gate_path))
    identities = gate.get("production_identities")
    if not isinstance(identities, Mapping):
        raise AdminAPIError(
            status_code=503,
            code="PLAYGROUND_GATE_IDENTITY_MISSING",
            message="Qualified production gate identity is unavailable",
        )
    admission = evaluate_owner_admission(
        gate,
        {
            "resolved_gate_self_sha256": gate.get("self_sha256"),
            "owner_subject_hash": owner_subject_hash,
            "owner_only_route": identities.get("owner_only_route"),
            "public_request": False,
        },
    )
    if not admission["admitted"]:
        raise AdminAPIError(
            status_code=403,
            code="PLAYGROUND_RUNTIME_ADMISSION_DENIED",
            message="The qualified answer runtime denied this owner request",
            details={"reason_codes": admission.get("reason_codes", [])},
        )

    trace_id = "m26p05ret_" + canonical_sha256(
        {
            "gate": gate.get("self_sha256"),
            "question": normalized_question,
            "owner_subject_hash": owner_subject_hash,
            "nonce": uuid.uuid4().hex,
        }
    )[:32]
    intent_class = _intent_class(normalized_question)
    bundle = load_production_answer_bundle()
    if bundle.release_id != FULL_PRODUCTION_RELEASE_ID:
        raise AdminAPIError(
            status_code=503,
            code="PLAYGROUND_RELEASE_IDENTITY_MISMATCH",
            message="Loaded answer bundle is not the qualified active release",
        )
    retrieval_started = time.monotonic()
    if event_sink:
        event_sink({"type": "stage.started", "stage": "retrieval"})
    lexical, dense = _run_lexical_primary_retrieval(
        question=normalized_question,
        bundle=bundle,
        dense_channel=None,
        require_remote_dense=False,
        top_k=top_k,
        event_sink=event_sink,
        relation_aware_expansion=False,
    )
    evidence = _select_evidence(
        bundle=bundle,
        lexical_result=lexical,
        dense_result=dense,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
        allow_graph_expansion=False,
    )[:top_k]
    if event_sink:
        event_sink(
            {
                "type": "stage.completed",
                "stage": "retrieval",
                "selected_evidence_count": len(evidence),
                "latency_ms": int((time.monotonic() - retrieval_started) * 1000),
            }
        )
    return {
        "trace_id": trace_id,
        "status": "complete" if evidence else "partial",
        "terminal_status": "retrieval_complete" if evidence else "no_qualified_evidence",
        "reason_codes": []
        if evidence and _has_meaningful_overlap(normalized_question, evidence)
        else ["LOW_RETRIEVAL_SUPPORT" if evidence else "NO_AUTHORIZED_PRODUCTION_EVIDENCE"],
        "answer_text": "",
        "citations": [],
        "selected_evidence": evidence,
        "accounting": {
            "generation_provider_calls": 0,
            "generation_retries": 0,
            "cost_boundary_crossed": False,
            "payg_equivalent_cost_usd": "0",
            "latency_ms": int((time.monotonic() - started) * 1000),
        },
        "identities": {
            "production_release_id": bundle.release_id,
            "production_manifest_sha256": bundle.manifest_sha256,
            "resolved_gate_self_sha256": gate.get("self_sha256"),
        },
        "retrieval": _retrieval_response_fields(
            gate=gate,
            bundle=bundle,
            lexical_result=lexical,
            dense_result=dense,
            selected_evidence=evidence,
            intent_class=intent_class,
        ),
    }


def _full_ask_after_translation(
    *,
    root: Path,
    gate_path: Path,
    translated_question: str,
    owner_subject_hash: str,
    event_sink: Any,
) -> dict[str, Any]:
    try:
        provider = MiniMaxClient(
            os.environ.get("MINIMAX_API_KEY", ""),
            max_calls=1,
            max_cost=Decimal("0.10"),
        )
    except LiveGateError as exc:
        raise AdminAPIError(
            status_code=503,
            code="PLAYGROUND_PROVIDER_CONFIGURATION_MISSING",
            message="Full Ask synthesis provider is unavailable",
            details={"reason_code": type(exc).__name__},
        ) from exc
    return run_owner_query_for_web(
        root=root,
        gate_path=gate_path,
        request_payload={"question": translated_question},
        owner_subject_hash=owner_subject_hash,
        public_request=False,
        provider_client=provider,
        require_remote_dense=False,
        max_provider_calls=1,
        max_cost=Decimal("0.10"),
        event_sink=event_sink,
    )


def _failure_data(
    *,
    mode: str,
    trace: list[dict[str, Any]],
    reason_code: str,
    detail: str,
    translation: Mapping[str, Any] | None = None,
    events: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "trace": trace,
        "translation": dict(translation or {}),
        "runtime_events": [dict(item) for item in events or []],
        "reason_codes": [reason_code],
        "answer_text": "",
        "citations": [],
        "selected_evidence": [],
        "accounting": {
            "generation_provider_calls": sum(
                1 for item in events or [] if item.get("type") == "model.started"
            ),
            "generation_retries": 0,
            "cost_boundary_crossed": any(
                item.get("type") == "model.started" for item in events or []
            ),
            "payg_equivalent_cost_usd": "0",
        },
        "failure": {"reason_code": reason_code, "detail": detail},
    }


def router() -> APIRouter:
    api = APIRouter(prefix=ADMIN_PREFIX, tags=["Playground"])

    @api.post(
        "/playground/retrieve",
        operation_id="inspectRetrieval",
        openapi_extra={
            "x-m26-capability-id": "playground.retrieve",
            "x-m26-public-contract-separate": True,
            "x-m26-state-changing": False,
        },
    )
    async def inspect_retrieval(payload: PlaygroundRequest, request: Request) -> dict[str, Any]:
        require_capability(request, "playground.retrieve", mutation=False)
        _validate_release(payload.release_id)
        trace = _blank_trace()
        events: list[Mapping[str, Any]] = []
        root = request.app.state.root
        gate_path = request.app.state.gate_path or DEFAULT_GATE_PATH
        translation_started = time.monotonic()

        def downstream(translated: str) -> Mapping[str, Any]:
            return _retrieval_only_after_translation(
                root=root,
                gate_path=gate_path,
                translated_question=translated,
                owner_subject_hash=_owner_subject_hash(request),
                top_k=payload.top_k,
                event_sink=events.append,
            )

        result = run_translation_gateway(
            question=payload.question,
            downstream=downstream,
            provider=_app_translation_provider(request.app),
            correlation_id=request_id_from(request),
        )
        if not result.ok:
            _set_stage(
                trace,
                "translation_normalization",
                "failed",
                reason_code="translation_failed",
                detail=result.failure_code,
                duration_ms=int((time.monotonic() - translation_started) * 1000),
            )
            data = _failure_data(
                mode="retrieve",
                trace=trace,
                reason_code="translation_failed",
                detail=result.failure_code,
                translation=result.observability,
            )
            return _canonical_envelope(
                request,
                data=data,
                status="unavailable",
                reason_code="translation_failed",
                detail=result.failure_code,
            )
        _set_stage(
            trace,
            "translation_normalization",
            "complete",
            duration_ms=int((time.monotonic() - translation_started) * 1000),
        )
        runtime = dict(result.sealed_m26_response or {})
        _set_stage(trace, "retrieval", "complete")
        _set_stage(trace, "evidence_organization", "complete")
        data = {
            "mode": "retrieve",
            "trace": trace,
            "translation": result.observability,
            "runtime_events": [dict(item) for item in events],
            **runtime,
        }
        return _canonical_envelope(
            request,
            data=data,
            status="available" if runtime.get("selected_evidence") else "partial",
            reason_code=(runtime.get("reason_codes") or [None])[0],
        )

    @api.post(
        "/playground/ask",
        operation_id="runFullAsk",
        openapi_extra={
            "x-m26-capability-id": "playground.ask",
            "x-m26-public-contract-separate": True,
            "x-m26-state-changing": False,
        },
    )
    async def full_ask(payload: PlaygroundRequest, request: Request) -> dict[str, Any]:
        require_capability(request, "playground.ask", mutation=False)
        _validate_release(payload.release_id)
        trace = _blank_trace()
        events: list[Mapping[str, Any]] = []
        root = request.app.state.root
        gate_path = request.app.state.gate_path or DEFAULT_GATE_PATH
        translation_started = time.monotonic()

        def downstream(translated: str) -> Mapping[str, Any]:
            return _full_ask_after_translation(
                root=root,
                gate_path=gate_path,
                translated_question=translated,
                owner_subject_hash=_owner_subject_hash(request),
                event_sink=events.append,
            )

        try:
            result = run_translation_gateway(
                question=payload.question,
                downstream=downstream,
                provider=_app_translation_provider(request.app),
                correlation_id=request_id_from(request),
            )
        except AdminAPIError:
            raise
        except Exception as exc:
            runtime_map = _runtime_events_to_stage_map(events)
            _set_stage(
                trace,
                "translation_normalization",
                "complete",
                duration_ms=int((time.monotonic() - translation_started) * 1000),
            )
            if "retrieval" in runtime_map and runtime_map["retrieval"].get("type") != "stage.completed":
                _set_stage(trace, "retrieval", "failed", reason_code="retrieval_failed")
                reason = "retrieval_failed"
            else:
                _set_stage(trace, "retrieval", "complete")
                _set_stage(trace, "evidence_organization", "complete")
                _set_stage(trace, "generation_provider", "failed", reason_code="provider_failed")
                reason = "provider_failed"
            data = _failure_data(
                mode="ask",
                trace=trace,
                reason_code=reason,
                detail=type(exc).__name__,
                events=events,
            )
            return _canonical_envelope(
                request,
                data=data,
                status="partial",
                reason_code=reason,
                detail=type(exc).__name__,
            )

        if not result.ok:
            _set_stage(
                trace,
                "translation_normalization",
                "failed",
                reason_code="translation_failed",
                detail=result.failure_code,
                duration_ms=int((time.monotonic() - translation_started) * 1000),
            )
            data = _failure_data(
                mode="ask",
                trace=trace,
                reason_code="translation_failed",
                detail=result.failure_code,
                translation=result.observability,
                events=events,
            )
            return _canonical_envelope(
                request,
                data=data,
                status="unavailable",
                reason_code="translation_failed",
                detail=result.failure_code,
            )

        runtime = dict(result.sealed_m26_response or {})
        _set_stage(trace, "translation_normalization", "complete")
        _set_stage(trace, "retrieval", "complete")
        _set_stage(trace, "evidence_organization", "complete")
        accounting = runtime.get("accounting") if isinstance(runtime.get("accounting"), Mapping) else {}
        provider_calls = int(accounting.get("provider_call_count", 0) or 0)
        reason_codes = [str(item) for item in runtime.get("reason_codes", [])]
        provider_failed = "PROVIDER_CALL_FAILED" in reason_codes
        if provider_calls:
            _set_stage(
                trace,
                "generation_provider",
                "failed" if provider_failed else "complete",
                reason_code="provider_failed" if provider_failed else None,
            )
        if provider_calls and not provider_failed:
            _set_stage(trace, "validation_citations", "complete")
            _set_stage(trace, "final_response", "complete")
        runtime["accounting"] = {
            **dict(accounting),
            "generation_provider_calls": provider_calls,
            "generation_retries": 0,
            "cost_boundary_crossed": provider_calls > 0,
        }
        data = {
            "mode": "ask",
            "trace": trace,
            "translation": result.observability,
            "runtime_events": [dict(item) for item in events],
            **runtime,
        }
        availability = "partial" if provider_failed or runtime.get("safe_abstention") else "available"
        return _canonical_envelope(
            request,
            data=data,
            status=availability,
            reason_code="provider_failed" if provider_failed else None,
        )

    return api


__all__ = ["PlaygroundRequest", "router"]
