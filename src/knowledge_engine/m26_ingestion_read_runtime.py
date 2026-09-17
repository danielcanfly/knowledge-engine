from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config import Settings
from .m25_blog_pilot import GitHubClient
from .m26_ingestion_health_read import enrich_active_observer_with_health
from .m26_ingestion_runtime import (
    SOURCE_REF,
    SOURCE_REF_ENV,
    SOURCE_REPOSITORY,
    SOURCE_REPOSITORY_ENV,
    SOURCE_ROOT_ENV,
    SOURCE_TOKEN_ENV,
    GitHubBlogSource,
    LocalBlogSource,
)
from .m26_sqlite_ingestion import (
    SQLiteIngestionAdapter,
    SQLiteIngestionReadAuthority,
    active_manifest_observer_from_store,
    candidate_manifest_observer_from_store,
)
from .storage import create_object_store


def _read_source_observer() -> tuple[Any | None, list[str]]:
    """Build the published-blog read observer without granting mutation authority."""

    source_root = os.getenv(SOURCE_ROOT_ENV, "").strip()
    if source_root:
        root = Path(source_root).expanduser()
        if root.is_dir():
            return LocalBlogSource(root).observe, []
        return None, [SOURCE_ROOT_ENV]

    repository = os.getenv(SOURCE_REPOSITORY_ENV, SOURCE_REPOSITORY).strip()
    ref = os.getenv(SOURCE_REF_ENV, SOURCE_REF).strip()
    if repository != SOURCE_REPOSITORY or ref != SOURCE_REF:
        return None, [SOURCE_REPOSITORY_ENV, SOURCE_REF_ENV]

    # The canonical blog repository is readable without a credential when public.
    # A configured token is used when present, but read truth must not depend on
    # production activation/write authority.
    token = os.getenv(SOURCE_TOKEN_ENV, "").strip() or None
    source = GitHubBlogSource(
        repository=repository,
        ref=ref,
        client=GitHubClient(token),
    )
    return source.observe, []


def _object_store() -> Any | None:
    try:
        return create_object_store(Settings.from_env())
    except Exception:
        return None


def _health_enriched_active(observer: Any, store: Any | None) -> Any:
    if not callable(observer) or store is None:
        return observer
    return enrich_active_observer_with_health(observer, store=store)


def enrich_read_authority_from_env(adapter: Any) -> Any:
    """Restore authoritative reads while preserving fail-closed mutations.

    Read evidence and mutation/finalization authority are deliberately separated.
    Missing write authority must never erase safe source/R2/Qdrant observations,
    while read-only enrichment must never create candidate executors, finalizers,
    write credentials, activation authority, or mutation capabilities.
    """

    if adapter is None:
        return None

    store = _object_store()

    # A fully qualified mutable adapter already owns the correct ingestion engine.
    # Only decorate its active observer with additional read-only health evidence.
    if isinstance(adapter, SQLiteIngestionAdapter):
        adapter.active_manifest_observer = _health_enriched_active(
            adapter.active_manifest_observer,
            store,
        )
        return adapter

    if not isinstance(adapter, SQLiteIngestionReadAuthority):
        return adapter

    source_observer = adapter.source_observer
    active_observer = adapter.active_manifest_observer
    candidate_observer = adapter.candidate_manifest_observer
    read_missing: list[str] = []

    if source_observer is None:
        source_observer, source_missing = _read_source_observer()
        read_missing.extend(source_missing)

    if active_observer is None or candidate_observer is None:
        if store is not None:
            if active_observer is None:
                active_observer = active_manifest_observer_from_store(store)
            if candidate_observer is None:
                candidate_observer = candidate_manifest_observer_from_store(store)
        else:
            read_missing.append("production_object_store_read")

    active_observer = _health_enriched_active(active_observer, store)

    if source_observer is None:
        read_missing.append("published_blog_read")
    if active_observer is None:
        read_missing.append("active_manifest_read")
    if candidate_observer is None:
        read_missing.append("candidate_manifest_read")

    return SQLiteIngestionReadAuthority(
        adapter.ledger,
        sorted(set(read_missing)),
        source_observer=source_observer,
        active_manifest_observer=active_observer,
        candidate_manifest_observer=candidate_observer,
        finalization_mode=adapter.finalization_mode,
    )


__all__ = ["enrich_read_authority_from_env"]
