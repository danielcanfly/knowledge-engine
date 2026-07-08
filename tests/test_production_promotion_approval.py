from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.promotion_approval_history import (
    validate_historical_production_promotion_approval,
)

APPROVAL = Path(
    "governed_batches/evidence/m9-001-production-promotion-approval.json"
)
SPEC = Path("governed_batches/m9-001-agent-planning-strategies.json")
REQUEST = Path("production_promotions/m9-001-agent-planning-strategies.json")
APPROVAL_SHA256 = (
    "7eadff0fcda73c968982d6fc58bdaf4fc82a852f027ff4192730075f8c88b877"
)


def test_m9_production_promotion_approval_is_exact_and_consumed() -> None:
    result = validate_historical_production_promotion_approval(
        approval_path=APPROVAL,
        spec_path=SPEC,
        request_path=REQUEST,
    )

    assert result["status"] == "approved"
    assert result["batch_id"] == "m9-001-agent-planning-strategies"
    assert result["decision"] == "approve"
    assert result["authorized_by"] == "danielcanfly"
    assert result["authorized_at"] == "2026-07-08T04:52:50Z"
    assert result["approval_issue"] == 114
    assert result["approval_sha256"] == APPROVAL_SHA256
    assert result["operation_id"] == "m9-001-agent-planning-strategies-001"
    assert result["request_path"] == str(REQUEST)
    assert result["request_sha256"] == (
        "41564a42a3f207ea87bbc600935effbb9c3979c8366e16a4b1c7d1f35e172b5b"
    )
    assert result["target_release_id"] == "20260708T040116Z-69a9f445699a"
    assert result["target_manifest_sha256"] == (
        "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
    )
    assert result["expected_previous_release_id"] == (
        "20260707T111252Z-aebf06593f89"
    )
    assert result["expected_previous_manifest_sha256"] == (
        "1a2f2014073e9e97f9e1fdd5df4e43bf19cb2b2679532b6e52ea38480ec4d2ec"
    )
    assert result["expected_previous_pointer_sha256"] == (
        "2de63a9ff5963ea3f72f0051b25a084dda9e5e609fe79615e55e3f95a1351914"
    )
    assert result["production_dispatch_authorized"] is True
    assert result["production_mutated"] is False
    assert result["mutations_performed"] == []
    assert result["next_action"] == "dispatch_production_promotion"
    assert result["lifecycle_state_at_approval"] == "request_spec_committed"
    assert result["current_lifecycle_state"] == "closed"
    assert result["approval_consumed"] is True


def _validate_tampered(tmp_path: Path, payload: dict[str, object]) -> None:
    approval_path = Path("governed_batches/evidence") / (
        f".tmp-{tmp_path.name}-approval.json"
    )
    approval_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        validate_historical_production_promotion_approval(
            approval_path=approval_path,
            spec_path=SPEC,
            request_path=REQUEST,
        )
    finally:
        approval_path.unlink(missing_ok=True)


def test_approval_rejects_request_hash_tampering(tmp_path: Path) -> None:
    payload = json.loads(APPROVAL.read_text(encoding="utf-8"))
    payload["request"]["request_sha256"] = "0" * 64

    with pytest.raises(IntegrityError, match="request_sha256"):
        _validate_tampered(tmp_path, payload)


def test_approval_rejects_target_substitution(tmp_path: Path) -> None:
    payload = json.loads(APPROVAL.read_text(encoding="utf-8"))
    payload["target"]["release_id"] = "20260101T000000Z-000000000000"

    with pytest.raises(IntegrityError, match="target"):
        _validate_tampered(tmp_path, payload)


def test_approval_rejects_replay_or_rollback_authority(tmp_path: Path) -> None:
    payload = json.loads(APPROVAL.read_text(encoding="utf-8"))
    payload["authorization_scope"]["idempotent_replay_authorized"] = True
    payload["authorization_scope"]["rollback_authorized"] = True

    with pytest.raises(IntegrityError, match="authorization_scope"):
        _validate_tampered(tmp_path, payload)
