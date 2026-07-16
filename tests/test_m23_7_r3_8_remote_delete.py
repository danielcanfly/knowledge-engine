from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scripts import m23_7_r3_8_remote_delete as subject
from scripts.m23_7_r3_8_remote_operator import canonical_sha256


def _authorization() -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": subject.AUTH_SCHEMA,
        "worker_name": "knowledge-engine-r3-8-29506217284",
        "observation_run_id": "29506217284",
        "recovery_run_id": "29513606007",
        "worker_version_ids": [
            "1e8ec806-4cf2-40d4-bdd0-578602493cc3",
            "56d7bac1-f169-411a-a8f1-e79c1c793664",
        ],
        "worker_deployment_ids": [
            "035ceb79-0c55-4e1f-aa51-13a41b81ab6d",
            "47749012-1242-48d3-a79e-d09d6308fcb5",
        ],
        "receipt_sha256": "1" * 64,
        "evidence_seal_sha256": "2" * 64,
        "independent_reconciliation_sha256": "3" * 64,
        "authority": {
            "diagnostic_worker_deletion_authorized": True,
            "production_mutation_authorized": False,
            "qdrant_mutation_authorized": False,
            "r2_mutation_authorized": False,
            "pointer_mutation_authorized": False,
            "source_mutation_authorized": False,
        },
    }
    value["authorization_sha256"] = canonical_sha256(value)
    return value


def _rewrite_digest(value: dict[str, Any]) -> None:
    unsigned = dict(value)
    unsigned.pop("authorization_sha256", None)
    value["authorization_sha256"] = canonical_sha256(unsigned)


def test_deletion_authorization_validates_full_identity_sets(tmp_path: Path) -> None:
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(_authorization()), encoding="utf-8")
    value = subject.validate_authorization(path)
    assert value["worker_name"] == "knowledge-engine-r3-8-29506217284"
    assert len(value["worker_version_ids"]) == 2
    assert len(value["worker_deployment_ids"]) == 2


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update(worker_name="knowledge-engine-m23-7-r3-8-latency"),
        lambda value: value["authority"].update(production_mutation_authorized=True),
        lambda value: value.update(receipt_sha256="bad"),
        lambda value: value.update(observation_run_id="run-1"),
        lambda value: value.update(extra_field=True),
        lambda value: value.update(worker_version_ids=[]),
        lambda value: value.update(worker_deployment_ids=[]),
        lambda value: value.update(worker_version_ids=["not-a-uuid"]),
        lambda value: value.update(worker_deployment_ids=["not-a-uuid"]),
        lambda value: value.update(
            worker_version_ids=[
                "56d7bac1-f169-411a-a8f1-e79c1c793664",
                "1e8ec806-4cf2-40d4-bdd0-578602493cc3",
            ]
        ),
        lambda value: value.update(
            worker_deployment_ids=[
                "035ceb79-0c55-4e1f-aa51-13a41b81ab6d",
                "035ceb79-0c55-4e1f-aa51-13a41b81ab6d",
            ]
        ),
        lambda value: value.update(authorization_sha256="0" * 64),
    ),
)
def test_deletion_authorization_rejects_drift(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    value = _authorization()
    mutation(value)
    if value.get("authorization_sha256") != "0" * 64:
        _rewrite_digest(value)
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(subject.RemoteOperatorError):
        subject.validate_authorization(path)


def test_delete_command_uses_positional_worker_name(tmp_path: Path) -> None:
    worker = "knowledge-engine-r3-8-29506217284"
    config = tmp_path / f"wrangler.delete.{worker}.jsonc"
    command = subject.build_delete_command(worker, config)
    assert command == [
        "npx",
        "--yes",
        "wrangler@4.111.0",
        "delete",
        worker,
        "--config",
        str(config),
        "--force",
    ]
    assert "--name" not in command


def test_delete_command_rejects_unbounded_worker_name(tmp_path: Path) -> None:
    with pytest.raises(subject.RemoteOperatorError):
        subject.build_delete_command("knowledge-engine-r3-8-not-a-run", tmp_path / "x")


def test_execute_dispatches_positional_delete_and_proves_absence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_head = "5" * 40
    authorization = tmp_path / "authorization.json"
    authorization.write_text(json.dumps(_authorization()), encoding="utf-8")
    calls: list[list[str]] = []

    monkeypatch.setattr(
        subject.subprocess,
        "check_output",
        lambda *args, **kwargs: expected_head + "\n",
    )
    monkeypatch.setattr(
        subject,
        "required_env",
        lambda name: "https://qdrant.example" if name == "QDRANT_URL" else "secret",
    )
    monkeypatch.setattr(subject, "generate_wrangler_config", lambda *args, **kwargs: {})

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[3] == "delete":
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "Cloudflare error 10007")

    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    result = subject.execute(
        argparse.Namespace(
            confirmation="DELETE_RECONCILED_R3_8_WORKER",
            expected_head=expected_head,
            authorization_path=str(authorization),
            output_dir=str(tmp_path / "evidence"),
        )
    )
    assert result == 0
    assert calls[0][3:5] == ["delete", "knowledge-engine-r3-8-29506217284"]
    assert "--name" not in calls[0]
    assert calls[0][-1] == "--force"
    assert calls[1][3:6] == ["versions", "list", "--name"]
    receipt = json.loads(
        (tmp_path / "evidence" / "remote-deletion-receipt.json").read_text()
    )
    assert receipt["status"] == "diagnostic_worker_deleted_and_absence_proven"
    assert receipt["control_plane_absence_proven"] is True


def test_deletion_source_requires_full_identity_binding() -> None:
    text = Path("scripts/m23_7_r3_8_remote_delete.py").read_text(encoding="utf-8")
    assert "authorization_sha256" in text
    assert "independent_reconciliation_sha256" in text
    assert "worker_version_ids" in text
    assert "worker_deployment_ids" in text
    assert "DELETE_RECONCILED_R3_8_WORKER" in text
    assert "production_mutation_authorized" in text
    assert '"delete",\n        worker_name,' in text
    assert '["delete", "--name"' not in text
