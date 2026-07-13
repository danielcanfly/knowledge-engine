from __future__ import annotations

import copy
import hashlib
import json

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m21_resumable_batch import (
    build_batch_plan,
    build_initial_checkpoint,
    transition_checkpoint,
)


def _snapshot(count: int = 3) -> dict:
    identity = {
        "engine_sha": "e" * 40,
        "source_sha": "s" * 40,
        "foundation_sha": "f" * 40,
        "captured_at": "2026-07-13T16:00:00Z",
    }
    items = []
    for index in range(count):
        items.append(
            {
                "canonical_url": f"https://www.danielcanfly.com/blog/post-{index}",
                "language": "en",
                "slug": f"post-{index}",
                "series": "production-rag",
                "part": index + 1,
                "published_at": None,
                "modified_at": None,
                "content_sha256": f"{index + 1:064x}",
                "source_kind": "repository_markdown",
                "locator": f"content/en/post-{index}.md",
                "redirects": [],
                "translated_counterpart": None,
                "access_status": "available",
                "intake_status": "captured" if index == 0 else "discovered",
                "ownership_basis": "first-party",
                "audience": "public",
            }
        )
    snapshot = {
        "schema": "knowledge-engine-blog-inventory/v1",
        "identity": identity,
        "authority": "evidence_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "items": items,
    }
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    snapshot["snapshot_sha256"] = hashlib.sha256(canonical).hexdigest()
    return snapshot


def test_plan_is_deterministic_partitioned_and_evidence_only() -> None:
    first = build_batch_plan(_snapshot(5), batch_size=2)
    second = build_batch_plan(_snapshot(5), batch_size=2)
    assert first == second
    assert first["item_count"] == 5
    assert [len(batch["items"]) for batch in first["batches"]] == [2, 2, 1]
    assert first["authority"] == "evidence_only"
    assert first["canonical_knowledge"] is False
    assert first["production_authority"] is False


def test_stable_item_and_batch_ids_do_not_depend_on_input_order() -> None:
    left = _snapshot(4)
    right = copy.deepcopy(left)
    right["items"].reverse()
    unsigned = dict(right)
    unsigned.pop("snapshot_sha256")
    right["snapshot_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert build_batch_plan(left, batch_size=2) == build_batch_plan(right, batch_size=2)


def test_rejected_and_unavailable_items_are_not_planned() -> None:
    snapshot = _snapshot(3)
    snapshot["items"][1]["intake_status"] = "rejected"
    snapshot["items"][2]["access_status"] = "blocked"
    unsigned = dict(snapshot)
    unsigned.pop("snapshot_sha256")
    snapshot["snapshot_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    plan = build_batch_plan(snapshot)
    assert plan["item_count"] == 1
    assert plan["batches"][0]["items"][0]["expected_action"] == "verify"


def test_initial_checkpoint_is_complete_and_resumable() -> None:
    plan = build_batch_plan(_snapshot(3), batch_size=2)
    checkpoint = build_initial_checkpoint(plan, created_at="2026-07-13T18:00:00+08:00")
    assert checkpoint["revision"] == 0
    assert [state["status"] for state in checkpoint["states"]] == ["pending"] * 3
    assert checkpoint["resume_cursor"]["item_key"] == checkpoint["states"][0]["item_key"]
    assert checkpoint["states"][0]["updated_at"] == "2026-07-13T10:00:00Z"


def test_transition_is_idempotent_and_resume_cursor_never_rewinds() -> None:
    plan = build_batch_plan(_snapshot(2))
    checkpoint = build_initial_checkpoint(plan, created_at="2026-07-13T10:00:00Z")
    first_key = checkpoint["states"][0]["item_key"]
    running = transition_checkpoint(
        plan,
        checkpoint,
        item_key=first_key,
        target_status="running",
        expected_revision=0,
        updated_at="2026-07-13T10:01:00Z",
    )
    completed = transition_checkpoint(
        plan,
        running,
        item_key=first_key,
        target_status="completed",
        expected_revision=1,
        updated_at="2026-07-13T10:02:00Z",
    )
    assert completed["resume_cursor"]["item_key"] == completed["states"][1]["item_key"]
    assert transition_checkpoint(
        plan,
        completed,
        item_key=first_key,
        target_status="completed",
        expected_revision=2,
        updated_at="2026-07-13T10:03:00Z",
    ) == completed


def test_retryable_state_records_failure_and_retry_time() -> None:
    plan = build_batch_plan(_snapshot(1))
    checkpoint = build_initial_checkpoint(plan, created_at="2026-07-13T10:00:00Z")
    key = checkpoint["states"][0]["item_key"]
    running = transition_checkpoint(
        plan,
        checkpoint,
        item_key=key,
        target_status="running",
        expected_revision=0,
        updated_at="2026-07-13T10:01:00Z",
    )
    retryable = transition_checkpoint(
        plan,
        running,
        item_key=key,
        target_status="retryable",
        expected_revision=1,
        updated_at="2026-07-13T10:02:00Z",
        failure_code="connector-timeout",
        retry_at="2026-07-13T10:10:00Z",
    )
    state = retryable["states"][0]
    assert state["status"] == "retryable"
    assert state["attempts"] == 1
    assert state["failure_code"] == "connector-timeout"
    assert retryable["resume_cursor"]["item_key"] == key


def test_stale_revision_invalid_transition_and_unknown_item_fail_closed() -> None:
    plan = build_batch_plan(_snapshot(1))
    checkpoint = build_initial_checkpoint(plan, created_at="2026-07-13T10:00:00Z")
    key = checkpoint["states"][0]["item_key"]
    with pytest.raises(IntegrityError, match="stale checkpoint revision"):
        transition_checkpoint(
            plan,
            checkpoint,
            item_key=key,
            target_status="running",
            expected_revision=1,
            updated_at="2026-07-13T10:01:00Z",
        )
    with pytest.raises(IntegrityError, match="invalid checkpoint transition"):
        transition_checkpoint(
            plan,
            checkpoint,
            item_key=key,
            target_status="completed",
            expected_revision=0,
            updated_at="2026-07-13T10:01:00Z",
        )
    with pytest.raises(IntegrityError, match="unknown item key"):
        transition_checkpoint(
            plan,
            checkpoint,
            item_key="missing",
            target_status="running",
            expected_revision=0,
            updated_at="2026-07-13T10:01:00Z",
        )


def test_tampered_inventory_plan_and_checkpoint_fail_closed() -> None:
    snapshot = _snapshot(1)
    snapshot["items"][0]["slug"] = "tampered"
    with pytest.raises(IntegrityError, match="inventory digest mismatch"):
        build_batch_plan(snapshot)

    plan = build_batch_plan(_snapshot(1))
    tampered_plan = copy.deepcopy(plan)
    tampered_plan["item_count"] = 99
    with pytest.raises(IntegrityError, match="batch plan digest mismatch"):
        build_initial_checkpoint(tampered_plan, created_at="2026-07-13T10:00:00Z")

    checkpoint = build_initial_checkpoint(plan, created_at="2026-07-13T10:00:00Z")
    checkpoint["states"][0]["status"] = "completed"
    with pytest.raises(IntegrityError, match="checkpoint digest mismatch"):
        transition_checkpoint(
            plan,
            checkpoint,
            item_key=checkpoint["states"][0]["item_key"],
            target_status="completed",
            expected_revision=0,
            updated_at="2026-07-13T10:01:00Z",
        )


def test_cross_plan_checkpoint_and_coverage_drift_fail_closed() -> None:
    plan = build_batch_plan(_snapshot(2))
    other = build_batch_plan(_snapshot(3))
    checkpoint = build_initial_checkpoint(plan, created_at="2026-07-13T10:00:00Z")
    with pytest.raises(IntegrityError, match="checkpoint identity mismatch"):
        transition_checkpoint(
            other,
            checkpoint,
            item_key=checkpoint["states"][0]["item_key"],
            target_status="running",
            expected_revision=0,
            updated_at="2026-07-13T10:01:00Z",
        )


def test_batch_size_bounds_and_empty_actionable_inventory_fail_closed() -> None:
    with pytest.raises(IntegrityError, match="batch size"):
        build_batch_plan(_snapshot(), batch_size=0)
    snapshot = _snapshot(1)
    snapshot["items"][0]["intake_status"] = "rejected"
    unsigned = dict(snapshot)
    unsigned.pop("snapshot_sha256")
    snapshot["snapshot_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(IntegrityError, match="no actionable"):
        build_batch_plan(snapshot)
