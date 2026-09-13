from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m26_admin_contract import AdminAPIError, canonical_json_bytes, utc_now


class DryRunRequest(BaseModel):
    scope: Literal["single_document", "stale_documents", "explicit_documents"]
    document_ids: list[str] | None = Field(default=None, max_length=100)


class ConfirmJobRequest(BaseModel):
    dry_run_id: str = Field(min_length=1, max_length=160)
    dry_run_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation: Literal[True]


@dataclass(frozen=True)
class ReadObservation:
    availability: Literal["available", "partial", "unavailable"]
    data: Any
    source: str
    observed_at: str | None = None
    freshness: Literal["live", "near_live", "delayed", "snapshot", "stale", "unknown"] = "unknown"
    reason_code: str | None = None
    detail: str | None = None
    resource_identity: Mapping[str, Any] | None = None
    evidence_digest: str | None = None


class UnavailableIngestionAdapter:
    """Fail-closed production default until an exact governed adapter is qualified."""

    reason_code = "ADMIN_INGESTION_ADAPTER_UNQUALIFIED"

    def current_index(self) -> ReadObservation:
        return self._unavailable("current_index")

    def list_audits(self) -> ReadObservation:
        return self._unavailable("index_audits")

    def list_jobs(self) -> ReadObservation:
        return self._unavailable("ingestion_jobs")

    def get_job(self, job_id: str) -> ReadObservation:
        return self._unavailable(f"ingestion_job:{job_id}")

    def scan(self, operation_id: str) -> None:
        self._raise_mutation_unavailable()

    def create_dry_run(self, operation_id: str, request: DryRunRequest) -> None:
        self._raise_mutation_unavailable()

    def confirm_job(self, operation_id: str, request: ConfirmJobRequest) -> None:
        self._raise_mutation_unavailable()

    def start_audit(self, operation_id: str) -> None:
        self._raise_mutation_unavailable()

    def _unavailable(self, target: str) -> ReadObservation:
        return ReadObservation(
            availability="unavailable",
            data=None,
            source="m26_ingestion_adapter",
            reason_code=self.reason_code,
            detail=f"No qualified production adapter is bound for {target}.",
        )

    def _raise_mutation_unavailable(self) -> None:
        raise AdminAPIError(
            status_code=503,
            code=self.reason_code,
            message="The governed production ingestion adapter is not qualified",
        )


def build_dry_run_plan(
    *,
    source_revision: str,
    documents: Sequence[Mapping[str, Any]],
    active_document_digests: Mapping[str, str],
    scope: str,
    document_ids: Sequence[str] | None,
) -> dict[str, Any]:
    source = {str(item["document_id"]): str(item["digest"]) for item in documents}
    requested = sorted(set(document_ids or []))
    if scope == "single_document":
        if len(requested) != 1:
            raise AdminAPIError(
                status_code=422,
                code="ADMIN_INGESTION_SINGLE_DOCUMENT_REQUIRED",
                message="single_document scope requires exactly one document_id",
            )
        selected = requested
    elif scope == "explicit_documents":
        if not requested:
            raise AdminAPIError(
                status_code=422,
                code="ADMIN_INGESTION_EXPLICIT_DOCUMENTS_REQUIRED",
                message="explicit_documents scope requires document_ids",
            )
        selected = requested
    elif scope == "stale_documents":
        selected = sorted(
            key for key, digest in source.items() if active_document_digests.get(key) != digest
        )
    else:
        raise AdminAPIError(
            status_code=422,
            code="ADMIN_INGESTION_SCOPE_INVALID",
            message="Unsupported ingestion scope",
        )
    missing = sorted(set(selected) - set(source))
    if missing:
        raise AdminAPIError(
            status_code=422,
            code="ADMIN_INGESTION_DOCUMENT_UNKNOWN",
            message="Requested document is not present in the source snapshot",
            details={"document_ids": missing},
        )
    actions = [
        {
            "document_id": document_id,
            "source_digest": source[document_id],
            "active_digest": active_document_digests.get(document_id),
            "action": "reindex" if document_id in active_document_digests else "add",
        }
        for document_id in selected
    ]
    plan = {
        "source_revision": source_revision,
        "scope": scope,
        "document_ids": selected,
        "actions": actions,
        "activation": "separate_explicit_action_required",
    }
    digest = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return {
        "dry_run_id": "dryrun_" + digest[:24],
        "dry_run_digest": digest,
        "plan": plan,
    }


class InMemoryIngestionAdapter:
    """Deterministic test/reference adapter. Never installed by production."""

    def __init__(
        self,
        *,
        source_revision: str,
        documents: Sequence[Mapping[str, Any]],
        active_document_digests: Mapping[str, str] | None = None,
    ) -> None:
        self.source_revision = source_revision
        self.documents = tuple(self._normalize_document(item) for item in documents)
        self.active_document_digests = dict(active_document_digests or {})
        self.jobs: list[dict[str, Any]] = []
        self.audits: list[dict[str, Any]] = []
        self.confirmed_job_ids: list[str] = []

    def current_index(self) -> ReadObservation:
        identity = {
            "source_revision": self.source_revision,
            "document_count": len(self.active_document_digests),
            "document_digests": dict(sorted(self.active_document_digests.items())),
        }
        digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
        return ReadObservation(
            availability="available",
            data=identity,
            source="in_memory_ingestion_fixture",
            observed_at=utc_now(),
            freshness="snapshot",
            resource_identity={"source_revision": self.source_revision},
            evidence_digest=digest,
        )

    def list_audits(self) -> ReadObservation:
        return ReadObservation(
            availability="available",
            data={"audits": list(self.audits), "write_attempts": 0, "repair_attempts": 0},
            source="in_memory_ingestion_fixture",
            observed_at=utc_now(),
            freshness="live",
        )

    def list_jobs(self) -> ReadObservation:
        return ReadObservation(
            availability="available",
            data={"jobs": list(self.jobs)},
            source="in_memory_ingestion_fixture",
            observed_at=utc_now(),
            freshness="live",
        )

    def get_job(self, job_id: str) -> ReadObservation:
        match = next(
            (
                item
                for item in self.jobs
                if item.get("job_id") == job_id or item.get("operation_id") == job_id
            ),
            None,
        )
        if match is None:
            return ReadObservation(
                availability="unavailable",
                data=None,
                source="in_memory_ingestion_fixture",
                reason_code="ADMIN_INGESTION_JOB_NOT_FOUND",
                detail="No job evidence exists for this identifier.",
            )
        return ReadObservation(
            availability="available",
            data=match,
            source="in_memory_ingestion_fixture",
            observed_at=match.get("observed_at"),
            freshness="snapshot",
        )

    def scan(self, operation_id: str) -> None:
        current = self.active_document_digests
        source = {item["document_id"]: item["digest"] for item in self.documents}
        self.jobs.append(
            {
                "operation_id": operation_id,
                "job_id": operation_id,
                "kind": "source_scan",
                "status": "succeeded",
                "source_revision": self.source_revision,
                "manifest_diff": {
                    "added": sorted(set(source) - set(current)),
                    "changed": sorted(
                        k for k in source.keys() & current.keys() if source[k] != current[k]
                    ),
                    "deleted": sorted(set(current) - set(source)),
                    "unchanged": sorted(
                        k for k in source.keys() & current.keys() if source[k] == current[k]
                    ),
                },
                "observed_at": utc_now(),
                "production_write_attempts": 0,
            }
        )

    def create_dry_run(self, operation_id: str, request: DryRunRequest) -> None:
        plan = build_dry_run_plan(
            source_revision=self.source_revision,
            documents=self.documents,
            active_document_digests=self.active_document_digests,
            scope=request.scope,
            document_ids=request.document_ids,
        )
        self.jobs.append(
            {
                "operation_id": operation_id,
                "job_id": operation_id,
                "kind": "dry_run",
                "status": "awaiting_confirmation",
                "dry_run_id": plan["dry_run_id"],
                "dry_run_digest": plan["dry_run_digest"],
                "source_revision": self.source_revision,
                "plan": plan["plan"],
                "observed_at": utc_now(),
                "production_write_attempts": 0,
            }
        )

    def confirm_job(self, operation_id: str, request: ConfirmJobRequest) -> None:
        dry_run = next(
            (
                item
                for item in reversed(self.jobs)
                if item.get("kind") == "dry_run" and item.get("dry_run_id") == request.dry_run_id
            ),
            None,
        )
        if dry_run is None or dry_run.get("dry_run_digest") != request.dry_run_digest:
            raise AdminAPIError(
                status_code=409,
                code="ADMIN_INGESTION_DRY_RUN_STALE",
                message="Dry-run identity or digest no longer matches",
            )
        if dry_run.get("source_revision") != self.source_revision:
            raise AdminAPIError(
                status_code=409,
                code="ADMIN_INGESTION_SOURCE_REVISION_CHANGED",
                message="Source revision changed after dry run",
            )
        job_id = "ingjob_" + operation_id.removeprefix("admop_")
        self.confirmed_job_ids.append(job_id)
        self.jobs.append(
            {
                "operation_id": operation_id,
                "job_id": job_id,
                "kind": "confirmed_ingestion",
                "status": "queued",
                "dry_run_id": request.dry_run_id,
                "dry_run_digest": request.dry_run_digest,
                "source_revision": self.source_revision,
                "observed_at": utc_now(),
                "candidate_activation": "not_requested",
            }
        )

    def start_audit(self, operation_id: str) -> None:
        self.audits.append(
            {
                "audit_id": "idxaudit_" + operation_id.removeprefix("admop_"),
                "operation_id": operation_id,
                "status": "succeeded",
                "source_revision": self.source_revision,
                "write_attempts": 0,
                "repair_attempts": 0,
                "observed_at": utc_now(),
            }
        )

    @staticmethod
    def _normalize_document(item: Mapping[str, Any]) -> dict[str, str]:
        document_id = str(item.get("document_id", "")).strip()
        digest = str(item.get("digest", "")).strip().lower()
        if (
            not document_id
            or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            raise ValueError("documents require document_id and lowercase sha256 digest")
        return {"document_id": document_id, "digest": digest}
