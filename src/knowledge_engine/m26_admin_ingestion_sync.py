from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel

from .m26_admin_contract import AdminAPIError, canonical_json_bytes, utc_now
from .m26_admin_ingestion_core import ReadObservation


class SyncBlogRequest(BaseModel):
    """Operator intent for one-click blog synchronization.

    Add/change-only plans can execute without an extra product confirmation.
    A plan containing removals/unpublishes is destructive and must carry an
    explicit confirmation from the operator.
    """

    confirmation: bool = False


def build_manifest_diff(
    *,
    documents: Sequence[Mapping[str, Any]],
    active_document_digests: Mapping[str, str],
) -> dict[str, list[str]]:
    source = {str(item["document_id"]): str(item["digest"]) for item in documents}
    active = {str(key): str(value) for key, value in active_document_digests.items()}
    return {
        "added": sorted(set(source) - set(active)),
        "changed": sorted(key for key in source.keys() & active.keys() if source[key] != active[key]),
        "removed": sorted(set(active) - set(source)),
        "unchanged": sorted(key for key in source.keys() & active.keys() if source[key] == active[key]),
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


def build_index_health(observation: ReadObservation) -> ReadObservation:
    """Normalize index evidence without upgrading unknown evidence to healthy."""

    if observation.availability != "available" or not isinstance(observation.data, Mapping):
        return ReadObservation(
            availability=observation.availability,
            data={
                "status": "unavailable" if observation.availability == "unavailable" else "unknown",
                "issues": [observation.reason_code or "INDEX_EVIDENCE_UNAVAILABLE"],
            },
            source=observation.source,
            observed_at=observation.observed_at,
            freshness=observation.freshness,
            reason_code=observation.reason_code,
            detail=observation.detail,
            resource_identity=observation.resource_identity,
            evidence_digest=observation.evidence_digest,
        )

    data = dict(observation.data)
    vector_count = data.get("vector_chunk_count")
    lexical_count = data.get("lexical_chunk_count")
    vector_ids = data.get("vector_chunk_ids")
    lexical_ids = data.get("lexical_chunk_ids")
    issues: list[str] = []

    if vector_count is None or lexical_count is None:
        issues.append("INDEX_DUAL_STORE_COUNTS_UNPROVEN")
    elif vector_count != lexical_count:
        issues.append("INDEX_CHUNK_COUNT_MISMATCH")

    if vector_ids is None or lexical_ids is None:
        issues.append("INDEX_ID_PARITY_UNPROVEN")
    elif set(vector_ids) != set(lexical_ids):
        issues.append("INDEX_ID_PARITY_MISMATCH")

    status: Literal["healthy", "degraded", "unknown"]
    if issues:
        status = "unknown" if all(issue.endswith("UNPROVEN") for issue in issues) else "degraded"
    else:
        status = "healthy"

    health = {
        "status": status,
        "indexed_articles": data.get("document_count"),
        "vector_chunks": vector_count,
        "lexical_chunks": lexical_count,
        "vector_lexical_parity": not issues,
        "issues": issues,
        "source_revision": data.get("source_revision"),
        "last_successful_sync": data.get("last_successful_sync"),
        "last_audit": data.get("last_audit"),
    }
    return ReadObservation(
        availability="available",
        data=health,
        source=observation.source,
        observed_at=observation.observed_at or utc_now(),
        freshness=observation.freshness,
        resource_identity=observation.resource_identity,
        evidence_digest=hashlib.sha256(canonical_json_bytes(health)).hexdigest(),
    )


def require_sync_adapter(adapter: Any) -> Any:
    method = getattr(adapter, "sync_blog", None)
    if not callable(method):
        raise AdminAPIError(
            status_code=503,
            code="ADMIN_INGESTION_SYNC_ADAPTER_UNQUALIFIED",
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
        plan = build_sync_plan(
            source_revision=self.source_revision,
            documents=self.documents,
            active_document_digests=self.active_document_digests,
        )
        if plan["plan"]["requires_confirmation"] and not request.confirmation:
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
