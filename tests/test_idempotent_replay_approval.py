from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.idempotent_replay_approval import (
    validate_idempotent_replay_approval,
)

APPROVAL = Path(
    "governed_batches/evidence/m9-001-idempotent-replay-approval.json"
)
SPEC = Path("governed_batches/m9-001-agent-planning-strategies.json")
REQUEST = Path("production_promotions/m9-001-agent-planning-strategies.json")
PROMOTION = Path(
    "governed_batches/evidence/m9-001-production-promotion-observation.json"
)
LIFECYCLE = Path("governed_batches/evidence/m9-001-lifecycle-history.json")


def _validate(approval_path: Path = APPROVAL) -> dict[str, object]:
    return validate_idempotent_replay_approval(
        approval_path=approval_path,
        spec_path=SPEC,
        request_path=REQUEST,
        promotion_observation_path=PROMOTION,
        lifecycle_path=LIFECYCLE,
    )


def test_m9_idempotent_replay_approval_is_exact_and_non_mutating() -> None:
    result = _validate()

    assert result["status"] == "approved"
    assert result["batch_id"] == "m9-001-agent-planning-strategies"
    assert result["decision"] == "approve"
    assert result["authorized_by"] == "danielcanfly"
    assert result["authorized_at"] == "2026-07-08T05:31:42Z"
    assert result["approval_issue"] == 119
    assert result["operation_id"] == "m9-001-agent-planning-strategies-001"
    assert result["request_path"] == str(REQUEST)
    assert result["request_sha256"] == (
        "41564a42a3f207ea87bbc600935effbb9c3979c8366e16a4b1c7d1f35e172b5b"
    )
    assert result["target_release_id"] == "20260708T040116Z-69a9f445699a"
    assert result["target_manifest_sha256"] == (
        "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
    )
    assert result["target_pointer_sha256"] == (
        "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
    )
    assert result["original_promotion_run"] == 28919098263
    assert result["original_promotion_artifact"] == 8158736427
    assert result["single_idempotent_replay_dispatch_authorized"] is True
    assert result["permanent_ledger_append_on_success_authorized"] is True
    assert result["closure_reconciliation_after_success_authorized"] is True
    assert result["rollback_authorized"] is False
    assert result["additional_replays_authorized"] is False
    assert result["replay_dispatched"] is False
    assert result["production_mutated"] is False
    assert result["permanent_ledger_appended"] is False
    assert result["mutations_performed"] == []
    assert result["next_action"] == "dispatch_idempotent_replay"


def _validate_tampered(tmp_path: Path, payload: dict[str, object]) -> None:
    approval_path = Path("governed_batches/evidence") / (
        f".tmp-{tmp_path.name}-replay-approval.json"
    )
    approval_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        _validate(approval_path)
    finally:
        approval_path.unlink(missing_ok=True)


def test_replay_approval_rejects_operation_replacement(tmp_path: Path) -> None:
    payload = json.loads(APPROVAL.read_text(encoding="utf-8"))
    payload["request"]["operation_id"] = "m9-replacement-operation"

    with pytest.raises(IntegrityError, match="operation_id"):
        _validate_tampered(tmp_path, payload)


def test_replay_approval_rejects_target_substitution(tmp_path: Path) -> None:
    payload = json.loads(APPROVAL.read_text(encoding="utf-8"))
    payload["current_production"]["release_id"] = (
        "20260101T000000Z-000000000000"
    )

    with pytest.raises(IntegrityError, match="current production"):
        _validate_tampered(tmp_path, payload)


def test_replay_approval_rejects_rollback_or_extra_replays(tmp_path: Path) -> None:
    payload = json.loads(APPROVAL.read_text(encoding="utf-8"))
    payload["authorization_scope"]["rollback_authorized"] = True
    payload["authorization_scope"]["additional_replays_authorized"] = True

    with pytest.raises(IntegrityError, match="authorization_scope"):
        _validate_tampered(tmp_path, payload)


def test_replay_approval_rejects_non_idempotent_expected_outcome(
    tmp_path: Path,
) -> None:
    payload = json.loads(APPROVAL.read_text(encoding="utf-8"))
    payload["required_replay_outcome"]["idempotent"] = False
    payload["required_replay_outcome"]["promotion_status"] = "promoted"

    with pytest.raises(IntegrityError, match="required_replay_outcome"):
        _validate_tampered(tmp_path, payload)
