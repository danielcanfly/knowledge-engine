from __future__ import annotations

import json
import time

import pytest

from knowledge_engine import m26_runtime_read_cache as read_cache


def _payload(role: str) -> dict[str, object]:
    if role == "source":
        return {
            "source_revision": "git:" + "a" * 40,
            "source_identity_digest": "b" * 64,
            "documents": [],
        }
    return {
        "release_id": "release-a",
        "manifest_sha256": "c" * 64,
        "qdrant_collection": "collection-a",
        "document_digests": {},
    }


def test_fresh_materialized_observer_never_schedules_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    read_cache.write_materialized_read_cache("source", _payload("source"))
    calls: list[str] = []
    monkeypatch.setattr(
        read_cache, "schedule_runtime_refresh", lambda role: calls.append(role) or True
    )

    observed = read_cache.materialized_runtime_observer("source")()

    assert observed["source_revision"] == "git:" + "a" * 40
    assert calls == []


def test_stale_materialized_observer_serves_cache_and_singleflight_refreshes(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    read_cache.write_materialized_read_cache("active", _payload("active"))
    path = read_cache.materialized_cache_path("active")
    body = json.loads(path.read_text(encoding="utf-8"))
    body["cached_at_epoch"] = time.time() - read_cache._REFRESH_SECONDS["active"] - 1
    path.write_text(json.dumps(body), encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        read_cache, "schedule_runtime_refresh", lambda role: calls.append(role) or True
    )

    observed = read_cache.materialized_runtime_observer("active")()

    assert observed["release_id"] == "release-a"
    assert calls == ["active"]


def test_missing_or_too_old_cache_returns_pending_without_running_live_observer(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    calls: list[str] = []
    monkeypatch.setattr(
        read_cache, "schedule_runtime_refresh", lambda role: calls.append(role) or True
    )

    with pytest.raises(read_cache.RuntimeReadRefreshPending):
        read_cache.materialized_runtime_observer("source")()

    assert calls == ["source"]


def test_schedule_is_singleflight_per_role(monkeypatch):
    started: list[str] = []

    class FakeThread:
        def __init__(self, *, target, args, daemon, name):
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name

        def start(self):
            started.append(self.args[0])

    monkeypatch.setattr(read_cache.threading, "Thread", FakeThread)
    read_cache._REFRESHING.clear()

    assert read_cache.schedule_runtime_refresh("health") is True
    assert read_cache.schedule_runtime_refresh("health") is False
    assert started == ["health"]
    read_cache._REFRESHING.clear()
