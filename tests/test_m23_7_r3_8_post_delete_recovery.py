from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import m23_7_r3_8_post_delete_recovery as subject


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode()

    def json(self) -> dict:
        return self._payload


class _Client:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, url: str) -> _Response:
        self.calls.append(url)
        return self.responses.pop(0)


def test_source_contains_no_destructive_cloudflare_call() -> None:
    text = Path(subject.__file__).read_text(encoding="utf-8")
    assert "client.get(" in text
    for forbidden in (
        "client.post(",
        "client.put(",
        "client.patch(",
        "client.delete(",
        "wrangler delete",
        "QDRANT_URL",
        "QDRANT_API_KEY",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    ):
        assert forbidden not in text


def test_execute_writes_absence_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = {
        "command_type": "r3_8_post_delete_recovery",
        "authorization_sha256": "a" * 64,
    }
    previous = {
        "authorization_sha256": "b" * 64,
        "worker_version_ids": ["v1", "v2"],
        "worker_deployment_ids": ["d1", "d2"],
    }
    monkeypatch.setattr(subject, "validate_authorization", lambda *a, **k: auth)
    monkeypatch.setattr(subject, "load_previous_authorization", lambda *a, **k: previous)
    monkeypatch.setattr(
        subject.subprocess,
        "check_output",
        lambda *a, **k: "c" * 40 + "\n",
    )
    monkeypatch.setattr(subject, "required_env", lambda name: name.lower())
    client = _Client(
        [
            _Response(200, {"success": True, "errors": [], "result": {"items": []}}),
            _Response(
                200,
                {"success": True, "errors": [], "result": {"deployments": []}},
            ),
        ]
    )
    monkeypatch.setattr(subject.httpx, "Client", lambda **kwargs: client)

    output = tmp_path / "evidence"
    args = SimpleNamespace(
        authorization_path="auth.json",
        expected_head="c" * 40,
        nonce="d" * 64,
        repo_root=str(tmp_path),
        output_dir=str(output),
    )
    assert subject.execute(args) == 0
    receipt = json.loads((output / "post-delete-recovery-receipt.json").read_text())
    assert receipt["worker_state"] == "worker_absent"
    assert receipt["control_plane_absence_proven"] is True
    assert receipt["destructive_deletion_replayed"] is False
    assert len(client.calls) == 2
    assert client.calls[0].endswith("/versions")
    assert client.calls[1].endswith("/deployments")


def test_main_persists_privacy_safe_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "execute",
        lambda args: (_ for _ in ()).throw(subject.PostDeleteRecoveryError("x")),
    )
    output = tmp_path / "failure"
    code = subject.main(
        [
            "--authorization-path",
            "a.json",
            "--expected-head",
            "e" * 40,
            "--nonce",
            "f" * 64,
            "--repo-root",
            str(tmp_path),
            "--output-dir",
            str(output),
        ]
    )
    assert code == 23
    payload = json.loads((output / "post-delete-recovery-failure.json").read_text())
    assert payload["failure_code"] == "x"
    assert payload["credentials_persisted"] is False
    assert payload["arbitrary_exception_text_persisted"] is False
