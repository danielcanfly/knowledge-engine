from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m25_review_surface import (
    ACTIONS,
    DecisionLedger,
    DecisionRequest,
    build_review_batch,
    create_review_app,
    load_json,
    validate_review_batch,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m25"
BATCH = load_json(PILOT / "m25-6-review-batch.json")
AUTH = ("browser-reviewer", "browser-acceptance-secret")


def _item(class_label: str, split: str = "final") -> dict:
    return next(
        value
        for value in BATCH["items"]
        if value["class_label"] == class_label and value["split"] == split
    )


def _request(
    item: dict,
    action: str,
    *,
    head: str | None = None,
    reviewer: str = "browser-reviewer",
) -> DecisionRequest:
    return DecisionRequest(
        batch_sha256=BATCH["batch_sha256"],
        review_item_id=item["review_item_id"],
        expected_review_state_sha256=item["review_state_sha256"],
        expected_ledger_head_sha256=head,
        reviewer=reviewer,
        action=action,
        rationale=f"Reviewed {action} path.",
        evidence_reviewed=True,
        comparison_reviewed=True,
        diff_reviewed=True,
        mapping_target="kos_existing_target" if action == "map" else None,
        edited_payload={"label": "Edited"} if action == "edit" else None,
        split_payload=[{"label": "Part A"}, {"label": "Part B"}]
        if action == "split"
        else None,
        decided_at="2026-07-23T06:00:00+00:00",
    )


def test_review_batch_is_deterministic_and_complete() -> None:
    rebuilt = build_review_batch(
        load_json(PILOT / "m25-4-gold-suite.json"),
        load_json(PILOT / "m25-4-baseline-report.json"),
        load_json(PILOT / "m25-5-calibration-policy.json"),
        load_json(PILOT / "m25-5-calibrated-report.json"),
        load_json(PILOT / "m25-5-acceptance.json"),
    )
    assert rebuilt == BATCH
    assert rebuilt["item_count"] == 30
    assert rebuilt["split_counts"] == {"calibration": 10, "final": 10, "train": 10}
    assert set(rebuilt["decision_actions"]) == ACTIONS
    assert {action for item in rebuilt["items"] for action in item["allowed_actions"]} == ACTIONS
    assert rebuilt["bulk_approval_permitted"] is False
    assert rebuilt["source_write_permitted"] is False
    assert rebuilt["m25_7_authorized"] is False


def test_batch_tampering_fails_closed() -> None:
    value = deepcopy(BATCH)
    value["items"][0]["rationale"] = "tampered"
    with pytest.raises(IntegrityError, match="batch digest mismatch"):
        validate_review_batch(value)


def test_decision_ledger_is_append_only_and_replayable(tmp_path: Path) -> None:
    ledger = DecisionLedger(tmp_path / "ledger")
    item = _item("exact_match")
    first = ledger.append(BATCH, _request(item, "approve"))
    assert first["sequence"] == 1
    assert first["previous_decision_sha256"] is None
    assert first["source_write_permitted"] is False
    audit = ledger.export(BATCH)
    assert audit["decision_count"] == 1
    assert audit["pending_item_count"] == 29
    assert audit["admission_ready"] is False
    assert audit["source_write_permitted"] is False
    with pytest.raises(IntegrityError, match="terminal decision"):
        ledger.append(
            BATCH,
            _request(item, "approve", head=first["decision_sha256"]),
        )


def test_stale_batch_item_and_ledger_heads_fail_closed(tmp_path: Path) -> None:
    ledger = DecisionLedger(tmp_path / "ledger")
    item = _item("exact_match")
    request = _request(item, "approve")
    request.batch_sha256 = "0" * 64
    with pytest.raises(IntegrityError, match="stale batch"):
        ledger.append(BATCH, request)
    request = _request(item, "approve")
    request.expected_review_state_sha256 = "1" * 64
    with pytest.raises(IntegrityError, match="stale review context"):
        ledger.append(BATCH, request)
    first = ledger.append(BATCH, _request(item, "approve"))
    second_item = _item("approved_alias")
    with pytest.raises(IntegrityError, match="stale ledger head"):
        ledger.append(BATCH, _request(second_item, "map"))
    second = ledger.append(
        BATCH,
        _request(second_item, "map", head=first["decision_sha256"]),
    )
    assert second["previous_decision_sha256"] == first["decision_sha256"]


def test_incomplete_acknowledgement_and_action_payloads_fail_closed(tmp_path: Path) -> None:
    ledger = DecisionLedger(tmp_path / "ledger")
    item = _item("exact_match")
    request = _request(item, "approve")
    request.evidence_reviewed = False
    with pytest.raises(IntegrityError, match="incomplete review acknowledgement"):
        ledger.append(BATCH, request)
    alias = _item("approved_alias")
    request = _request(alias, "map")
    request.mapping_target = None
    with pytest.raises(IntegrityError, match="map target required"):
        ledger.append(BATCH, request)
    near = _item("near_match_distinct")
    request = _request(near, "edit")
    request.edited_payload = None
    with pytest.raises(IntegrityError, match="edited payload required"):
        ledger.append(BATCH, request)
    parent = _item("parent_child_distinct")
    request = _request(parent, "split")
    request.split_payload = [{"label": "Only one"}]
    with pytest.raises(IntegrityError, match="at least two parts"):
        ledger.append(BATCH, request)


def test_defer_can_be_superseded_but_still_blocks_completion(tmp_path: Path) -> None:
    ledger = DecisionLedger(tmp_path / "ledger")
    item = _item("polysemy_ambiguous")
    deferred = ledger.append(BATCH, _request(item, "defer"))
    audit = ledger.export(BATCH)
    assert audit["deferred_item_count"] == 1
    assert audit["admission_ready"] is False
    terminal = ledger.append(
        BATCH,
        _request(item, "reject", head=deferred["decision_sha256"]),
    )
    assert terminal["action"] == "reject"
    assert ledger.export(BATCH)["deferred_item_count"] == 0


def test_all_items_must_have_terminal_decisions_before_admission_ready(tmp_path: Path) -> None:
    ledger = DecisionLedger(tmp_path / "ledger")
    head = None
    for item in BATCH["items"]:
        action = "reject" if "reject" in item["allowed_actions"] else item["allowed_actions"][0]
        record = ledger.append(BATCH, _request(item, action, head=head))
        head = record["decision_sha256"]
    audit = ledger.export(BATCH)
    assert audit["terminal_item_count"] == 30
    assert audit["pending_item_count"] == 0
    assert audit["review_complete"] is True
    assert audit["admission_ready"] is True
    assert audit["source_write_permitted"] is False
    assert audit["github_pr_creation_permitted"] is False
    assert audit["m25_7_authorized"] is False


def test_api_is_authenticated_and_has_security_headers(tmp_path: Path) -> None:
    client = TestClient(
        create_review_app(
            BATCH,
            tmp_path / "ledger",
            username=AUTH[0],
            password=AUTH[1],
        )
    )
    denied = client.get("/review")
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"].startswith("Basic")
    page = client.get("/review", auth=AUTH)
    assert page.status_code == 200
    assert "M25.6 Human Review Console" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    queue = client.get("/v1/review/queue", auth=AUTH)
    assert queue.status_code == 200
    assert queue.json()["bulk_approval_permitted"] is False
    assert client.post("/v1/review/bulk-approve", auth=AUTH).status_code == 404


def test_api_records_item_decision_and_rejects_reviewer_mismatch(tmp_path: Path) -> None:
    client = TestClient(
        create_review_app(
            BATCH,
            tmp_path / "ledger",
            username=AUTH[0],
            password=AUTH[1],
        )
    )
    item = _item("exact_match")
    body = _request(item, "approve").model_dump()
    body["reviewer"] = "another-reviewer"
    denied = client.post("/v1/review/decisions", json=body, auth=AUTH)
    assert denied.status_code == 403
    body["reviewer"] = AUTH[0]
    accepted = client.post("/v1/review/decisions", json=body, auth=AUTH)
    assert accepted.status_code == 200
    assert accepted.json()["action"] == "approve"
    assert accepted.json()["admission_ready"] is False
    audit = client.get("/v1/review/audit", auth=AUTH).json()
    assert audit["decision_count"] == 1
    assert audit["records"][0]["authority"] == "admission_decision_only"
