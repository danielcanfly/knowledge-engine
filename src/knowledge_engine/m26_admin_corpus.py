from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, Query, Request

from .m26_admin_contract import AdminAPIError, canonical_json_bytes, new_request_id, redact
from .m26_production_answer_bundle import load_production_answer_bundle

CONTRACT_VERSION = "1.1.0-gate-a-repair-a"
CORPUS_SOURCE = "corpus_reconciliation_read_model"
_ALLOWED_FRESHNESS = {
    "live",
    "near_live",
    "delayed",
    "snapshot",
    "stale",
    "unknown",
}


class CorpusAdapter(Protocol):
    def read(self) -> Mapping[str, Any]: ...


class UnavailableCorpusAdapter:
    def read(self) -> Mapping[str, Any]:
        raise AdminAPIError(
            status_code=503,
            code="ADMIN_CORPUS_ADAPTER_UNAVAILABLE",
            message="Corpus reconciliation adapters are not configured",
            retryable=True,
            details={"availability": "unavailable"},
        )


class ObjectStoreCorpusAdapter:
    """Read a corpus view from the pointer-selected immutable release only."""

    def __init__(self, store: Any) -> None:
        self.store = store

    @staticmethod
    def _rows(value: Any, *keys: str) -> list[Mapping[str, Any]]:
        if not isinstance(value, Mapping):
            return []
        for key in keys:
            rows = value.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, Mapping)]
        return []

    @staticmethod
    def _source_id(row: Mapping[str, Any]) -> str | None:
        for key in ("source_id", "document_id", "id"):
            value = _text(row.get(key))
            if value:
                return value
        return None

    def read(self) -> Mapping[str, Any]:
        bundle = load_production_answer_bundle(store=self.store)
        active = bundle.active_release
        source_rows = self._rows(bundle.source_documents, "documents", "sources", "entries")
        if not source_rows:
            source_rows = self._rows(
                bundle.document_source_index,
                "entries",
                "sources",
                "documents",
                "rows",
            )
        lexical_rows = self._rows(bundle.lexical_index, "documents")
        semantic_rows = self._rows(bundle.semantic_inputs, "documents")
        provenance_rows = self._rows(bundle.provenance, "records")
        if semantic_rows and len(semantic_rows) != active.semantic_point_count:
            raise ValueError("active semantic artifact count does not match release authority")

        source_by_id = {
            source_id: dict(row)
            for row in source_rows
            if (source_id := self._source_id(row)) is not None
        }
        lexical_by_id: dict[str, list[Mapping[str, Any]]] = {}
        for row in lexical_rows:
            source_id = self._source_id(row)
            if source_id:
                lexical_by_id.setdefault(source_id, []).append(row)
        semantic_by_id: dict[str, list[Mapping[str, Any]]] = {}
        for row in semantic_rows:
            source_id = self._source_id(row)
            if source_id:
                semantic_by_id.setdefault(source_id, []).append(row)
        provenance_ids = {
            source_id
            for record in provenance_rows
            for source in self._rows(record, "sources")
            if (source_id := self._source_id(source)) is not None
        }
        source_ids = sorted(set(source_by_id) | set(lexical_by_id) | set(semantic_by_id))

        sources: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        vectors: list[dict[str, Any]] = []
        for source_id in source_ids:
            source = source_by_id.get(source_id, {})
            lexical = lexical_by_id.get(source_id, [])
            semantic = semantic_by_id.get(source_id, [])
            sources.append(
                {
                    "source_id": source_id,
                    "source_path": (
                        _text(source.get("origin_path"))
                        or _text(source.get("source_path"))
                        or _text(source.get("uri"))
                        or source_id
                    ),
                    "canonical_url": _text(source.get("canonical_url")) or "",
                    "language": _text(source.get("language")),
                    "source_revision": active.source_commit_sha,
                }
            )
            artifacts.append(
                {
                    "source_id": source_id,
                    "source_revision": active.source_commit_sha,
                    "artifact_markdown": (
                        bundle.artifact_keys.get("lexical_index") if lexical else None
                    ),
                    "embedding_text": (
                        bundle.artifact_keys.get("semantic_inputs") if semantic else None
                    ),
                    "manifest_record": (
                        bundle.artifact_keys.get("provenance")
                        if source_id in provenance_ids
                        else None
                    ),
                    "release_marker": active.release_id,
                    "metadata_json": {
                        "lexical_section_count": len(lexical),
                        "semantic_section_count": len(semantic),
                    },
                    "materialized_at": bundle.loaded_at,
                }
            )
            vectors.append(
                {
                    "source_id": source_id,
                    "vector_backend": "qdrant",
                    "vector_presence": bool(semantic),
                    "release_marker": active.release_id,
                    "indexed_at": bundle.loaded_at if semantic else None,
                }
            )

        identity = {
            "release_id": active.release_id,
            "production_manifest_sha256": active.production_manifest_sha256,
            "candidate_manifest_sha256": active.candidate_manifest_sha256,
            "qdrant_collection": active.qdrant_collection,
            "source_ids": source_ids,
        }
        return {
            "sources": sources,
            "artifacts": artifacts,
            "vectors": vectors,
            "active_release_marker": active.release_id,
            "warnings": [],
            "observed_at": bundle.loaded_at,
            "freshness": "snapshot",
            "evidence_digest": hashlib.sha256(canonical_json_bytes(identity)).hexdigest(),
        }


def object_store_corpus_adapter_from_env() -> ObjectStoreCorpusAdapter | None:
    try:
        from .config import Settings
        from .storage import create_object_store

        return ObjectStoreCorpusAdapter(create_object_store(Settings.from_env()))
    except Exception:
        return None


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


def _language(source: Mapping[str, Any], artifact: Mapping[str, Any]) -> str | None:
    direct = _text(source.get("language")) or _text(artifact.get("language"))
    if direct:
        return direct
    metadata = artifact.get("metadata_json")
    if isinstance(metadata, Mapping):
        return _text(metadata.get("language"))
    return None


def _record(
    source: Mapping[str, Any] | None,
    artifact: Mapping[str, Any] | None,
    vector: Mapping[str, Any] | None,
    *,
    active_release_marker: str | None,
    duplicate_slug: bool = False,
) -> dict[str, Any]:
    source = dict(source or {})
    artifact = dict(artifact or {})
    vector = dict(vector or {})

    source_id = (
        _text(source.get("source_id"))
        or _text(artifact.get("source_id"))
        or _text(vector.get("source_id"))
        or "unknown"
    )
    artifact_markdown = _text(artifact.get("artifact_markdown"))
    embedding_text = _text(artifact.get("embedding_text"))
    manifest_record = _text(artifact.get("manifest_record"))
    vector_presence = bool(vector.get("vector_presence", False))
    row_release = _text(artifact.get("release_marker")) or _text(vector.get("release_marker"))

    missing: list[str] = []
    reasons: list[str] = []

    if not source:
        missing.append("source")
        reasons.append("CORPUS_ORPHANED_ARTIFACT")
    if not artifact_markdown:
        missing.append("artifact_markdown")
        reasons.append("CORPUS_MATERIALIZE_MARKDOWN_MISSING")
    if not embedding_text:
        missing.append("embedding_text")
        reasons.append("CORPUS_MATERIALIZE_SEMANTIC_PAYLOAD_MISSING")
    if not manifest_record:
        missing.append("manifest_record")
        reasons.append("CORPUS_MANIFEST_RECORD_MISSING")
    if not vector_presence:
        missing.append("vector")
        reasons.append("CORPUS_VECTOR_MISSING")
    if duplicate_slug:
        reasons.append("CORPUS_DUPLICATE_SLUG")

    stale = False
    if active_release_marker and row_release and row_release != active_release_marker:
        stale = True
        reasons.append("CORPUS_ACTIVE_RELEASE_MISMATCH")

    source_revision = _text(source.get("source_revision"))
    artifact_revision = _text(artifact.get("source_revision"))
    if (
        source
        and artifact
        and source_revision
        and artifact_revision
        and source_revision != artifact_revision
    ):
        stale = True
        reasons.append("CORPUS_SOURCE_REVISION_MISMATCH")

    metadata_json = artifact.get("metadata_json")
    if not isinstance(metadata_json, Mapping):
        metadata_json = None

    return {
        "source_id": source_id,
        "source_path": (
            _text(source.get("source_path"))
            or _text(artifact.get("source_path"))
            or "<source unavailable>"
        ),
        "canonical_url": (
            _text(source.get("canonical_url")) or _text(artifact.get("canonical_url")) or ""
        ),
        "language": _language(source, artifact),
        "source_revision": source_revision,
        "artifact_markdown": artifact_markdown,
        "embedding_text": embedding_text,
        "metadata_json": metadata_json,
        "manifest_record": manifest_record,
        "vector_backend": _text(vector.get("vector_backend")),
        "vector_presence": vector_presence,
        "active_release_marker": active_release_marker,
        "materialized_at": _text(artifact.get("materialized_at")),
        "indexed_at": _text(vector.get("indexed_at")),
        "missing": missing,
        "stale": stale,
        "reasons": reasons,
    }


def reconcile_corpus(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources = [dict(item) for item in snapshot.get("sources", []) if isinstance(item, Mapping)]
    artifacts = [dict(item) for item in snapshot.get("artifacts", []) if isinstance(item, Mapping)]
    vectors = [dict(item) for item in snapshot.get("vectors", []) if isinstance(item, Mapping)]
    active_release = _text(snapshot.get("active_release_marker"))

    source_by_id = {
        _text(item.get("source_id")): item for item in sources if _text(item.get("source_id"))
    }
    artifact_by_id = {
        _text(item.get("source_id")): item for item in artifacts if _text(item.get("source_id"))
    }
    vector_by_id = {
        _text(item.get("source_id")): item for item in vectors if _text(item.get("source_id"))
    }
    all_ids = list(dict.fromkeys([*source_by_id, *artifact_by_id, *vector_by_id]))
    slug_counts = Counter(_slug(item) for item in sources if _slug(item))

    rows = []
    for source_id in all_ids:
        source = source_by_id.get(source_id)
        duplicate_slug = bool(source) and slug_counts[_slug(source)] > 1
        rows.append(
            _record(
                source,
                artifact_by_id.get(source_id),
                vector_by_id.get(source_id),
                active_release_marker=active_release,
                duplicate_slug=duplicate_slug,
            )
        )
    return sorted(rows, key=lambda row: (row["source_path"], row["source_id"]))


def _row_state(row: Mapping[str, Any]) -> str:
    reasons = row.get("reasons", [])
    if isinstance(reasons, list) and any("ORPHANED" in str(item) for item in reasons):
        return "orphaned"
    if bool(row.get("stale")):
        return "stale"
    if row.get("missing") or row.get("reasons"):
        return "partial"
    return "healthy"


def _filter_rows(
    rows: list[dict[str, Any]],
    *,
    q: str | None,
    state: str | None,
    language: str | None,
) -> list[dict[str, Any]]:
    query = _text(q)
    state_filter = _text(state)
    language_filter = _text(language)

    if query:
        needle = query.casefold()
        rows = [
            row
            for row in rows
            if any(
                needle in str(row.get(field) or "").casefold()
                for field in ("source_id", "source_path", "canonical_url")
            )
        ]
    if state_filter:
        wanted_state = state_filter.casefold()
        rows = [row for row in rows if _row_state(row) == wanted_state]
    if language_filter:
        wanted_language = language_filter.casefold()
        rows = [row for row in rows if str(row.get("language") or "").casefold() == wanted_language]
    return rows


class CorpusReadService:
    def __init__(self, adapter: CorpusAdapter) -> None:
        self.adapter = adapter

    def read(self) -> tuple[Mapping[str, Any], list[dict[str, Any]]]:
        try:
            snapshot = self.adapter.read()
        except AdminAPIError:
            raise
        except Exception as exc:
            raise AdminAPIError(
                status_code=503,
                code="ADMIN_CORPUS_ADAPTER_FAILURE",
                message="Corpus reconciliation adapter failed",
                retryable=True,
                details={"availability": "unavailable"},
            ) from exc

        if not isinstance(snapshot, Mapping):
            raise AdminAPIError(
                status_code=503,
                code="ADMIN_CORPUS_ADAPTER_MALFORMED",
                message="Corpus reconciliation adapter returned malformed data",
                retryable=True,
            )
        return snapshot, reconcile_corpus(snapshot)


def _availability(rows: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    partial = bool(warnings) or any(
        row["missing"] or row["stale"] or row["reasons"] for row in rows
    )
    return {
        "status": "partial" if partial else "available",
        "reason_code": "CORPUS_PARTIAL_EVIDENCE" if partial else None,
        "detail": "; ".join(warnings) if warnings else None,
    }


def _read_metadata(snapshot: Mapping[str, Any]) -> tuple[list[str], str | None, str]:
    warnings = [str(item) for item in snapshot.get("warnings", []) if str(item).strip()]
    observed_at = _text(snapshot.get("observed_at"))
    freshness = _text(snapshot.get("freshness")) or "unknown"
    if freshness not in _ALLOWED_FRESHNESS:
        freshness = "unknown"
    return warnings, observed_at, freshness


def _provenance(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": CORPUS_SOURCE,
        "resource_identity": {"contract_version": CONTRACT_VERSION},
        "evidence_digest": _text(snapshot.get("evidence_digest")),
        "source_observed_at": _text(snapshot.get("observed_at")),
    }


def install_admin_corpus(
    app: FastAPI,
    *,
    adapter: CorpusAdapter | None = None,
) -> FastAPI:
    service = CorpusReadService(adapter or UnavailableCorpusAdapter())
    app.state.admin_corpus_service = service
    router = APIRouter(prefix="/v1/admin", tags=["AdminCorpus"])

    @router.get("/corpus", operation_id="listCorpus")
    async def list_corpus(
        request: Request,
        q: str = Query(default=None, max_length=200),
        state: str = None,
        language: str = None,
    ) -> dict[str, Any]:
        snapshot, rows = service.read()
        rows = _filter_rows(rows, q=q, state=state, language=language)
        warnings, observed_at, freshness = _read_metadata(snapshot)
        request_id = getattr(request.state, "admin_request_id", None) or new_request_id()
        return {
            "request_id": request_id,
            "availability": _availability(rows, warnings),
            "provenance": _provenance(snapshot),
            "observed_at": observed_at,
            "freshness": freshness,
            "data": redact(rows),
        }

    @router.get("/corpus/{document_id}", operation_id="getCorpusDocument")
    async def get_corpus_document(
        request: Request,
        document_id: str,
    ) -> dict[str, Any]:
        snapshot, rows = service.read()
        warnings, observed_at, freshness = _read_metadata(snapshot)
        row = next((item for item in rows if item["source_id"] == document_id), None)
        request_id = getattr(request.state, "admin_request_id", None) or new_request_id()
        if row is None:
            availability = {
                "status": "unavailable",
                "reason_code": "CORPUS_DOCUMENT_NOT_OBSERVED",
                "detail": "No authoritative corpus observation exists for this document id",
            }
        else:
            availability = _availability([row], warnings)
        return {
            "request_id": request_id,
            "availability": availability,
            "provenance": _provenance(snapshot),
            "observed_at": observed_at,
            "freshness": freshness,
            "data": redact(row),
        }

    app.include_router(router)
    return app


__all__ = [
    "CONTRACT_VERSION",
    "CorpusReadService",
    "ObjectStoreCorpusAdapter",
    "UnavailableCorpusAdapter",
    "install_admin_corpus",
    "object_store_corpus_adapter_from_env",
    "reconcile_corpus",
]
