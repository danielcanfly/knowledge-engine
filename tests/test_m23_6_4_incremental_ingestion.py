from __future__ import annotations

import hashlib
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_incremental_ingestion import (
    ExistingPoint,
    build_message,
    plan_batch,
    validate_message,
)

SOURCE_SHA = "a" * 64
SOURCE_COMMIT = "b" * 40
OLD_TEXT_SHA = hashlib.sha256(b"old").hexdigest()


def section(name: str, text: str, previous: str | None = None) -> dict[str, object]:
    text_sha = hashlib.sha256(text.encode()).hexdigest()
    point_id = str(uuid5(NAMESPACE_URL, f"m23:{name}"))
    return {
        "section_id": name,
        "point_id": point_id,
        "expected_previous_text_sha256": previous,
        "text": text,
        "text_sha256": text_sha,
        "payload": {
            "payload_schema_version": "knowledge-engine-m23-qdrant-payload/v1",
            "section_id": name,
            "article_id": name.split("#", 1)[0],
            "document_id": name.split("#", 1)[0],
            "concept_id": f"concept:{name}",
            "source_path": f"proposals/{name}.md",
            "source_sha256": SOURCE_SHA,
            "text_sha256": text_sha,
            "audience": "internal",
            "source_membership": "evaluation-only-pending-proposal",
            "release_id": "m23pilot-test",
            "release_manifest_sha256": "c" * 64,
            "graph_node_id": f"concept:{name}",
            "embedding_provider": "cloudflare-workers-ai",
            "embedding_model": "@cf/baai/bge-m3",
            "vector_dimension": 1024,
            "vector_name": "default",
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
        },
    }


def message(*sections: dict[str, object], cost: float = 0.01) -> dict[str, object]:
    return build_message(
        release_id="m23pilot-test",
        source_commit_sha=SOURCE_COMMIT,
        emitted_at="2026-07-15T00:00:00Z",
        estimated_usd=cost,
        sections=sections,
    )


def test_insert_skip_replace_and_stale_are_deterministic() -> None:
    insert = section("new#one", "new text")
    skip = section("same#one", "same text")
    replace = section("replace#one", "replacement", OLD_TEXT_SHA)
    stale = section("stale#one", "late replacement", "d" * 64)

    existing = {
        skip["point_id"]: ExistingPoint(
            point_id=str(skip["point_id"]),
            section_id=str(skip["section_id"]),
            text_sha256=str(skip["text_sha256"]),
        ),
        replace["point_id"]: ExistingPoint(
            point_id=str(replace["point_id"]),
            section_id=str(replace["section_id"]),
            text_sha256=OLD_TEXT_SHA,
        ),
        stale["point_id"]: ExistingPoint(
            point_id=str(stale["point_id"]),
            section_id=str(stale["section_id"]),
            text_sha256=OLD_TEXT_SHA,
        ),
    }
    receipt_a = plan_batch([message(insert, skip, replace, stale)], existing)
    receipt_b = plan_batch([message(insert, skip, replace, stale)], existing)
    assert receipt_a == receipt_b
    assert [item["action"] for item in receipt_a["outcomes"]] == [
        "insert",
        "skip-duplicate",
        "replace",
        "reject-stale",
    ]
    assert receipt_a["status"] == "rejected"
    assert all(value is False for value in receipt_a["authority"].values())


def test_message_identity_detects_tampering() -> None:
    raw = message(section("one#one", "hello"))
    raw["sections"][0]["text"] = "tampered"  # type: ignore[index]
    with pytest.raises(IntegrityError, match="text digest mismatch"):
        validate_message(raw)


def test_payload_authority_must_remain_false() -> None:
    raw = message(section("one#one", "hello"))
    raw["sections"][0]["payload"]["production_authority"] = True  # type: ignore[index]
    with pytest.raises(IntegrityError, match="production_authority"):
        validate_message(raw)


def test_wrong_collection_is_refused() -> None:
    raw = message(section("one#one", "hello"))
    raw["collection"] = "production"
    with pytest.raises(IntegrityError, match="wrong collection"):
        validate_message(raw)


def test_oversize_message_is_refused() -> None:
    sections = [section(f"s{i}#one", f"text {i}") for i in range(26)]
    with pytest.raises(IntegrityError, match="section count"):
        message(*sections)


def test_batch_and_daily_budget_caps_are_refused() -> None:
    messages = [message(section(f"s{i}#one", f"text {i}"), cost=0.13) for i in range(4)]
    with pytest.raises(IntegrityError, match="run budget"):
        plan_batch(messages, {})

    valid = message(section("daily#one", "text"), cost=0.01)
    with pytest.raises(IntegrityError, match="daily budget"):
        plan_batch([valid], {}, daily_estimated_usd_before=2.0)
    with pytest.raises(IntegrityError, match="daily section"):
        plan_batch([valid], {}, daily_sections_before=2000)


def test_duplicate_message_in_batch_is_refused() -> None:
    raw = message(section("one#one", "hello"))
    with pytest.raises(IntegrityError, match="duplicate message_id"):
        plan_batch([raw, deepcopy(raw)], {})


def test_point_identity_collision_is_terminal_stale_rejection() -> None:
    item = section("one#one", "hello")
    existing = {
        item["point_id"]: ExistingPoint(
            point_id=str(item["point_id"]),
            section_id="different#section",
            text_sha256=OLD_TEXT_SHA,
        )
    }
    receipt = plan_batch([message(item)], existing)
    assert receipt["outcomes"][0]["action"] == "reject-stale"
    assert receipt["outcomes"][0]["reason"] == "point-id-section-id-conflict"
