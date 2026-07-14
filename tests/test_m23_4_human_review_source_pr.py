from __future__ import annotations

import copy
import hashlib
import json

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_human_review_source_pr import (
    FOUNDATION_SHA,
    SOURCE_SHA,
    build_human_review_package,
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def evidence(seed: str) -> list[dict[str, object]]:
    return [
        {
            "snapshot_id": "a" * 64,
            "plan_sha256": "b" * 64,
            "derivative_id": f"derivative_{seed}",
            "start": 0,
            "end": 4,
            "excerpt_sha256": "c" * 64,
        }
    ]


def candidate(candidate_id: str, label: str, tags: list[str]) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "kind": "concept",
        "label": label,
        "normalized_label": label.casefold(),
        "language": "en",
        "confidence": 0.9,
        "aliases": [],
        "controlled_tags": tags,
        "definition": f"Definition for {label}.",
        "evidence_spans": evidence(candidate_id),
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }


def fixture(*, overlap: bool) -> tuple[dict, dict, list[dict]]:
    identity = {
        "engine_sha": "1" * 40,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
    }
    concept = candidate("concept_a", "Fresh Harness Concept", ["agents"] if overlap else [])
    extraction = {
        "schema": "knowledge-engine-extraction-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "source_text_untrusted": True,
        "plan_sha256": "d" * 64,
        "checkpoint_sha256": "e" * 64,
        "inventory_sha256": "f" * 64,
        "identity": identity,
        "allowed_tags": ["agents"],
        "derivative_count": 1,
        "candidate_count": 1,
        "candidates": [concept],
    }
    extraction["packet_sha256"] = digest(extraction)
    tag_rows = []
    if overlap:
        tag_rows.append(
            {
                "tag_candidate_id": "tag_a",
                "source_candidate_id": "concept_a",
                "source_tag": "agents",
                "canonical_tag": "agents",
                "dimension": "domain",
                "confidence": 0.8,
                "evidence_spans": evidence("tag"),
                "status": "pending_review",
                "authority": "candidate_only",
                "canonical_knowledge": False,
                "production_authority": False,
            }
        )
    governed = {
        "schema": "knowledge-engine-governed-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "foundation_sha": FOUNDATION_SHA,
        "extraction_packet_sha256": extraction["packet_sha256"],
        "identity": identity,
        "relation_ontology": {
            "schema_version": "knowledge-os-relation-ontology/v0.1",
            "ontology_id": "daniel-knowledge-os/relation-ontology",
            "version": "0.1.0",
            "sha256": "2" * 64,
        },
        "tag_taxonomy": {
            "schema_version": "knowledge-os-tag-taxonomy/v0.1",
            "taxonomy_id": "daniel-knowledge-os/tag-taxonomy",
            "version": "0.1.0",
            "sha256": "3" * 64,
        },
        "typed_relation_count": 0,
        "governed_tag_count": len(tag_rows),
        "typed_relation_candidates": [],
        "governed_tag_candidates": tag_rows,
    }
    governed["packet_sha256"] = digest(governed)
    source = [
        {
            "x_kos_id": "ko_existing",
            "concept_path": "bundle/concepts/existing.md",
            "title": "Existing Agent Concept",
            "aliases": [],
            "bilingual_terms": [],
            "tags": ["agents"],
            "audience": "public",
            "source_sha256": "4" * 64,
        }
    ]
    return extraction, governed, source


def test_shared_tag_signal_blocks_automatic_packaging(monkeypatch: pytest.MonkeyPatch) -> None:
    extraction, governed, source = fixture(overlap=True)
    monkeypatch.setattr(
        "knowledge_engine.m23_human_review_source_pr.EXTRACTION_SHA",
        extraction["packet_sha256"],
    )
    monkeypatch.setattr(
        "knowledge_engine.m23_human_review_source_pr.GOVERNED_SHA",
        governed["packet_sha256"],
    )
    result = build_human_review_package(extraction, governed, source)
    assert result["resolution_packet"]["packaging_blocked"] is True
    assert result["receipt"]["m21_6_status"] == "blocked_by_m21_5"
    assert result["manual_review_packet"]["review_item_count"] == 1
    assert result["receipt"]["human_approval_recorded"] is False


def test_distinct_candidate_routes_through_m21_6(monkeypatch: pytest.MonkeyPatch) -> None:
    extraction, governed, source = fixture(overlap=False)
    monkeypatch.setattr(
        "knowledge_engine.m23_human_review_source_pr.EXTRACTION_SHA",
        extraction["packet_sha256"],
    )
    monkeypatch.setattr(
        "knowledge_engine.m23_human_review_source_pr.GOVERNED_SHA",
        governed["packet_sha256"],
    )
    result = build_human_review_package(extraction, governed, source)
    assert result["resolution_packet"]["packaging_blocked"] is False
    assert result["receipt"]["m21_6_status"] == "prepared"
    assert result["m21_6_preparation"] is not None
    assert result["m21_6_preparation"]["bulk_preparation"]["source_write_permitted"] is False


def test_packet_tamper_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    extraction, governed, source = fixture(overlap=True)
    monkeypatch.setattr(
        "knowledge_engine.m23_human_review_source_pr.EXTRACTION_SHA",
        extraction["packet_sha256"],
    )
    monkeypatch.setattr(
        "knowledge_engine.m23_human_review_source_pr.GOVERNED_SHA",
        governed["packet_sha256"],
    )
    tampered = copy.deepcopy(extraction)
    tampered["candidates"][0]["label"] = "Tampered"
    with pytest.raises(IntegrityError, match="extraction digest mismatch"):
        build_human_review_package(tampered, governed, source)


def test_real_receipt_is_review_only() -> None:
    receipt = {
        "candidate_count": 38,
        "endpoint_count": 15,
        "typed_relation_count": 12,
        "governed_tag_count": 34,
        "human_approval_recorded": False,
        "source_pr_required_state": "draft",
        "source_pr_merge_permitted": False,
    }
    assert receipt["candidate_count"] == 38
    assert receipt["endpoint_count"] == 15
    assert receipt["typed_relation_count"] == 12
    assert receipt["governed_tag_count"] == 34
    assert receipt["human_approval_recorded"] is False
    assert receipt["source_pr_required_state"] == "draft"
    assert receipt["source_pr_merge_permitted"] is False
