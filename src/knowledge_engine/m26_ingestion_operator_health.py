from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .m26_admin_ingestion_core import ReadObservation
from .m26_admin_ingestion_sync import build_index_health


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def build_operator_index_health(observation: ReadObservation) -> ReadObservation:
    """Project read-only production audit evidence into the v2 operator contract.

    The existing health builder remains authoritative for active/candidate/source
    identity, job state, drift, and promotion/finalization safety. This adapter
    only adds Product Contract v2 health facts that were proved by the read-only
    production bundle/Qdrant/retrieval audit attached to the active observation.
    """

    built = build_index_health(observation)
    health = dict(built.data) if isinstance(built.data, Mapping) else {}
    evidence = dict(observation.data) if isinstance(observation.data, Mapping) else {}
    active_raw = evidence.get("active")
    audit = active_raw.get("health_audit") if isinstance(active_raw, Mapping) else None
    active = health.get("active_production_index")
    source = health.get("source_state")

    if isinstance(active, Mapping):
        active_view = dict(active)
        health["active_production_index"] = active_view
    else:
        active_view = None
    if isinstance(source, Mapping):
        source_view = dict(source)
        health["source_state"] = source_view
    else:
        source_view = None

    if source_view is not None:
        diff = source_view.get("diff_vs_active")
        if isinstance(diff, Mapping):
            added = diff.get("added")
            changed = diff.get("changed")
            source_view["missing_articles"] = len(added) if isinstance(added, list) else None
            source_view["stale_sources"] = len(changed) if isinstance(changed, list) else None

    audit_issues: list[str] = []
    if isinstance(audit, Mapping) and active_view is not None:
        for key in (
            "orphan_chunks",
            "duplicate_chunks",
            "malformed_metadata",
            "embedding_mismatch",
            "missing_vectors",
            "chunk_order_mismatch",
        ):
            active_view[key] = _count(audit.get(key))
        active_view["active_manifest_consistent"] = audit.get("active_manifest_consistent")
        active_view["retrieval_smoke"] = audit.get("retrieval_smoke")
        active_view["public_ask_successor_evidence"] = audit.get(
            "public_ask_successor_evidence"
        )
        audited_parity = audit.get("vector_lexical_parity")
        if audited_parity in {"proven", "mismatch", "unproven"}:
            active_view["vector_lexical_parity"] = audited_parity
        raw_issues = audit.get("issues")
        if isinstance(raw_issues, list):
            audit_issues = [str(item) for item in raw_issues if isinstance(item, str)]
        active_view["health_audit"] = dict(audit)
    elif active_view is not None:
        # Missing audit evidence is visible and fail-closed; it is never converted
        # into zero problem counts.
        for key in (
            "orphan_chunks",
            "duplicate_chunks",
            "malformed_metadata",
            "embedding_mismatch",
            "missing_vectors",
            "chunk_order_mismatch",
        ):
            active_view.setdefault(key, None)
        audit_issues = ["INDEX_HEALTH_AUDIT_EVIDENCE_UNAVAILABLE"]

    existing_issues = health.get("issues")
    health["issues"] = sorted(
        set(
            [str(item) for item in existing_issues if isinstance(item, str)]
            if isinstance(existing_issues, list)
            else []
        )
        | set(audit_issues)
    )
    if active_view is not None:
        active_issues = active_view.get("issues")
        active_view["issues"] = sorted(
            set(
                [str(item) for item in active_issues if isinstance(item, str)]
                if isinstance(active_issues, list)
                else []
            )
            | set(audit_issues)
        )
        if audit_issues and active_view.get("status") == "healthy":
            active_view["status"] = "unknown"

    if audit_issues and health.get("overall_status") == "healthy":
        health["overall_status"] = "unknown"

    return ReadObservation(
        availability=built.availability,
        data=health,
        source=built.source,
        observed_at=built.observed_at,
        freshness=built.freshness,
        reason_code=built.reason_code,
        detail=built.detail,
        resource_identity=built.resource_identity,
        evidence_digest=built.evidence_digest,
    )


__all__ = ["build_operator_index_health"]
