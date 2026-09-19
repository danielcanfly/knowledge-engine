from __future__ import annotations

import json
import time

from knowledge_engine import m26_ingestion_health_read as health_read


def _identity(release: str = "release-a") -> dict[str, str]:
    return {
        "release_id": release,
        "manifest_sha256": "a" * 64,
        "qdrant_collection": "collection-a",
    }


def _audit(release: str = "release-a") -> dict[str, object]:
    return {
        "schema_version": "m26-index-health-audit/v1",
        "status": "healthy",
        "release_id": release,
        "vector_lexical_parity": "proven",
        "issues": [],
    }


def test_matching_same_release_cache_is_used_without_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    health_read._write_cached_health_audit(_identity(), _audit())
    scheduled: list[dict[str, str]] = []
    monkeypatch.setattr(
        health_read,
        "_schedule_health_audit_refresh",
        lambda *, store, identity: scheduled.append(dict(identity)),
    )

    observed = health_read._cached_or_refreshing_health_audit(
        store=object(),
        active=_identity(),
    )

    assert observed["status"] == "healthy"
    assert observed["release_id"] == "release-a"
    assert scheduled == []


def test_cache_for_different_release_is_rejected_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    health_read._write_cached_health_audit(_identity("release-a"), _audit("release-a"))
    scheduled: list[dict[str, str]] = []
    monkeypatch.setattr(
        health_read,
        "_schedule_health_audit_refresh",
        lambda *, store, identity: scheduled.append(dict(identity)),
    )

    active = _identity("release-b")
    observed = health_read._cached_or_refreshing_health_audit(store=object(), active=active)

    assert observed["status"] == "unavailable"
    assert observed["reason_code"] == "INDEX_HEALTH_AUDIT_REFRESH_PENDING"
    assert observed["release_id"] == "release-b"
    assert scheduled == [active]


def test_stale_same_release_cache_is_served_while_single_refresh_is_scheduled(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    health_read._write_cached_health_audit(_identity(), _audit())
    cache_path = health_read._audit_cache_path()
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["cached_at_epoch"] = time.time() - health_read._AUDIT_CACHE_REFRESH_SECONDS - 1
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    scheduled: list[dict[str, str]] = []
    monkeypatch.setattr(
        health_read,
        "_schedule_health_audit_refresh",
        lambda *, store, identity: scheduled.append(dict(identity)),
    )

    observed = health_read._cached_or_refreshing_health_audit(
        store=object(),
        active=_identity(),
    )

    assert observed["status"] == "healthy"
    assert scheduled == [_identity()]


def test_mismatched_full_audit_is_never_written_to_active_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))

    health_read._write_cached_health_audit(_identity("release-a"), _audit("release-b"))

    assert not health_read._audit_cache_path().exists()


def test_cache_older_than_max_stale_window_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    health_read._write_cached_health_audit(_identity(), _audit())
    cache_path = health_read._audit_cache_path()
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["cached_at_epoch"] = time.time() - health_read._AUDIT_CACHE_MAX_STALE_SECONDS - 1
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    scheduled: list[dict[str, str]] = []
    monkeypatch.setattr(
        health_read,
        "_schedule_health_audit_refresh",
        lambda *, store, identity: scheduled.append(dict(identity)),
    )

    observed = health_read._cached_or_refreshing_health_audit(
        store=object(),
        active=_identity(),
    )

    assert observed["status"] == "unavailable"
    assert observed["reason_code"] == "INDEX_HEALTH_AUDIT_REFRESH_PENDING"
    assert scheduled == [_identity()]
