from __future__ import annotations

from types import SimpleNamespace

from knowledge_engine import api


class _ReadyRuntime:
    channel = "production"

    def __init__(self) -> None:
        self.loaded = False

    def ensure_loaded(self):
        self.loaded = True
        return SimpleNamespace(release_id="release-20260702")


class _StartingRuntime:
    channel = "production"

    def ensure_loaded(self):
        raise FileNotFoundError("channels/production.json")


def test_health_loads_release_before_reporting_healthy(monkeypatch) -> None:
    runtime = _ReadyRuntime()
    monkeypatch.setattr(api, "get_runtime", lambda: runtime)

    response = api.health()

    assert runtime.loaded is True
    assert response == {
        "status": "healthy",
        "release_id": "release-20260702",
        "channel": "production",
    }


def test_health_reports_starting_when_release_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_runtime", lambda: _StartingRuntime())

    assert api.health() == {
        "status": "starting",
        "release_id": None,
        "channel": "production",
    }
