from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from scripts import m23_7_r3_8_remote_entrypoint as subject


def _args(output_dir: Path) -> list[str]:
    return [
        "--expected-head",
        "a" * 40,
        "--run-id",
        "12345",
        "--run-attempt",
        "1",
        "--confirmation",
        "RUN_R3_8_REMOTE_ONCE",
        "--evidence-key",
        "diagnostic/m23-7/r3-8/evidence.zip",
        "--output-dir",
        str(output_dir),
    ]


def test_entrypoint_writes_evidence_before_operator(monkeypatch, tmp_path: Path) -> None:
    fake = types.SimpleNamespace(execute=lambda args: 0)
    monkeypatch.setitem(sys.modules, "scripts.m23_7_r3_8_remote_operator", fake)
    monkeypatch.setattr(
        subject.subprocess,
        "check_output",
        lambda *args, **kwargs: "a" * 40 + "\n",
    )
    assert subject.main(_args(tmp_path)) == 0
    entry = json.loads((tmp_path / "remote-entry.json").read_text(encoding="utf-8"))
    digest = entry.pop("entry_sha256")
    assert subject.canonical_sha256(entry) == digest
    assert entry["status"] == "operator_entry_started"
    assert entry["protected_mutations_dispatched"] is False


def test_entrypoint_converts_import_or_execution_failure_to_artifact(
    monkeypatch, tmp_path: Path
) -> None:
    def fail(args):
        raise RuntimeError("secret-shaped text must not be persisted")

    fake = types.SimpleNamespace(execute=fail)
    monkeypatch.setitem(sys.modules, "scripts.m23_7_r3_8_remote_operator", fake)
    monkeypatch.setattr(
        subject.subprocess,
        "check_output",
        lambda *args, **kwargs: "a" * 40 + "\n",
    )
    assert subject.main(_args(tmp_path)) == 23
    failure = json.loads(
        (tmp_path / "remote-entry-failure.json").read_text(encoding="utf-8")
    )
    assert failure["failure_code"] == "bounded_remote_entrypoint_failure"
    assert failure["arbitrary_exception_text_persisted"] is False
    assert "secret-shaped" not in json.dumps(failure)
    assert failure["worker_state_known"] is False
