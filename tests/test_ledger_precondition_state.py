from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from knowledge_engine.ledger import build_production_ledger_comment


def _load_ledger_fixture_module() -> ModuleType:
    path = Path(__file__).with_name("test_ledger.py")
    spec = importlib.util.spec_from_file_location("ledger_fixture_module", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_ledger_accepts_previous_pointer_for_ready_to_promote(tmp_path: Path) -> None:
    fixture = _load_ledger_fixture_module()
    fixture._write_evidence(tmp_path)

    precondition = json.loads((tmp_path / "precondition.json").read_text())
    precondition["release_id"] = fixture.PREVIOUS_RELEASE_ID
    precondition["manifest_sha256"] = fixture.PREVIOUS_MANIFEST_SHA
    _write(tmp_path / "precondition.json", precondition)

    idempotency = json.loads(
        (tmp_path / "idempotency_observation.json").read_text()
    )
    idempotency["state"] = "ready_to_promote"
    idempotency["current"] = idempotency["expected_previous"]
    _write(tmp_path / "idempotency_observation.json", idempotency)

    comment = build_production_ledger_comment(
        evidence_dir=tmp_path,
        run_id="28847474378",
        run_url=(
            "https://github.com/danielcanfly/knowledge-engine/actions/runs/"
            "28847474378"
        ),
        workflow_name="M5 Production Promotion",
        event_name="workflow_dispatch",
        head_sha=fixture.CONTROL_PLANE_SHA,
    )

    assert "- Production precondition state: `ready_to_promote`" in comment
    assert f"- Release ID: `{fixture.RELEASE_ID}`" in comment
