from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field

from .m26_admin_contract import ADMIN_PREFIX, AdminAPIError, redact
from .m26_admin_control_plane import request_id_from

P09_EVIDENCE_PROVIDER_STATE = "m26_jobs_rollback_evidence_provider"


@dataclass(frozen=True)
class EvidenceObservation:
    availability_status: str
    reason_code: str | None
    detail: str | None
    source: str
    data: Any
    observed_at: str | None = None
    freshness: str = "unknown"
    resource_identity: Mapping[str, Any] | None = None
    evidence_digest: str | None = None
    source_observed_at: str | None = None

    def __post_init__(self) -> None:
        if self.availability_status not in {"available", "partial", "unavailable"}:
            raise ValueError(f"invalid availability status: {self.availability_status}")
        if self.freshness not in {
            "live",
            "near_live",
            "delayed",
            "snapshot",
            "stale",
            "unknown",
        }:
            raise ValueError(f"invalid freshness: {self.freshness}")
        if self.availability_status == "unavailable" and self.data is not None:
            raise ValueError("unavailable observations must not fabricate data")


class JobsRollbackEvidenceProvider(Protocol):
    def list_jobs(self) -> EvidenceObservation: ...

    def get_job(self, job_id: str) -> EvidenceObservation: ...

    def list_versions(self) -> EvidenceObservation: ...


class ActivateVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preflight_token: str = Field(min_length=1)
    confirmation: Literal[True]


class UnavailableJobsRollbackEvidenceProvider:
    _REASON = "P09_AUTHORITATIVE_EVIDENCE_SOURCE_UNAVAILABLE"
    _DETAIL = (
        "No qualified ingestion-job or index-lineage evidence provider is configured. "
        "No empty/zero/current state has been inferred."
    )

    def _unavailable(self) -> EvidenceObservation:
        return EvidenceObservation(
            availability_status="unavailable",
            reason_code=self._REASON,
            detail=self._DETAIL,
            source="p09_jobs_rollback.unconfigured",
            data=None,
        )

    def list_jobs(self) -> EvidenceObservation:
        return self._unavailable()

    def get_job(self, job_id: str) -> EvidenceObservation:
        return self._unavailable()

    def list_versions(self) -> EvidenceObservation:
        return self._unavailable()


def _provider(request: Request) -> JobsRollbackEvidenceProvider:
    provider = getattr(request.app.state, P09_EVIDENCE_PROVIDER_STATE, None)
    if provider is None:
        return UnavailableJobsRollbackEvidenceProvider()
    return provider


def canonical_envelope(request: Request, observation: EvidenceObservation) -> dict[str, Any]:
    return {
        "request_id": request_id_from(request),
        "availability": {
            "status": observation.availability_status,
            "reason_code": observation.reason_code,
            "detail": observation.detail,
        },
        "provenance": {
            "source": observation.source,
            "resource_identity": redact(observation.resource_identity),
            "evidence_digest": observation.evidence_digest,
            "source_observed_at": observation.source_observed_at,
        },
        "observed_at": observation.observed_at,
        "freshness": observation.freshness,
        "data": redact(observation.data),
    }


def _unavailable_capability(capability_id: str) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "qualification_status": "unavailable",
        "effective_state": "unavailable",
        "mutation_authorized": False,
        "reason_code": "P09_PRODUCTION_POINTER_AUTHORITY_UNQUALIFIED",
        "source": "p09_jobs_rollback.fail_closed",
        "observed_at": None,
        "resource_identity": None,
        "evidence_digest": None,
    }


def _rollback_preflight_payload(request: Request, version_id: str) -> dict[str, Any]:
    reason_code = "P09_ROLLBACK_PREFLIGHT_UNQUALIFIED"
    return {
        "request_id": request_id_from(request),
        "availability": {
            "status": "unavailable",
            "reason_code": reason_code,
            "detail": (
                "The exact production pointer resource and rollback actuator are not qualified. "
                "Preflight remains fail-closed and no token is issued."
            ),
        },
        "provenance": {
            "source": "p09_jobs_rollback.fail_closed",
            "resource_identity": None,
            "evidence_digest": None,
            "source_observed_at": None,
        },
        "observed_at": None,
        "freshness": "unknown",
        "data": {
            "version_id": version_id,
            "eligibility": "not_eligible",
            "reason_code": reason_code,
            "immutable_target": None,
            "evidence_digest": None,
            "preflight_token": None,
            "expires_at": None,
            "pointer_digest": None,
            "pointer_etag": None,
            "write_attempts": 0,
            "activation_capability": _unavailable_capability("index.activate"),
            "mismatches": [
                "authoritative_version_evidence_unavailable",
                "production_pointer_authority_unqualified",
            ],
        },
    }


def _router() -> APIRouter:
    router = APIRouter(prefix=ADMIN_PREFIX, tags=["Jobs"])

    @router.get("/ingestion/jobs", operation_id="listIngestionJobs")
    async def list_ingestion_jobs(request: Request) -> dict[str, Any]:
        return canonical_envelope(request, _provider(request).list_jobs())

    @router.get("/ingestion/jobs/{job_id}", operation_id="getIngestionJob")
    async def get_ingestion_job(job_id: str, request: Request) -> dict[str, Any]:
        return canonical_envelope(request, _provider(request).get_job(job_id))

    @router.get("/index/versions", operation_id="listIndexVersions")
    async def list_index_versions(request: Request) -> dict[str, Any]:
        return canonical_envelope(request, _provider(request).list_versions())

    @router.post(
        "/index/versions/{version_id}/rollback-preflight",
        operation_id="rollbackPreflight",
    )
    async def rollback_preflight(version_id: str, request: Request) -> dict[str, Any]:
        # Evidence-only by construction. This performs no R2/Qdrant/pointer write.
        return _rollback_preflight_payload(request, version_id)

    @router.post("/index/versions/{version_id}/activate", operation_id="activateVersion")
    async def activate_version(
        version_id: str,
        request: Request,
        body: ActivateVersionRequest,
    ) -> None:
        # Body validation happens before this fail-closed boundary. No production actuator is
        # installed by this lane, so reject before idempotency persistence, durable audit, or
        # any storage/pointer mutation is attempted.
        del request, body
        raise AdminAPIError(
            status_code=503,
            code="P09_PRODUCTION_POINTER_ACTUATOR_UNAVAILABLE",
            message="Production index activation is not qualified",
            details={
                "version_id": version_id,
                "capability_id": "index.activate",
                "mutation_authorized": False,
            },
        )

    return router


def install_jobs_rollback_routes(
    app: FastAPI,
    *,
    evidence_provider: JobsRollbackEvidenceProvider | None = None,
) -> FastAPI:
    if getattr(app.state, "m26_jobs_rollback_installed", False):
        return app
    setattr(
        app.state,
        P09_EVIDENCE_PROVIDER_STATE,
        evidence_provider or UnavailableJobsRollbackEvidenceProvider(),
    )
    app.include_router(_router())
    app.state.m26_jobs_rollback_installed = True
    return app


__all__ = [
    "ActivateVersionRequest",
    "EvidenceObservation",
    "JobsRollbackEvidenceProvider",
    "UnavailableJobsRollbackEvidenceProvider",
    "canonical_envelope",
    "install_jobs_rollback_routes",
]
