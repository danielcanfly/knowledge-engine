from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, Request

from .m26_admin_contract import AdminAPIError, new_request_id, redact

CONTRACT_VERSION = "1.1.0-gate-a-repair-a"
CORPUS_SOURCE = "corpus_reconciliation_read_model"
_ALLOWED_FRESHNESS = {"live", "near_live", "delayed", "snapshot", "stale", "unknown"}


class CorpusAdapter(Protocol):
    def read(self, *, task_id: str | None = None) -> Mapping[str, Any]: ...


class UnavailableCorpusAdapter:
    def read(self, *, task_id: str | None = None) -> Mapping[str, Any]:
        raise AdminAPIError(status_code=503, code="ADMIN_CORPUS_ADAPTER_UNAVAILABLE", message="Corpus reconciliation adapters are not configured", retryable=True, details={"availability": "unavailable", "task_id": task_id})


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _slug(source: Mapping[str, Any]) -> str:
    explicit = _text(source.get("slug"))
    if explicit:
        return explicit.casefold()
    leaf = (_text(source.get("source_path")) or "").rsplit("/", 1)[-1]
    return leaf.rsplit(".", 1)[0].casefold()


def _record(source: Mapping[str, Any] | None, artifact: Mapping[str, Any] | None, vector: Mapping[str, Any] | None, *, active_release_marker: str | None, duplicate_slug: bool = False) -> dict[str, Any]:
    source, artifact, vector = dict(source or {}), dict(artifact or {}), dict(vector or {})
    source_id = _text(source.get("source_id")) or _text(artifact.get("source_id")) or _text(vector.get("source_id")) or "unknown"
    artifact_markdown = _text(artifact.get("artifact_markdown"))
    embedding_text = _text(artifact.get("embedding_text"))
    manifest_record = _text(artifact.get("manifest_record"))
    vector_presence = bool(vector.get("vector_presence", False))
    row_release = _text(artifact.get("release_marker")) or _text(vector.get("release_marker"))
    missing: list[str] = []
    reasons: list[str] = []
    if not source: missing.append("source"); reasons.append("CORPUS_ORPHANED_ARTIFACT")
    if not artifact_markdown: missing.append("artifact_markdown"); reasons.append("CORPUS_MATERIALIZE_MARKDOWN_MISSING")
    if not embedding_text: missing.append("embedding_text"); reasons.append("CORPUS_MATERIALIZE_SEMANTIC_PAYLOAD_MISSING")
    if not manifest_record: missing.append("manifest_record"); reasons.append("CORPUS_MANIFEST_RECORD_MISSING")
    if not vector_presence: missing.append("vector"); reasons.append("CORPUS_VECTOR_MISSING")
    if duplicate_slug: reasons.append("CORPUS_DUPLICATE_SLUG")
    stale = False
    if active_release_marker and row_release and row_release != active_release_marker:
        stale = True; reasons.append("CORPUS_ACTIVE_RELEASE_MISMATCH")
    if source and artifact and _text(source.get("source_revision")) and _text(artifact.get("source_revision")) and _text(source.get("source_revision")) != _text(artifact.get("source_revision")):
        stale = True; reasons.append("CORPUS_SOURCE_REVISION_MISMATCH")
    return {
        "source_id": source_id,
        "source_path": _text(source.get("source_path")) or _text(artifact.get("source_path")) or "<source unavailable>",
        "canonical_url": _text(source.get("canonical_url")) or _text(artifact.get("canonical_url")) or "",
        "source_revision": _text(source.get("source_revision")),
        "artifact_markdown": artifact_markdown,
        "embedding_text": embedding_text,
        "metadata_json": artifact.get("metadata_json") if isinstance(artifact.get("metadata_json"), Mapping) else None,
        "manifest_record": manifest_record,
        "vector_backend": _text(vector.get("vector_backend")),
        "vector_presence": vector_presence,
        "active_release_marker": active_release_marker,
        "materialized_at": _text(artifact.get("materialized_at")),
        "indexed_at": _text(vector.get("indexed_at")),
        "missing": missing, "stale": stale, "reasons": reasons,
    }


def reconcile_corpus(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources = [dict(x) for x in snapshot.get("sources", []) if isinstance(x, Mapping)]
    artifacts = [dict(x) for x in snapshot.get("artifacts", []) if isinstance(x, Mapping)]
    vectors = [dict(x) for x in snapshot.get("vectors", []) if isinstance(x, Mapping)]
    active_release = _text(snapshot.get("active_release_marker"))
    source_by_id = {_text(x.get("source_id")): x for x in sources if _text(x.get("source_id"))}
    artifact_by_id = {_text(x.get("source_id")): x for x in artifacts if _text(x.get("source_id"))}
    vector_by_id = {_text(x.get("source_id")): x for x in vectors if _text(x.get("source_id"))}
    all_ids = list(dict.fromkeys([*source_by_id, *artifact_by_id, *vector_by_id]))
    slug_counts = Counter(_slug(x) for x in sources if _slug(x))
    rows = [_record(source_by_id.get(source_id), artifact_by_id.get(source_id), vector_by_id.get(source_id), active_release_marker=active_release, duplicate_slug=bool(source_by_id.get(source_id)) and slug_counts[_slug(source_by_id[source_id])] > 1) for source_id in all_ids]
    return sorted(rows, key=lambda row: (row["source_path"], row["source_id"]))


class CorpusReadService:
    def __init__(self, adapter: CorpusAdapter) -> None:
        self.adapter = adapter

    def read(self, *, task_id: str | None = None) -> tuple[Mapping[str, Any], list[dict[str, Any]]]:
        try:
            snapshot = self.adapter.read(task_id=task_id)
        except AdminAPIError:
            raise
        except Exception as exc:
            raise AdminAPIError(status_code=503, code="ADMIN_CORPUS_ADAPTER_FAILURE", message="Corpus reconciliation adapter failed", retryable=True, details={"availability": "unavailable"}) from exc
        if not isinstance(snapshot, Mapping):
            raise AdminAPIError(status_code=503, code="ADMIN_CORPUS_ADAPTER_MALFORMED", message="Corpus reconciliation adapter returned malformed data", retryable=True)
        return snapshot, reconcile_corpus(snapshot)


def install_admin_corpus(app: FastAPI, *, adapter: CorpusAdapter | None = None) -> FastAPI:
    service = CorpusReadService(adapter or UnavailableCorpusAdapter())
    app.state.admin_corpus_service = service
    router = APIRouter(prefix="/v1/admin", tags=["AdminCorpus"])

    @router.get("/corpus", operation_id="listCorpus")
    async def list_corpus(request: Request, task_id: str | None = None) -> dict[str, Any]:
        snapshot, rows = service.read(task_id=task_id)
        warnings = [str(x) for x in snapshot.get("warnings", []) if str(x).strip()]
        partial = bool(warnings) or any(row["missing"] or row["stale"] or row["reasons"] for row in rows)
        observed_at = _text(snapshot.get("observed_at"))
        freshness = _text(snapshot.get("freshness")) or "unknown"
        if freshness not in _ALLOWED_FRESHNESS: freshness = "unknown"
        request_id = getattr(request.state, "admin_request_id", None) or new_request_id()
        return {
            "request_id": request_id,
            "availability": {"status": "partial" if partial else "available", "reason_code": "CORPUS_PARTIAL_EVIDENCE" if partial else None, "detail": "; ".join(warnings) if warnings else None},
            "provenance": {"source": CORPUS_SOURCE, "resource_identity": {"task_id": task_id, "contract_version": CONTRACT_VERSION}, "evidence_digest": _text(snapshot.get("evidence_digest")), "source_observed_at": observed_at},
            "observed_at": observed_at,
            "freshness": freshness,
            "data": redact(rows),
        }

    app.include_router(router)
    return app


__all__ = ["CONTRACT_VERSION", "CorpusReadService", "UnavailableCorpusAdapter", "install_admin_corpus", "reconcile_corpus"]
