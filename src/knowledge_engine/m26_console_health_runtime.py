from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .m26_runtime_read_cache import materialized_cache_path, schedule_runtime_refresh

_ACTIVE_REFRESH_SECONDS = 60.0


def _iso_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def _active_cache_snapshot() -> tuple[dict[str, Any], float, float] | None:
    path = materialized_cache_path("active")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None
    if not isinstance(body, Mapping) or body.get("role") != "active":
        return None
    payload = body.get("payload")
    cached_at = body.get("cached_at_epoch")
    if not isinstance(payload, Mapping) or not isinstance(cached_at, (int, float)):
        return None
    age = max(0.0, time.time() - float(cached_at))
    if age > _ACTIVE_REFRESH_SECONDS:
        schedule_runtime_refresh("active")
    return dict(payload), float(cached_at), age


def _freshness(age_seconds: float) -> str:
    if age_seconds <= _ACTIVE_REFRESH_SECONDS:
        return "near_live"
    return "stale"


def _base(
    *,
    status: str,
    source: str,
    observed_at: str,
    freshness: str,
    detail: str,
    expected: Any = None,
    observed: Any = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "source": source,
        "observed_at": observed_at,
        "freshness": freshness,
        "latency_ms": 0,
        "detail": detail,
        "expected": expected,
        "observed": observed,
    }


class MaterializedConsoleHealthObserver:
    """Health evidence derived only from already-materialized local runtime state."""

    def _active_rows(self) -> dict[str, Any]:
        snapshot = _active_cache_snapshot()
        if snapshot is None:
            return {}
        payload, cached_at, age = snapshot
        observed_at = _iso_from_epoch(cached_at)
        freshness = _freshness(age)
        release_id = str(payload.get("release_id") or "").strip() or None
        manifest_sha = str(payload.get("production_manifest_sha256") or "").strip() or None
        pointer_sha = str(payload.get("pointer_sha256") or "").strip() or None
        collection = str(payload.get("qdrant_collection") or "").strip() or None
        lexical = payload.get("lexical_chunk_count")
        vector = payload.get("vector_chunk_count")
        document_count = payload.get("document_count")

        rows: dict[str, Any] = {}
        if release_id and (manifest_sha or pointer_sha):
            rows["production"] = _base(
                status="healthy",
                source="materialized_active_release_cache",
                observed_at=observed_at,
                freshness=freshness,
                detail=(
                    "Pointer-selected production identity read from the existing "
                    "materialized active-release cache; no synchronous object-store load ran."
                ),
                observed=pointer_sha or manifest_sha or release_id,
            )
        if manifest_sha:
            rows["r2"] = _base(
                status="healthy",
                source="materialized_active_release_cache",
                observed_at=observed_at,
                freshness=freshness,
                detail=(
                    "Production manifest identity is present in the existing active-release "
                    "cache; this is bounded read evidence, not a live R2 probe."
                ),
                observed=manifest_sha,
            )
        if collection and isinstance(lexical, int) and isinstance(vector, int):
            rows["qdrant"] = _base(
                status="healthy" if lexical == vector and vector > 0 else "warning",
                source="materialized_active_release_cache",
                observed_at=observed_at,
                freshness=freshness,
                detail=(
                    "Vector/lexical parity is projected from the active-release snapshot; "
                    "no live Qdrant count query ran in the Admin request."
                ),
                expected=lexical,
                observed=vector,
            )
        if release_id and isinstance(document_count, int):
            rows["metadata"] = _base(
                status="healthy",
                source="materialized_active_release_cache",
                observed_at=observed_at,
                freshness=freshness,
                detail="Active release/control-plane identity is materialized locally.",
                observed=f"{release_id}:{document_count}",
            )
        return rows

    def collect(self, request: Any) -> Mapping[str, Any]:
        del request
        rows = self._active_rows()
        configured = bool(
            os.environ.get("MINIMAX_API_KEY", "").strip()
            or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
        )
        if configured:
            now = _iso_from_epoch(time.time())
            rows["provider"] = _base(
                status="read_only",
                source="provider_configuration_presence",
                observed_at=now,
                freshness="live",
                detail=(
                    "A provider configuration is present. No live provider request was "
                    "made by System Health, so external reachability is not claimed."
                ),
                observed="configured",
            )
        return rows

    def production_observation(self) -> Mapping[str, Any] | None:
        return self._active_rows().get("production")

    def release_observation(self) -> Mapping[str, Any] | None:
        snapshot = _active_cache_snapshot()
        if snapshot is None:
            return None
        payload, cached_at, age = snapshot
        release_id = str(payload.get("release_id") or "").strip()
        if not release_id:
            return None
        return {
            "release_id": release_id,
            "manifest_sha256": str(payload.get("manifest_sha256") or "").strip() or None,
            "production_manifest_sha256": (
                str(payload.get("production_manifest_sha256") or "").strip() or None
            ),
            "production_pointer_sha256": (
                str(payload.get("pointer_sha256") or "").strip() or None
            ),
            "qdrant_collection": str(payload.get("qdrant_collection") or "").strip() or None,
            "document_count": payload.get("document_count"),
            "lexical_chunk_count": payload.get("lexical_chunk_count"),
            "vector_chunk_count": payload.get("vector_chunk_count"),
            "observed_at": _iso_from_epoch(cached_at),
            "freshness": _freshness(age),
            "source": "materialized_active_release_cache",
        }


def materialized_console_health_observer() -> MaterializedConsoleHealthObserver | None:
    if not os.getenv("CACHE_DIR", "").strip():
        return None
    return MaterializedConsoleHealthObserver()


__all__ = [
    "MaterializedConsoleHealthObserver",
    "materialized_console_health_observer",
]
