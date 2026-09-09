from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from .m26_admin_contract import AdminAPIError, canonical_json_bytes, utc_now
from .m26_admin_ingestion_core import ReadObservation


class SyncBlogRequest(BaseModel):
    """Operator intent for one-click blog synchronization.

    Add/change-only plans can execute without an extra product confirmation.
    A plan containing removals/unpublishes is destructive and must carry both an
    explicit confirmation and the exact plan digest shown to the operator.
    """

    confirmation: bool = False
    expected_plan_digest: str | None = None


def build_manifest_diff(
    *,
    documents: Sequence[Mapping[str, Any]],
    active_document_digests: Mapping[str, str],
) -> dict[str, list[str]]:
    source = {str(item["document_id"]): str(item["digest"]) for item in documents}
    active = {str(key): str(value) for key, value in active_document_digests.items()}
    shared = source.keys() & active.keys()
    return {
        "added": sorted(set(source) - set(active)),
        "changed": sorted(key for key in shared if source[key] != active[key]),
        "removed": sorted(set(active) - set(source)),
        "unchanged": sorted(key for key in shared if source[key] == active[key]),
    }


def build_sync_plan(
    *,
    source_revision: str,
    documents: Sequence[Mapping[str, Any]],
    active_document_digests: Mapping[str, str],
) -> dict[str, Any]:
    source = {str(item["document_id"]): str(item["digest"]) for item in documents}
    diff = build_manifest_diff(
        documents=documents,
        active_document_digests=active_document_digests,
    )
    actions = [
        {
            "document_id": document_id,
            "action": "add",
            "source_digest": source[document_id],
            "active_digest": None,
        }
        for document_id in diff["added"]
    ]
    actions.extend(
        {
            "document_id": document_id,
            "action": "reindex",
            "source_digest": source[document_id],
            "active_digest": active_document_digests[document_id],
        }
        for document_id in diff["changed"]
    )
    actions.extend(
        {
            "document_id": document_id,
            "action": "remove",
            "source_digest": None,
            "active_digest": active_document_digests[document_id],
        }
        for document_id in diff["removed"]
    )
    plan = {
        "source_revision": source_revision,
        "manifest_diff": diff,
        "actions": actions,
        "requires_confirmation": bool(diff["removed"]),
        "verification": "vector_lexical_parity_required_before_finalize",
    }
    digest = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return {
        "plan_id": "syncplan_" + digest[:24],
        "plan_digest": digest,
        "plan": plan,
    }


def _empty_active() -> dict[str, Any]:
    return {
        "status": "unknown",
        "release_id": None,
        "manifest_key": None,
        "manifest_sha256": None,
        "source_identity_digest": None,
        "source_revision": None,
        "document_count": None,
        "lexical_chunk_count": None,
        "vector_chunk_count": None,
        "vector_lexical_parity": "unproven",
        "qdrant_collection": None,
        "issues": [],
    }


def _empty_candidate() -> dict[str, Any]:
    return {
        "status": "absent",
        "is_active": False,
        "release_id": None,
        "manifest_key": None,
        "manifest_sha256": None,
        "job_id": None,
        "operation_id": None,
        "attempt": None,
        "plan_id": None,
        "plan_digest": None,
        "source_identity_digest": None,
        "source_revision": None,
        "lexical_chunk_count": None,
        "vector_chunk_count": None,
        "vector_lexical_parity": "unproven",
        "qdrant_collection": None,
        "issues": [],
    }


def _active_health(
    data: Mapping[str, Any] | None,
    error: Mapping[str, Any] | None,
    *,
    strict_identity: bool,
) -> dict[str, Any]:
    result = _empty_active()
    if error is not None or data is None:
        result["status"] = "unavailable"
        result["issues"] = [
            str((error or {}).get("reason_code") or "INDEX_ACTIVE_EVIDENCE_UNAVAILABLE")
        ]
        return result

    vector_count = data.get("vector_chunk_count")
    lexical_count = data.get("lexical_chunk_count")
    vector_ids = data.get("vector_chunk_ids")
    lexical_ids = data.get("lexical_chunk_ids")
    issues: list[str] = []
    if strict_identity and (
        any(
            not data.get(field)
            for field in (
                "release_id",
                "production_manifest_key",
                "production_manifest_sha256",
                "source_revision",
                "qdrant_collection",
            )
        )
        or data.get("document_count") is None
    ):
        issues.append("INDEX_ACTIVE_IDENTITY_UNPROVEN")
    if vector_count is None or lexical_count is None:
        issues.append("INDEX_DUAL_STORE_COUNTS_UNPROVEN")
    elif vector_count != lexical_count:
        issues.append("INDEX_CHUNK_COUNT_MISMATCH")

    if vector_ids is not None and lexical_ids is not None:
        if set(vector_ids) != set(lexical_ids):
            issues.append("INDEX_ID_PARITY_MISMATCH")
    elif data.get("parity_basis") not in {"manifest_counts", "verified_readback"}:
        issues.append("INDEX_ID_PARITY_UNPROVEN")

    if any(issue.endswith("MISMATCH") for issue in issues):
        status = "degraded"
        parity = "mismatch"
    elif issues:
        status = "unknown"
        parity = "unproven"
    else:
        status = "healthy"
        parity = "proven"
    result.update(
        {
            "status": status,
            "release_id": data.get("release_id"),
            "manifest_key": data.get("production_manifest_key") or data.get("manifest_key"),
            "manifest_sha256": data.get("production_manifest_sha256")
            or data.get("manifest_sha256"),
            "source_identity_digest": data.get("source_identity_digest"),
            "source_revision": data.get("source_revision"),
            "document_count": data.get("document_count"),
            "lexical_chunk_count": lexical_count,
            "vector_chunk_count": vector_count,
            "vector_lexical_parity": parity,
            "qdrant_collection": data.get("qdrant_collection"),
            "issues": issues,
        }
    )
    return result


def _job_summary(job: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if job is None:
        return None
    return {
        key: job.get(key)
        for key in (
            "job_id",
            "operation_id",
            "status",
            "phase",
            "progress",
            "attempt",
            "plan_id",
            "plan_digest",
            "source_revision",
            "source_identity_digest",
            "candidate_release_id",
            "candidate_manifest_key",
            "candidate_manifest_sha256",
            "error_code",
            "created_at",
            "updated_at",
            "completed_at",
        )
    }


def _candidate_health(
    job: Mapping[str, Any] | None,
    manifest_evidence: Mapping[str, Any] | None,
    manifest_error: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result = _empty_candidate()
    if job is None:
        return result
    result.update(
        {
            "job_id": job.get("job_id"),
            "operation_id": job.get("operation_id"),
            "attempt": job.get("attempt"),
            "plan_id": job.get("plan_id"),
            "plan_digest": job.get("plan_digest"),
            "source_identity_digest": job.get("source_identity_digest"),
            "source_revision": job.get("source_revision"),
            "release_id": job.get("candidate_release_id"),
            "manifest_key": job.get("candidate_manifest_key"),
            "manifest_sha256": job.get("candidate_manifest_sha256"),
        }
    )
    status = str(job.get("status", "")).upper()
    if status in {"PENDING", "RUNNING"}:
        result["status"] = "building"
        return result
    if status == "FAILED":
        result["status"] = "failed"
        result["issues"] = [str(job.get("error_code") or "INDEX_CANDIDATE_JOB_FAILED")]
        return result
    if not job.get("candidate_release_id"):
        return _empty_candidate()
    if manifest_error is not None or manifest_evidence is None:
        result["status"] = "unknown"
        result["issues"] = [
            str((manifest_error or {}).get("reason_code") or "INDEX_CANDIDATE_MANIFEST_UNPROVEN")
        ]
        return result

    receipt = job.get("result") if isinstance(job.get("result"), Mapping) else {}
    manifest = (
        manifest_evidence.get("manifest")
        if isinstance(manifest_evidence.get("manifest"), Mapping)
        else {}
    )
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), Mapping) else {}
    receipt_lexical_count = receipt.get("lexical_document_count")
    manifest_lexical_count = counts.get("lexical_documents")
    lexical_count = receipt_lexical_count or manifest_lexical_count
    vector = receipt.get("vector") if isinstance(receipt.get("vector"), Mapping) else {}
    vector_count = vector.get("point_count")
    receipt_semantic_count = receipt.get("semantic_document_count")
    manifest_semantic_count = counts.get("semantic_documents")
    semantic_count = receipt_semantic_count or manifest_semantic_count
    detail = vector.get("detail") if isinstance(vector.get("detail"), Mapping) else {}
    issues: list[str] = []
    if (
        manifest_evidence.get("verified") is not True
        or manifest_evidence.get("manifest_key") != job.get("candidate_manifest_key")
        or manifest_evidence.get("manifest_sha256") != job.get("candidate_manifest_sha256")
        or receipt.get("schema_version") != "m26-ingestion-candidate-write-receipt/v1"
        or receipt.get("status") != "candidate_release_finalized"
        or receipt.get("manifest_key") != job.get("candidate_manifest_key")
        or receipt.get("manifest_sha256") != job.get("candidate_manifest_sha256")
        or manifest.get("schema_version") != "knowledge-engine-release/v1"
        or manifest.get("release_id") != job.get("candidate_release_id")
        or manifest.get("status") != "candidate"
    ):
        issues.append("INDEX_CANDIDATE_IDENTITY_MISMATCH")
    authority = receipt.get("authority") if isinstance(receipt.get("authority"), Mapping) else {}
    manifest_authority = (
        manifest.get("authority") if isinstance(manifest.get("authority"), Mapping) else {}
    )
    if (
        authority.get("candidate_only") is not True
        or authority.get("production_pointer_writes") != 0
        or manifest_authority.get("candidate_only") is not True
        or manifest_authority.get("production_pointer_authorized") is not False
    ):
        issues.append("INDEX_CANDIDATE_AUTHORITY_UNPROVEN")
    if lexical_count is None or semantic_count is None or vector_count is None:
        issues.append("INDEX_CANDIDATE_PARITY_UNPROVEN")
    elif (
        not (lexical_count == semantic_count == vector_count)
        or receipt_lexical_count != manifest_lexical_count
        or receipt_semantic_count != manifest_semantic_count
        or vector.get("section_id_count") != vector_count
        or detail.get("full_readback") is not True
    ):
        issues.append("INDEX_CANDIDATE_PARITY_MISMATCH")

    result.update(
        {
            "status": "ready" if not issues else "unknown",
            "lexical_chunk_count": lexical_count,
            "vector_chunk_count": vector_count,
            "vector_lexical_parity": "proven"
            if not issues
            else (
                "mismatch" if any(issue.endswith("MISMATCH") for issue in issues) else "unproven"
            ),
            "qdrant_collection": receipt.get("qdrant_collection")
            or manifest.get("qdrant_collection"),
            "issues": issues,
        }
    )
    return result


def _has_changes(diff: Mapping[str, Any] | None) -> bool:
    return bool(diff and any(diff.get(key) for key in ("added", "changed", "removed")))


def _source_health(
    source: Mapping[str, Any] | None,
    source_error: Mapping[str, Any] | None,
    active: Mapping[str, Any] | None,
    candidate: Mapping[str, Any],
    candidate_manifest: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], bool | None]:
    result: dict[str, Any] = {
        "status": "unknown",
        "source_revision": None,
        "source_identity_digest": None,
        "document_count": None,
        "diff_vs_active": None,
        "diff_vs_candidate": None,
        "requires_confirmation": False,
        "plan_digest_vs_active": None,
        "issues": [],
    }
    if source_error is not None or source is None:
        result["status"] = "unavailable"
        result["issues"] = [
            str((source_error or {}).get("reason_code") or "INDEX_SOURCE_EVIDENCE_UNAVAILABLE")
        ]
        return result, None
    documents = source.get("documents")
    if not isinstance(documents, Sequence) or isinstance(documents, (str, bytes)):
        result["issues"] = ["INDEX_SOURCE_EVIDENCE_INVALID"]
        return result, None
    result.update(
        {
            "source_revision": source.get("source_revision"),
            "source_identity_digest": source.get("source_identity_digest"),
            "document_count": len(documents),
        }
    )
    active_digests = active.get("document_digests") if isinstance(active, Mapping) else None
    if isinstance(active_digests, Mapping):
        plan = build_sync_plan(
            source_revision=str(source.get("source_revision") or "unknown"),
            documents=documents,
            active_document_digests=active_digests,
        )
        result["diff_vs_active"] = plan["plan"]["manifest_diff"]
        result["requires_confirmation"] = bool(plan["plan"]["requires_confirmation"])
        result["plan_digest_vs_active"] = plan["plan_digest"]
    else:
        result["issues"].append("INDEX_SOURCE_VS_ACTIVE_UNPROVEN")

    candidate_matches: bool | None = None
    if candidate.get("release_id"):
        current_digest = source.get("source_identity_digest")
        candidate_digest = candidate.get("source_identity_digest")
        if current_digest is not None and candidate_digest is not None:
            candidate_matches = current_digest == candidate_digest
        candidate_digests = (
            candidate_manifest.get("document_digests")
            if isinstance(candidate_manifest, Mapping)
            else None
        )
        if isinstance(candidate_digests, Mapping):
            result["diff_vs_candidate"] = build_manifest_diff(
                documents=documents,
                active_document_digests=candidate_digests,
            )
            candidate_matches = not _has_changes(result["diff_vs_candidate"])
        elif candidate_matches is None:
            result["issues"].append("INDEX_SOURCE_VS_CANDIDATE_UNPROVEN")
        if candidate_matches is False:
            result["issues"].append("INDEX_CANDIDATE_SOURCE_STALE")

    drifted = _has_changes(result["diff_vs_active"]) or candidate_matches is False
    if drifted:
        result["status"] = "drifted"
    elif result["issues"]:
        result["status"] = "unknown"
    else:
        result["status"] = "current"
    return result, candidate_matches


def build_index_health(observation: ReadObservation) -> ReadObservation:
    """Build the candidate-only v2 truth model without upgrading missing evidence."""

    evidence = dict(observation.data) if isinstance(observation.data, Mapping) else {}
    rich = evidence.get("schema_version") == "m26-index-health-evidence/v1"
    active_data = evidence.get("active") if rich else evidence or None
    active_error = evidence.get("active_error") if rich else None
    source_data = evidence.get("source") if rich else None
    source_error = evidence.get("source_error") if rich else None
    jobs = list(evidence.get("jobs", [])) if rich and isinstance(evidence.get("jobs"), list) else []
    candidate_job = evidence.get("candidate_job") if rich else None
    candidate_manifest = evidence.get("candidate_manifest") if rich else None
    candidate_error = evidence.get("candidate_manifest_error") if rich else None
    missing_seams = sorted(str(item) for item in evidence.get("missing_seams", [])) if rich else []

    active = _active_health(
        active_data if isinstance(active_data, Mapping) else None,
        active_error if isinstance(active_error, Mapping) else None,
        strict_identity=rich,
    )
    candidate = _candidate_health(
        candidate_job if isinstance(candidate_job, Mapping) else None,
        candidate_manifest if isinstance(candidate_manifest, Mapping) else None,
        candidate_error if isinstance(candidate_error, Mapping) else None,
    )
    source, candidate_matches = _source_health(
        source_data if isinstance(source_data, Mapping) else None,
        source_error if isinstance(source_error, Mapping) else None,
        active_data if isinstance(active_data, Mapping) else None,
        candidate,
        candidate_manifest if isinstance(candidate_manifest, Mapping) else None,
    )
    running = [
        _job_summary(job)
        for job in jobs
        if str(job.get("status", "")).upper() in {"PENDING", "RUNNING"}
    ]
    last_successful = next(
        (_job_summary(job) for job in jobs if str(job.get("status", "")).upper() == "SUCCEEDED"),
        None,
    )
    last_failed = next(
        (_job_summary(job) for job in jobs if str(job.get("status", "")).upper() == "FAILED"),
        None,
    )
    retryable_failed_count = sum(
        1 for job in jobs if str(job.get("status", "")).upper() == "FAILED"
    )

    blockers = list(candidate["issues"])
    if missing_seams:
        blockers.extend("INDEX_RUNTIME_SEAM_UNQUALIFIED:" + seam for seam in missing_seams)
    if active["status"] != "healthy":
        blockers.append("INDEX_ACTIVE_PRODUCTION_NOT_HEALTHY")
    if candidate_matches is False:
        blockers.append("INDEX_CANDIDATE_SOURCE_STALE")
    if candidate["status"] == "ready" and candidate_matches is True and not blockers:
        readiness = "ready_for_review"
    elif candidate["status"] in {"absent", "building", "failed"}:
        readiness = "not_ready"
    elif candidate["status"] == "unknown" or blockers:
        readiness = "blocked"
    else:
        readiness = "unknown"

    issues = sorted(
        set(
            active["issues"]
            + candidate["issues"]
            + source["issues"]
            + ["INDEX_RUNTIME_SEAM_UNQUALIFIED:" + seam for seam in missing_seams]
        )
    )
    if active["status"] == "unavailable" or source["status"] == "unavailable":
        overall = "unavailable"
    elif (
        active["status"] == "degraded"
        or source["status"] == "drifted"
        or candidate["status"] in {"building", "failed"}
    ):
        overall = "degraded"
    elif (
        active["status"] == "unknown"
        or source["status"] == "unknown"
        or candidate["status"] == "unknown"
    ):
        overall = "unknown"
    elif missing_seams:
        overall = "degraded"
    else:
        overall = "healthy"

    health = {
        "schema_version": "m26-index-health/v2",
        "mode": "candidate_only",
        "overall_status": overall,
        "active_production_index": active,
        "candidate_index": candidate,
        "source_state": source,
        "jobs": {
            "running": running,
            "last_successful": last_successful,
            "last_failed": last_failed,
            "retryable_failed_count": retryable_failed_count,
        },
        "promotion_readiness": {
            "status": readiness,
            "candidate_only": True,
            "active_pointer_authorized": False,
            "blockers": sorted(set(blockers)),
        },
        "issues": issues if rich else active["issues"],
        # Temporary compatibility aliases for existing backend callers. The v2
        # sections above are authoritative and these never add authority.
        "status": active["status"],
        "vector_lexical_parity": active["vector_lexical_parity"] == "proven",
    }
    return ReadObservation(
        availability=observation.availability,
        data=health,
        source=observation.source,
        observed_at=observation.observed_at or utc_now(),
        freshness=observation.freshness,
        reason_code=observation.reason_code,
        detail=observation.detail,
        resource_identity=observation.resource_identity,
        evidence_digest=hashlib.sha256(canonical_json_bytes(health)).hexdigest(),
    )


def require_sync_adapter(adapter: Any) -> Any:
    method = getattr(adapter, "sync_blog", None)
    if not callable(method):
        raise AdminAPIError(
            status_code=503,
            code=str(
                getattr(
                    adapter,
                    "reason_code",
                    "ADMIN_INGESTION_SYNC_ADAPTER_UNQUALIFIED",
                )
            ),
            message="The one-click blog sync actuator is not qualified",
        )
    return method


class DeterministicSyncIngestionAdapter:
    """Test/reference one-click adapter. Never installed by production."""

    def __init__(
        self,
        *,
        source_revision: str,
        documents: Sequence[Mapping[str, Any]],
        active_document_digests: Mapping[str, str] | None = None,
        vector_chunk_ids: Sequence[str] | None = None,
        lexical_chunk_ids: Sequence[str] | None = None,
    ) -> None:
        self.source_revision = source_revision
        self.documents = tuple(dict(item) for item in documents)
        self.active_document_digests = dict(active_document_digests or {})
        self.vector_chunk_ids = list(vector_chunk_ids or [])
        self.lexical_chunk_ids = list(lexical_chunk_ids or [])
        self.jobs: list[dict[str, Any]] = []

    def current_index(self) -> ReadObservation:
        data = {
            "source_revision": self.source_revision,
            "document_count": len(self.active_document_digests),
            "vector_chunk_count": len(self.vector_chunk_ids),
            "lexical_chunk_count": len(self.lexical_chunk_ids),
            "vector_chunk_ids": list(self.vector_chunk_ids),
            "lexical_chunk_ids": list(self.lexical_chunk_ids),
            "last_successful_sync": next(
                (job["observed_at"] for job in reversed(self.jobs) if job["status"] == "succeeded"),
                None,
            ),
        }
        return ReadObservation(
            availability="available",
            data=data,
            source="deterministic_sync_fixture",
            observed_at=utc_now(),
            freshness="snapshot",
            resource_identity={"source_revision": self.source_revision},
        )

    def sync_blog(self, operation_id: str, request: SyncBlogRequest) -> dict[str, Any]:
        # Rebuild from the currently observed source/index state on every call. A
        # destructive confirmation is therefore pinned to exactly the plan the
        # operator saw, rather than authorizing whatever plan happens to exist later.
        plan = build_sync_plan(
            source_revision=self.source_revision,
            documents=self.documents,
            active_document_digests=self.active_document_digests,
        )
        requires_confirmation = bool(plan["plan"]["requires_confirmation"])
        if requires_confirmation and not request.confirmation:
            raise AdminAPIError(
                status_code=409,
                code="ADMIN_INGESTION_DESTRUCTIVE_CONFIRMATION_REQUIRED",
                message="Removed or unpublished documents require explicit confirmation",
                details={
                    "plan_id": plan["plan_id"],
                    "plan_digest": plan["plan_digest"],
                    "manifest_diff": plan["plan"]["manifest_diff"],
                },
            )
        if requires_confirmation and not request.expected_plan_digest:
            raise AdminAPIError(
                status_code=409,
                code="ADMIN_INGESTION_PLAN_DIGEST_REQUIRED",
                message="Destructive confirmation must reference the exact reviewed sync plan",
                details={
                    "plan_id": plan["plan_id"],
                    "plan_digest": plan["plan_digest"],
                    "manifest_diff": plan["plan"]["manifest_diff"],
                },
            )
        if requires_confirmation and request.expected_plan_digest != plan["plan_digest"]:
            raise AdminAPIError(
                status_code=409,
                code="ADMIN_INGESTION_STALE_PLAN",
                message="The blog or active index changed after confirmation was requested",
                details={
                    "expected_plan_digest": request.expected_plan_digest,
                    "current_plan_id": plan["plan_id"],
                    "current_plan_digest": plan["plan_digest"],
                    "manifest_diff": plan["plan"]["manifest_diff"],
                },
            )

        source_now = {str(item["document_id"]): str(item["digest"]) for item in self.documents}
        self.active_document_digests = source_now
        job = {
            "operation_id": operation_id,
            "job_id": "syncjob_" + operation_id.removeprefix("admop_"),
            "kind": "blog_sync",
            "status": "succeeded",
            "source_revision": self.source_revision,
            "plan_id": plan["plan_id"],
            "plan_digest": plan["plan_digest"],
            "manifest_diff": plan["plan"]["manifest_diff"],
            "verification": {
                "vector_chunk_count": len(self.vector_chunk_ids),
                "lexical_chunk_count": len(self.lexical_chunk_ids),
                "id_parity": set(self.vector_chunk_ids) == set(self.lexical_chunk_ids),
            },
            "observed_at": utc_now(),
            "production_write_attempts": 0,
        }
        self.jobs.append(job)
        return job


__all__ = [
    "DeterministicSyncIngestionAdapter",
    "SyncBlogRequest",
    "build_index_health",
    "build_manifest_diff",
    "build_sync_plan",
    "require_sync_adapter",
]
