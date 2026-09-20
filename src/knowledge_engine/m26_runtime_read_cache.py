from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .m26_admin_contract import canonical_json_bytes

LOGGER = logging.getLogger(__name__)

_CACHE_SCHEMA = "m26-runtime-read-cache/v1"
_REFRESH_SECONDS = {"source": 5 * 60, "active": 60}
_REFRESH_TIMEOUT_SECONDS = {"source": 45, "active": 20, "health": 150}
_REFRESHING: set[str] = set()
_REFRESH_LOCK = threading.Lock()
_REFRESH_RUN_LOCK = threading.Lock()


class RuntimeReadRefreshPending(RuntimeError):
    pass


def _cache_root() -> Path:
    return Path(os.getenv("CACHE_DIR", ".artifacts/cache") or ".artifacts/cache").expanduser()


def materialized_cache_path(role: str) -> Path:
    if role not in {"source", "active"}:
        raise ValueError(f"unsupported materialized read role: {role}")
    return _cache_root() / f"m26-runtime-{role}-observation-v1.json"


def refresh_status_path(role: str) -> Path:
    return _cache_root() / f"m26-runtime-{role}-refresh-status-v1.json"


def write_materialized_read_cache(role: str, payload: Mapping[str, Any]) -> None:
    path = materialized_cache_path(role)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": _CACHE_SCHEMA,
        "role": role,
        "cached_at_epoch": time.time(),
        "payload": dict(payload),
    }
    staging = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    staging.write_bytes(canonical_json_bytes(body))
    os.replace(staging, path)


def _read_materialized_read_cache(role: str) -> tuple[dict[str, Any] | None, float | None]:
    path = materialized_cache_path(role)
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None, None
    if (
        not isinstance(body, Mapping)
        or body.get("schema_version") != _CACHE_SCHEMA
        or body.get("role") != role
    ):
        return None, None
    payload = body.get("payload")
    cached_at = body.get("cached_at_epoch")
    if not isinstance(payload, Mapping) or not isinstance(cached_at, (int, float)):
        return None, None
    return dict(payload), max(0.0, time.time() - float(cached_at))


def _write_refresh_status(
    role: str,
    *,
    status: str,
    reason: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    path = refresh_status_path(role)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": "m26-runtime-read-refresh-status/v1",
        "role": role,
        "status": status,
        "observed_at_epoch": time.time(),
        "reason": reason,
        "duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
    }
    staging = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    staging.write_bytes(canonical_json_bytes(body))
    os.replace(staging, path)


def _run_refresh(role: str) -> None:
    started = time.monotonic()
    try:
        with _REFRESH_RUN_LOCK:
            _write_refresh_status(role, status="running")
            try:
                completed = subprocess.run(
                    [sys.executable, "-m", "knowledge_engine.m26_runtime_read_worker", role],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=_REFRESH_TIMEOUT_SECONDS[role],
                    env=os.environ.copy(),
                )
            except subprocess.TimeoutExpired:
                duration = time.monotonic() - started
                _write_refresh_status(
                    role,
                    status="failed",
                    reason="RUNTIME_READ_REFRESH_TIMEOUT",
                    duration_seconds=duration,
                )
                LOGGER.error(
                    "runtime read refresh timed out role=%s duration=%.3fs", role, duration
                )
                return
            duration = time.monotonic() - started
            if completed.returncode != 0:
                detail = (
                    (completed.stderr or completed.stdout or "").strip().replace("\n", " ")[:500]
                )
                _write_refresh_status(
                    role,
                    status="failed",
                    reason=f"RUNTIME_READ_REFRESH_EXIT_{completed.returncode}:{detail}",
                    duration_seconds=duration,
                )
                LOGGER.error(
                    "runtime read refresh failed role=%s exit=%s duration=%.3fs detail=%s",
                    role,
                    completed.returncode,
                    duration,
                    detail,
                )
                return
            _write_refresh_status(role, status="succeeded", duration_seconds=duration)
            LOGGER.info("runtime read refresh succeeded role=%s duration=%.3fs", role, duration)
    except Exception:
        duration = time.monotonic() - started
        LOGGER.exception("runtime read refresh crashed role=%s duration=%.3fs", role, duration)
        try:
            _write_refresh_status(
                role,
                status="failed",
                reason="RUNTIME_READ_REFRESH_INTERNAL_ERROR",
                duration_seconds=duration,
            )
        except OSError:
            LOGGER.exception("runtime read refresh status write failed role=%s", role)
    finally:
        with _REFRESH_LOCK:
            _REFRESHING.discard(role)


def schedule_runtime_refresh(role: str) -> bool:
    if role not in _REFRESH_TIMEOUT_SECONDS:
        raise ValueError(f"unsupported runtime read refresh role: {role}")
    with _REFRESH_LOCK:
        if role in _REFRESHING:
            return False
        _REFRESHING.add(role)
    threading.Thread(
        target=_run_refresh,
        args=(role,),
        daemon=True,
        name=f"m26-runtime-read-refresh-{role}",
    ).start()
    return True


def materialized_runtime_observer(role: str):
    if role not in _REFRESH_SECONDS:
        raise ValueError(f"unsupported materialized observer role: {role}")

    def observe() -> Mapping[str, Any]:
        payload, age_seconds = _read_materialized_read_cache(role)
        if payload is not None and age_seconds is not None:
            if age_seconds <= _REFRESH_SECONDS[role]:
                return payload
            # A matching materialized snapshot remains safe read evidence even
            # when old. Serve it immediately and refresh in the background so an
            # idle operator page never turns a healthy production index into a
            # synthetic outage. Mutation/finalization authority still uses the
            # live observers, not this materialized read path.
            schedule_runtime_refresh(role)
            return payload
        schedule_runtime_refresh(role)
        raise RuntimeReadRefreshPending(f"M26_{role.upper()}_READ_REFRESH_PENDING")

    return observe


__all__ = [
    "RuntimeReadRefreshPending",
    "materialized_cache_path",
    "materialized_runtime_observer",
    "refresh_status_path",
    "schedule_runtime_refresh",
    "write_materialized_read_cache",
]
