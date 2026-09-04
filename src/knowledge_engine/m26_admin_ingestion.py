from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Request

from .m26_admin_contract import AdminAPIError
from .m26_admin_control_plane import (
    actor_from,
    append_audit_event,
    build_audit_event,
    request_id_from,
)
from .m26_admin_ingestion_core import (
    ConfirmJobRequest,
    DryRunRequest,
    InMemoryIngestionAdapter,
    ReadObservation,
    UnavailableIngestionAdapter,
    build_dry_run_plan,
)

CAP_INDEX_CURRENT_READ = "index.current.read"
CAP_INDEX_AUDIT_START = "index.audit.start"
CAP_INDEX_AUDIT_READ = "index.audit.read"
CAP_INGESTION_SCAN = "ingestion.scan"
CAP_INGESTION_DRY_RUN = "ingestion.dry_run.start"
CAP_INGESTION_JOBS_READ = "ingestion.jobs.read"
CAP_INGESTION_JOB_CONFIRM = "ingestion.job.confirm"
CAP_INGESTION_JOB_READ = "ingestion.job.read"


def _read_envelope(request: Request, observation: ReadObservation) -> dict[str, Any]:
    return {
        "request_id": request_id_from(request),
        "availability": {
            "status": observation.availability,
            "reason_code": observation.reason_code,
            "detail": observation.detail,
        },
        "provenance": {
            "source": observation.source,
            "resource_identity": observation.resource_identity,
            "evidence_digest": observation.evidence_digest,
            "source_observed_at": observation.observed_at,
        },
        "observed_at": observation.observed_at,
        "freshness": observation.freshness,
        "data": observation.data,
    }


def _adapter(request: Request) -> Any:
    return getattr(request.app.state, "m26_ingestion_adapter", UnavailableIngestionAdapter())


def _require_mutation_capability(request: Request, capability_id: str) -> None:
    provider = getattr(request.app.state, "admin_capability_provider", None)
    gate = provider.get_capability(capability_id) if provider else None
    if gate is None:
        raise AdminAPIError(
            status_code=409,
            code="ADMIN_CAPABILITY_EVIDENCE_REQUIRED",
            message="Capability has not been qualified",
            details={"capability_id": capability_id, "effective_state": "unavailable"},
        )
    effective_state = getattr(gate, "effective_state", None)
    mutation_authorized = getattr(gate, "mutation_authorized", None)
    if effective_state is None or mutation_authorized is None:
        raise AdminAPIError(
            status_code=409,
            code="ADMIN_CAPABILITY_CANONICAL_MAPPING_REQUIRED",
            message="Canonical capability mapping is required before mutation",
            details={
                "capability_id": capability_id,
                "effective_state": "unavailable",
                "mutation_authorized": False,
            },
        )
    if str(effective_state) != "enabled" or mutation_authorized is not True:
        raise AdminAPIError(
            status_code=409,
            code=str(getattr(gate, "reason_code", "ADMIN_CAPABILITY_DISABLED")),
            message="Capability is not authorized for mutation",
            details={
                "capability_id": capability_id,
                "effective_state": str(effective_state),
                "mutation_authorized": mutation_authorized is True,
            },
        )


def _begin_operation(request: Request, payload: Any) -> tuple[str, bool]:
    return request.app.state.admin_idempotency.begin(
        actor_id=actor_from(request).actor_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("idempotency-key", ""),
        request_payload=payload,
    )


def _accepted(request: Request, operation_id: str, replayed: bool) -> dict[str, Any]:
    return {
        "request_id": request_id_from(request),
        "operation_id": operation_id,
        "status": "accepted",
        "replayed": replayed,
    }


def _audit(request: Request, action: str, operation_id: str, reason: str) -> None:
    append_audit_event(
        request,
        build_audit_event(
            actor=actor_from(request),
            action=action,
            object_type="ingestion_control_plane",
            object_id=None,
            request_id=request_id_from(request),
            operation_id=operation_id,
            outcome="accepted",
            reason_code=reason,
        ),
    )


def _router() -> APIRouter:
    router = APIRouter(prefix="/v1/admin", tags=["Ingestion"])

    @router.get("/index/current", operation_id="getCurrentIndex")
    async def current_index(request: Request) -> dict[str, Any]:
        return _read_envelope(request, _adapter(request).current_index())

    @router.post("/index/audits", status_code=202, operation_id="startIndexAudit")
    async def start_index_audit(request: Request) -> dict[str, Any]:
        _require_mutation_capability(request, CAP_INDEX_AUDIT_START)
        operation_id, replayed = _begin_operation(request, {})
        if replayed:
            return _accepted(request, operation_id, True)
        _audit(request, "index.audit.start", operation_id, "ADMIN_INDEX_AUDIT_ACCEPTED")
        _adapter(request).start_audit(operation_id)
        return _accepted(request, operation_id, False)

    @router.get("/index/audits", operation_id="listIndexAudits")
    async def list_index_audits(request: Request) -> dict[str, Any]:
        return _read_envelope(request, _adapter(request).list_audits())

    @router.post("/ingestion/scan", status_code=202, operation_id="scanCorpus")
    async def scan_corpus(request: Request) -> dict[str, Any]:
        _require_mutation_capability(request, CAP_INGESTION_SCAN)
        operation_id, replayed = _begin_operation(request, {})
        if replayed:
            return _accepted(request, operation_id, True)
        _audit(request, "ingestion.scan", operation_id, "ADMIN_INGESTION_SCAN_ACCEPTED")
        _adapter(request).scan(operation_id)
        return _accepted(request, operation_id, False)

    @router.post("/ingestion/dry-runs", status_code=202, operation_id="createDryRun")
    async def create_dry_run(request: Request, body: DryRunRequest) -> dict[str, Any]:
        _require_mutation_capability(request, CAP_INGESTION_DRY_RUN)
        payload = body.model_dump(exclude_none=True)
        operation_id, replayed = _begin_operation(request, payload)
        if replayed:
            return _accepted(request, operation_id, True)
        _audit(request, "ingestion.dry_run.start", operation_id, "ADMIN_INGESTION_DRY_RUN_ACCEPTED")
        _adapter(request).create_dry_run(operation_id, body)
        return _accepted(request, operation_id, False)

    @router.get("/ingestion/jobs", operation_id="listIngestionJobs")
    async def list_ingestion_jobs(request: Request) -> dict[str, Any]:
        return _read_envelope(request, _adapter(request).list_jobs())

    @router.post("/ingestion/jobs", status_code=202, operation_id="confirmIngestionJob")
    async def confirm_ingestion_job(request: Request, body: ConfirmJobRequest) -> dict[str, Any]:
        _require_mutation_capability(request, CAP_INGESTION_JOB_CONFIRM)
        operation_id, replayed = _begin_operation(request, body.model_dump())
        if replayed:
            return _accepted(request, operation_id, True)
        _audit(request, "ingestion.job.confirm", operation_id, "ADMIN_INGESTION_CONFIRM_ACCEPTED")
        _adapter(request).confirm_job(operation_id, body)
        return _accepted(request, operation_id, False)

    @router.get("/ingestion/jobs/{job_id}", operation_id="getIngestionJob")
    async def get_ingestion_job(request: Request, job_id: str) -> dict[str, Any]:
        return _read_envelope(request, _adapter(request).get_job(job_id))

    return router


def install_admin_ingestion_routes(app: FastAPI, *, adapter: Any | None = None) -> FastAPI:
    if getattr(app.state, "m26_admin_ingestion_installed", False):
        return app
    app.state.m26_ingestion_adapter = adapter or UnavailableIngestionAdapter()
    app.include_router(_router())
    app.state.m26_admin_ingestion_installed = True
    return app


__all__ = [
    "CAP_INDEX_AUDIT_READ",
    "CAP_INDEX_AUDIT_START",
    "CAP_INDEX_CURRENT_READ",
    "CAP_INGESTION_DRY_RUN",
    "CAP_INGESTION_JOB_CONFIRM",
    "CAP_INGESTION_JOB_READ",
    "CAP_INGESTION_JOBS_READ",
    "CAP_INGESTION_SCAN",
    "ConfirmJobRequest",
    "DryRunRequest",
    "InMemoryIngestionAdapter",
    "ReadObservation",
    "UnavailableIngestionAdapter",
    "build_dry_run_plan",
    "install_admin_ingestion_routes",
]
