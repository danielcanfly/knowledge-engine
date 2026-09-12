from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from knowledge_engine import m26_ask_api as ask_api


def _runtime_response() -> dict[str, Any]:
    return {
        "schema_version": "test-runtime/v1",
        "status": "owner_only_safe_abstention",
        "terminal_status": "safe_abstention",
        "trace_id": "trace-test",
        "question_sha256": "a" * 64,
        "safe_abstention": True,
        "reason_codes": ["TEST"],
    }


def test_web_entry_constructs_active_release_dense_channel_when_not_injected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sentinel = object()
    observed: dict[str, Any] = {}

    def build_dense(*, require_remote: bool):
        observed["require_remote"] = require_remote
        return sentinel

    def run_runtime(**kwargs):
        observed["dense_channel"] = kwargs["dense_channel"]
        observed["runtime_require_remote"] = kwargs["require_remote_dense"]
        return _runtime_response()

    monkeypatch.setattr(
        ask_api,
        "active_release_dense_channel_from_env",
        build_dense,
    )
    monkeypatch.setattr(ask_api, "_should_use_default_provider_routing", lambda: False)
    monkeypatch.setattr(ask_api, "load_json", lambda _path: {})
    monkeypatch.setattr(ask_api, "run_owner_arbitrary_query", run_runtime)

    result = ask_api.run_owner_query_for_web(
        root=tmp_path,
        gate_path=tmp_path / "gate.json",
        request_payload={"question": "Which release is active?"},
        owner_subject_hash="owner",
        require_remote_dense=True,
    )

    assert observed == {
        "require_remote": True,
        "dense_channel": sentinel,
        "runtime_require_remote": True,
    }
    assert result["status"] == "owner_only_safe_abstention"


def test_explicit_dense_channel_is_preserved_without_env_authority_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sentinel = object()
    observed: dict[str, Any] = {}

    def forbidden_env_lookup(*, require_remote: bool):
        raise AssertionError(
            f"env dense lookup must not run for injected channel: {require_remote}"
        )

    def run_runtime(**kwargs):
        observed["dense_channel"] = kwargs["dense_channel"]
        return _runtime_response()

    monkeypatch.setattr(
        ask_api,
        "active_release_dense_channel_from_env",
        forbidden_env_lookup,
    )
    monkeypatch.setattr(ask_api, "_should_use_default_provider_routing", lambda: False)
    monkeypatch.setattr(ask_api, "load_json", lambda _path: {})
    monkeypatch.setattr(ask_api, "run_owner_arbitrary_query", run_runtime)

    ask_api.run_owner_query_for_web(
        root=tmp_path,
        gate_path=tmp_path / "gate.json",
        request_payload={"question": "Use my injected dense channel"},
        owner_subject_hash="owner",
        dense_channel=sentinel,
        require_remote_dense=True,
    )

    assert observed["dense_channel"] is sentinel
