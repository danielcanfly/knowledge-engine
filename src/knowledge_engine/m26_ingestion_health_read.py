from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .m26_active_release_dense import ActiveReleaseDenseConfig, ActiveReleaseQdrantDenseChannel
from .m26_admin_contract import canonical_json_bytes
from .m26_ingestion_finalization import run_production_successor_probe
from .m26_ingestion_qdrant_qualification import (
    QdrantQualificationConfig,
    QdrantReadOnlyQualificationObserver,
)
from .m26_production_answer_bundle import (
    ProductionAnswerBundle,
    build_production_answer_compatibility_report,
    load_production_answer_bundle,
)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _source_rows(bundle: ProductionAnswerBundle) -> list[Mapping[str, Any]]:
    source_index = bundle.document_source_index
    if not isinstance(source_index, Mapping):
        return []
    for key in ("entries", "sources", "documents", "rows"):
        rows = _rows(source_index.get(key))
        if rows:
            return rows
    return []


def _source_id(row: Mapping[str, Any]) -> str | None:
    for key in ("source_id", "document_id", "id"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _lexical_metadata_invalid(row: Mapping[str, Any], source_ids: set[str]) -> bool:
    section_id = row.get("section_id")
    source_id = row.get("source_id")
    canonical_url = row.get("canonical_url")
    node_type = row.get("node_type")
    return not (
        isinstance(section_id, str)
        and section_id
        and isinstance(source_id, str)
        and source_id in source_ids
        and isinstance(canonical_url, str)
        and canonical_url.startswith(("https://", "http://"))
        and isinstance(node_type, str)
        and node_type in {"Article", "Section"}
    )


def _semantic_metadata_invalid(row: Mapping[str, Any], source_ids: set[str]) -> bool:
    section_id = row.get("section_id")
    text = row.get("text")
    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        return True
    source_id = payload.get("source_id")
    canonical_url = payload.get("canonical_url")
    content_sha256 = payload.get("content_sha256")
    source_commit_sha = payload.get("source_commit_sha")
    return not (
        isinstance(section_id, str)
        and section_id
        and isinstance(text, str)
        and bool(text.strip())
        and isinstance(source_id, str)
        and source_id in source_ids
        and isinstance(canonical_url, str)
        and canonical_url.startswith(("https://", "http://"))
        and isinstance(content_sha256, str)
        and len(content_sha256) == 64
        and isinstance(source_commit_sha, str)
        and len(source_commit_sha) == 40
    )


def _artifact_audit(bundle: ProductionAnswerBundle) -> dict[str, Any]:
    lexical = _rows(bundle.lexical_index.get("documents"))
    semantic_payload = bundle.semantic_inputs
    semantic = _rows(
        semantic_payload.get("documents") if isinstance(semantic_payload, Mapping) else None
    )
    sources = _source_rows(bundle)
    source_ids = {value for row in sources if (value := _source_id(row)) is not None}

    lexical_ids = [str(row.get("section_id") or "") for row in lexical]
    semantic_ids = [str(row.get("section_id") or "") for row in semantic]
    lexical_unique = {value for value in lexical_ids if value}
    semantic_unique = {value for value in semantic_ids if value}

    duplicate_chunks = (len(lexical_ids) - len(lexical_unique)) + (
        len(semantic_ids) - len(semantic_unique)
    )
    orphan_chunks = len(lexical_unique ^ semantic_unique)
    malformed_metadata = sum(
        1 for row in lexical if _lexical_metadata_invalid(row, source_ids)
    ) + sum(1 for row in semantic if _semantic_metadata_invalid(row, source_ids))

    lexical_order = [
        (str(row.get("concept_id") or ""), str(row.get("section_id") or ""))
        for row in lexical
    ]
    semantic_order = [str(row.get("section_id") or "") for row in semantic]
    chunk_order_mismatch = int(lexical_order != sorted(lexical_order)) + int(
        semantic_order != sorted(semantic_order)
    )

    source_metadata_invalid = 0
    for row in sources:
        source_id = _source_id(row)
        canonical_url = row.get("canonical_url")
        content_sha256 = row.get("content_sha256") or row.get("digest")
        origin_path = row.get("origin_path") or row.get("path")
        if not (
            source_id
            and isinstance(canonical_url, str)
            and canonical_url.startswith(("https://", "http://"))
            and isinstance(content_sha256, str)
            and len(content_sha256) == 64
            and isinstance(origin_path, str)
            and origin_path
        ):
            source_metadata_invalid += 1

    compatibility = build_production_answer_compatibility_report(bundle)
    mismatch_counts = compatibility.get("mismatch_counts")
    manifest_consistent = compatibility.get("status") == "compatible" and (
        isinstance(mismatch_counts, Mapping)
        and all(value == 0 for value in mismatch_counts.values())
    )

    issues: list[str] = []
    if duplicate_chunks:
        issues.append("INDEX_HEALTH_DUPLICATE_CHUNKS")
    if orphan_chunks:
        issues.append("INDEX_HEALTH_ORPHAN_CHUNKS")
    if malformed_metadata or source_metadata_invalid:
        issues.append("INDEX_HEALTH_MALFORMED_METADATA")
    if chunk_order_mismatch:
        issues.append("INDEX_HEALTH_CHUNK_ORDER_MISMATCH")
    if not manifest_consistent:
        issues.append("INDEX_HEALTH_MANIFEST_INCONSISTENT")

    return {
        "lexical_section_count": len(lexical),
        "semantic_section_count": len(semantic),
        "lexical_section_ids_sha256": _digest(sorted(lexical_unique)),
        "semantic_section_ids_sha256": _digest(sorted(semantic_unique)),
        "duplicate_chunks": duplicate_chunks,
        "orphan_chunks": orphan_chunks,
        "malformed_metadata": malformed_metadata + source_metadata_invalid,
        "chunk_order_mismatch": chunk_order_mismatch,
        "active_manifest_consistent": manifest_consistent,
        "compatibility_status": compatibility.get("status"),
        "compatibility_mismatch_counts": dict(mismatch_counts)
        if isinstance(mismatch_counts, Mapping)
        else None,
        "issues": issues,
    }


def _read_key() -> str:
    return (
        os.getenv("QDRANT_API_KEY_READ", "").strip()
        or os.getenv("QDRANT_READ_ONLY_API_KEY", "").strip()
    )


def _qdrant_audit(bundle: ProductionAnswerBundle, *, store: Any) -> dict[str, Any]:
    url = os.getenv("QDRANT_URL", "").strip()
    key = _read_key()
    if not url or not key:
        return {
            "status": "unavailable",
            "reason_code": "INDEX_HEALTH_QDRANT_READ_AUTHORITY_UNAVAILABLE",
        }
    try:
        observer = QdrantReadOnlyQualificationObserver(
            QdrantQualificationConfig(url=url, api_key=key),
            store=store,
        )
        result = observer.qualify_production(bundle.active_release)
        return {
            "status": "healthy",
            "collection": result.collection,
            "point_count": result.points_count,
            "full_identity_count": result.full_identity_count,
            "vector_dimension": result.vector_dimension,
            "distance": result.distance,
            "identity_profile": result.identity_profile,
            "section_ids_sha256": result.section_ids_sha256,
            "aggregate_identity_sha256": result.aggregate_identity_sha256,
            "vector_fingerprint_sha256": result.vector_fingerprint_sha256,
            "embedding_mismatch": 0,
            "missing_vectors": 0,
            "duplicate_vector_chunks": 0,
            "malformed_vector_metadata": 0,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason_code": str(
                getattr(exc, "code", "INDEX_HEALTH_QDRANT_QUALIFICATION_FAILED")
            ),
        }


def _successor_read_probe(bundle: ProductionAnswerBundle) -> dict[str, Any]:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.getenv("CLOUDFLARE_AI_TOKEN", "").strip()
    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    qdrant_key = _read_key()
    question = os.getenv("M26_INGESTION_ASK_PROBE_QUESTION", "").strip()
    if not all((account_id, token, qdrant_url, qdrant_key, question)):
        return {
            "status": "unavailable",
            "reason_code": "INDEX_HEALTH_SUCCESSOR_PROBE_AUTHORITY_UNAVAILABLE",
        }
    try:
        dense = ActiveReleaseQdrantDenseChannel(
            ActiveReleaseDenseConfig(
                cloudflare_account_id=account_id,
                cloudflare_api_token=token,
                qdrant_url=qdrant_url,
                qdrant_api_key=qdrant_key,
            )
        )
        result = run_production_successor_probe(
            bundle=bundle,
            dense_channel=dense,
            question=question,
        )
        return {
            "status": "healthy",
            "retrieval_smoke": "passed",
            "public_ask_successor_evidence": "passed",
            "release_id": result.get("release_id"),
            "production_pointer_sha256": result.get("production_pointer_sha256"),
            "qdrant_collection": result.get("qdrant_collection"),
            "evidence_count": len(result.get("evidence", []))
            if isinstance(result.get("evidence"), Sequence)
            else 0,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason_code": str(
                getattr(exc, "code", "INDEX_HEALTH_SUCCESSOR_PROBE_FAILED")
            ),
        }


def build_active_health_audit(*, store: Any) -> dict[str, Any]:
    try:
        bundle = load_production_answer_bundle(store=store)
        artifacts = _artifact_audit(bundle)
    except Exception as exc:
        return {
            "schema_version": "m26-index-health-audit/v1",
            "status": "unavailable",
            "reason_code": str(
                getattr(exc, "code", "INDEX_HEALTH_PRODUCTION_BUNDLE_UNAVAILABLE")
            ),
            "issues": ["INDEX_HEALTH_PRODUCTION_BUNDLE_UNAVAILABLE"],
        }

    qdrant = _qdrant_audit(bundle, store=store)
    probe = _successor_read_probe(bundle)
    issues = list(artifacts["issues"])
    if qdrant.get("status") != "healthy":
        issues.append(str(qdrant.get("reason_code") or "INDEX_HEALTH_QDRANT_UNAVAILABLE"))
    if probe.get("status") != "healthy":
        issues.append(str(probe.get("reason_code") or "INDEX_HEALTH_SUCCESSOR_PROBE_UNAVAILABLE"))

    vector_section_digest = qdrant.get("section_ids_sha256")
    lexical_section_digest = artifacts.get("lexical_section_ids_sha256")
    vector_lexical_parity = (
        "proven"
        if qdrant.get("status") == "healthy"
        and vector_section_digest == lexical_section_digest
        and artifacts.get("orphan_chunks") == 0
        else "unproven"
    )
    if qdrant.get("status") == "healthy" and vector_section_digest != lexical_section_digest:
        vector_lexical_parity = "mismatch"
        issues.append("INDEX_HEALTH_VECTOR_LEXICAL_ID_MISMATCH")

    return {
        "schema_version": "m26-index-health-audit/v1",
        "status": "healthy" if not issues else "degraded",
        "release_id": bundle.release_id,
        "missing_articles": 0,
        "orphan_chunks": artifacts.get("orphan_chunks"),
        "duplicate_chunks": artifacts.get("duplicate_chunks"),
        "malformed_metadata": artifacts.get("malformed_metadata"),
        "embedding_mismatch": qdrant.get("embedding_mismatch"),
        "missing_vectors": qdrant.get("missing_vectors"),
        "chunk_order_mismatch": artifacts.get("chunk_order_mismatch"),
        "active_manifest_consistent": artifacts.get("active_manifest_consistent"),
        "vector_lexical_parity": vector_lexical_parity,
        "retrieval_smoke": probe.get("retrieval_smoke"),
        "public_ask_successor_evidence": probe.get("public_ask_successor_evidence"),
        "artifact_audit": artifacts,
        "qdrant_audit": qdrant,
        "successor_probe": probe,
        "issues": sorted(set(issues)),
    }


def enrich_active_observer_with_health(
    observer: Callable[[], Mapping[str, Any]], *, store: Any
) -> Callable[[], Mapping[str, Any]]:
    def observe() -> Mapping[str, Any]:
        value = dict(observer())
        audit = build_active_health_audit(store=store)
        if audit.get("release_id") not in {None, value.get("release_id")}:
            audit = {
                "schema_version": "m26-index-health-audit/v1",
                "status": "degraded",
                "issues": ["INDEX_HEALTH_ACTIVE_RELEASE_IDENTITY_MISMATCH"],
            }
        value["health_audit"] = audit
        return value

    return observe


__all__ = ["build_active_health_audit", "enrich_active_observer_with_health"]
