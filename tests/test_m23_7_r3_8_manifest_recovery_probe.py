from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import m23_7_r3_8_manifest_recovery_probe as subject
from scripts.m23_7_r3_8_remote_operator import canonical_sha256
from scripts.m23_7_r3_8_run_authorization import (
    SCHEMA_VERSION,
    RunAuthorizationError,
    load_authorization,
)


def _authorization() -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "affected_run_id": "29696136508",
        "affected_engine_sha": "b57f0a05f6dca2d4030fdee354a478be6f295ff8",
        "worker_name": "knowledge-engine-r3-8-29696136508",
        "allowed_actions": ["recovery_probe"],
        "observation_artifact_sha256": "b" * 64,
        "expires_at": "2099-01-01T00:00:00Z",
        "production_mutation_authorized": False,
        "qdrant_mutation_authorized": False,
        "r2_mutation_authorized": False,
        "source_mutation_authorized": False,
        "blocker_clearance_authorized": False,
    }
    value["authorization_sha256"] = canonical_sha256(value)
    return value


def _write_authorization(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _rewrite_digest(value: dict[str, Any]) -> None:
    unsigned = dict(value)
    unsigned.pop("authorization_sha256", None)
    value["authorization_sha256"] = canonical_sha256(unsigned)


def test_manifest_authorization_validates_exact_identity(tmp_path: Path) -> None:
    path = tmp_path / "29696136508.json"
    _write_authorization(path, _authorization())
    value = load_authorization(
        path,
        requested_action="recovery_probe",
        actual_head="b57f0a05f6dca2d4030fdee354a478be6f295ff8",
    )
    assert value["affected_run_id"] == "29696136508"
    assert value["worker_name"] == "knowledge-engine-r3-8-29696136508"


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update(worker_name="knowledge-engine-r3-8-29696136509"),
        lambda value: value.update(affected_engine_sha="bad"),
        lambda value: value.update(affected_run_id="run-29696136508"),
        lambda value: value.update(observation_artifact_sha256="bad"),
        lambda value: value.update(allowed_actions=["delete_worker"]),
        lambda value: value.update(production_mutation_authorized=True),
        lambda value: value.update(qdrant_mutation_authorized=True),
        lambda value: value.update(r2_mutation_authorized=True),
        lambda value: value.update(source_mutation_authorized=True),
        lambda value: value.update(blocker_clearance_authorized=True),
        lambda value: value.update(extra=True),
        lambda value: value.update(authorization_sha256="0" * 64),
    ),
)
def test_manifest_authorization_rejects_drift(
    tmp_path: Path,
    mutation,
) -> None:
    value = _authorization()
    mutation(value)
    if value.get("authorization_sha256") != "0" * 64:
        _rewrite_digest(value)
    path = tmp_path / "29696136508.json"
    _write_authorization(path, value)
    with pytest.raises(RunAuthorizationError):
        load_authorization(
            path,
            requested_action="recovery_probe",
            actual_head="b57f0a05f6dca2d4030fdee354a478be6f295ff8",
        )


def test_generic_recovery_probe_reads_only_control_plane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "29696136508.json"
    _write_authorization(path, _authorization())
    calls: list[str] = []

    monkeypatch.setattr(
        subject.subprocess,
        "check_output",
        lambda *args, **kwargs: "b57f0a05f6dca2d4030fdee354a478be6f295ff8\n",
    )
    monkeypatch.setattr(subject, "required_env", lambda name: "secret")

    class FakeResponse:
        def __init__(self, payload: dict[str, Any]):
            self.status_code = 200
            self.content = json.dumps(payload).encode()

        def json(self) -> dict[str, Any]:
            return json.loads(self.content)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url: str) -> FakeResponse:
            calls.append(url)
            if url.endswith("/versions"):
                return FakeResponse(
                    {
                        "success": True,
                        "errors": [],
                        "result": {"items": [{"id": "v1"}]},
                    }
                )
            return FakeResponse(
                {
                    "success": True,
                    "errors": [],
                    "result": {"deployments": [{"id": "d1"}]},
                }
            )

    monkeypatch.setattr(subject.httpx, "Client", FakeClient)
    result = subject.execute(
        argparse.Namespace(
            authorization_path=str(path),
            confirmation=subject.CONFIRMATION,
            output_dir=str(tmp_path / "evidence"),
        )
    )
    assert result == 0
    assert len(calls) == 2
    assert calls[0].endswith("/versions")
    assert calls[1].endswith("/deployments")
    receipt = json.loads(
        (tmp_path / "evidence" / "generic-recovery-probe.json").read_text()
    )
    assert receipt["worker_state"] == "worker_present"
    assert receipt["worker_delete_dispatched"] is False
    assert receipt["qdrant_read_dispatched"] is False
    assert receipt["r2_read_dispatched"] is False


def test_generic_probe_source_has_no_run_specific_allowlist_or_mutations() -> None:
    source = Path("scripts/m23_7_r3_8_manifest_recovery_probe.py").read_text(
        encoding="utf-8"
    )
    assert "AUTHORIZED_RUNS" not in source
    assert "29696136508" not in source
    assert source.count("client.get(") == 2
    assert "client.post(" not in source
    assert "client.put(" not in source
    assert "client.patch(" not in source
    assert "client.delete(" not in source
