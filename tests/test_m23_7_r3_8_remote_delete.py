from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scripts import m23_7_r3_8_remote_delete as subject
from scripts.m23_7_r3_8_remote_operator import canonical_sha256


def _authorization() -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": subject.AUTH_SCHEMA,
        "worker_name": "knowledge-engine-r3-8-29499115739",
        "worker_version_id": "version-123",
        "observation_run_id": "29499115739",
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


def test_deletion_authorization_validates(tmp_path: Path) -> None:
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(_authorization()), encoding="utf-8")
    value = subject.validate_authorization(path)
    assert value["worker_name"] == "knowledge-engine-r3-8-29499115739"


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update(worker_name="knowledge-engine-m23-7-r3-8-latency"),
        lambda value: value["authority"].update(production_mutation_authorized=True),
        lambda value: value.update(receipt_sha256="bad"),
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
        unsigned = dict(value)
        unsigned.pop("authorization_sha256", None)
        value["authorization_sha256"] = canonical_sha256(unsigned)
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(subject.RemoteOperatorError):
        subject.validate_authorization(path)


def test_deletion_source_requires_committed_authorization() -> None:
    text = Path("scripts/m23_7_r3_8_remote_delete.py").read_text(encoding="utf-8")
    assert "authorization_sha256" in text
    assert "independent_reconciliation_sha256" in text
    assert "DELETE_RECONCILED_R3_8_WORKER" in text
    assert "production_mutation_authorized" in text
