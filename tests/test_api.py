from __future__ import annotations

from types import SimpleNamespace

from knowledge_engine import api
from knowledge_engine.auth import Principal


class _ReadyRuntime:
    channel = "production"

    def __init__(self) -> None:
        self.loaded = False

    def ensure_loaded(self):
        self.loaded = True
        return SimpleNamespace(
            release_id="release-20260702",
            manifest_sha256="a" * 64,
        )


class _StartingRuntime:
    channel = "production"

    def ensure_loaded(self):
        raise FileNotFoundError("channels/production.json")


class _RefreshRuntime:
    channel = "production"

    def __init__(self) -> None:
        self.expected: tuple[str | None, str | None] | None = None

    def refresh(
        self,
        *,
        expected_release_id: str | None = None,
        expected_manifest_sha256: str | None = None,
    ):
        self.expected = (expected_release_id, expected_manifest_sha256)
        return SimpleNamespace(
            release_id=expected_release_id,
            manifest_sha256=expected_manifest_sha256,
            loaded_at="2026-07-03T08:00:00Z",
        )


def _internal_principal() -> Principal:
    return Principal(
        subject="release-controller",
        audiences=frozenset({"public", "internal"}),
        claims={},
    )


def test_health_loads_release_before_reporting_healthy(monkeypatch) -> None:
    runtime = _ReadyRuntime()
    monkeypatch.setattr(api, "get_runtime", lambda: runtime)

    response = api.health()

    assert runtime.loaded is True
    assert response == {
        "status": "healthy",
        "release_id": "release-20260702",
        "manifest_sha256": "a" * 64,
        "channel": "production",
    }


def test_health_reports_starting_when_release_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_runtime", lambda: _StartingRuntime())

    assert api.health() == {
        "status": "starting",
        "release_id": None,
        "channel": "production",
    }


def test_refresh_passes_expected_identity_to_runtime(monkeypatch) -> None:
    runtime = _RefreshRuntime()
    monkeypatch.setattr(api, "get_runtime", lambda: runtime)
    request = api.RefreshRequest(
        expected_release_id="20260703T080000Z-aaaaaaaaaaaa",
        expected_manifest_sha256="b" * 64,
    )

    response = api.refresh_release(request, _internal_principal())

    assert runtime.expected == (
        "20260703T080000Z-aaaaaaaaaaaa",
        "b" * 64,
    )
    assert response.model_dump() == {
        "release_id": "20260703T080000Z-aaaaaaaaaaaa",
        "manifest_sha256": "b" * 64,
        "loaded_at": "2026-07-03T08:00:00Z",
    }
