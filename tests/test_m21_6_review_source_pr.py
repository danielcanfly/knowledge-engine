from __future__ import annotations

import copy
import hashlib
import json

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m21_review_source_pr import (
    FOUNDATION_SHA,
    SOURCE_SHA,
    build_review_source_pr_preparation,
)

ENGINE_SHA = "2" * 40
D64 = "a" * 64


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def signed(value, field="packet_sha256"):
    output = copy.deepcopy(value)
    output[field] = digest(output)
    return output


def evidence(seed="a"):
    return [
        {
            "snapshot_id": D64,
            "plan_sha256": "b" * 64,
            "derivative_id": f"derivative-{seed}",
            "start": 0,
            "end": 4,
            "excerpt_sha256": "c" * 64,
        }
    ]


def candidate(candidate_id, label, kind="concept", confidence=0.9, **extra):
    return {
        "candidate_id": candidate_id,
        "kind": kind,
        "label": label,
        "normalized_label": label.casefold(),
        "language": "en",
        "confidence": confidence,
        "aliases": [],
        "controlled_tags": [],
        "evidence_spans": evidence(candidate_id),
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        **extra,
    }


def fixture(outcome="distinct_new_candidate", action="create_concept"):
    identity = {
        "engine_sha": ENGINE_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
    }
    candidates = [candidate("cand-1", "Alpha")]
    extraction = signed(
        {
            "schema": "knowledge-engine-extraction-candidates/v1",
            "authority": "candidate_only",
            "canonical_knowledge": False,
            "production_authority": False,
            "review_required": True,
            "identity": identity,
            "candidate_count": 1,
            "candidates": candidates,
        }
    )
    governed = signed(
        {
            "schema": "knowledge-engine-governed-candidates/v1",
            "authority": "candidate_only",
            "canonical_knowledge": False,
            "production_authority": False,
            "review_required": True,
            "foundation_sha": FOUNDATION_SHA,
            "extraction_packet_sha256": extraction["packet_sha256"],
            "identity": identity,
            "relation_ontology": {"schema_version": "knowledge-os-relation-ontology/v0.1"},
            "tag_taxonomy": {"schema_version": "knowledge-os-tag-taxonomy/v0.1"},
            "typed_relation_count": 0,
            "governed_tag_count": 0,
            "typed_relation_candidates": [],
            "governed_tag_candidates": [],
        }
    )
    existing_id = None if outcome == "distinct_new_candidate" else "ko_alpha"
    existing_path = None if outcome == "distinct_new_candidate" else "bundle/concepts/alpha.md"
    resolution = {
        "resolution_id": "res-1",
        "candidate_ids": ["cand-1"],
        "outcome": outcome,
        "existing_x_kos_id": existing_id,
        "existing_concept_path": existing_path,
        "strong_signals": [],
        "weak_signals": [],
        "evidence_spans": evidence("cand-1"),
        "audience": "public",
        "confidence": 0.9,
        "status": "pending_review",
        "blocks_packaging": False,
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }
    resolution_packet = signed(
        {
            "schema": "knowledge-engine-resolution-candidates/v1",
            "authority": "candidate_only",
            "canonical_knowledge": False,
            "production_authority": False,
            "review_required": True,
            "source_sha": SOURCE_SHA,
            "foundation_sha": FOUNDATION_SHA,
            "identity": identity,
            "extraction_packet_sha256": extraction["packet_sha256"],
            "governed_packet_sha256": governed["packet_sha256"],
            "source_index_sha256": "d" * 64,
            "candidate_audience_sha256": "e" * 64,
            "claim_assertions_sha256": "f" * 64,
            "resolution_count": 1,
            "contradiction_count": 0,
            "packaging_blocked": False,
            "resolutions": [resolution],
            "contradictions": [],
        }
    )
    if action == "create_concept":
        paths = ["bundle/concepts/alpha.md", "provenance/alpha.json"]
        body = "# Alpha\n\nEvidence-bound proposed concept."
        change = None
        comparison = {
            "x_kos_id": None,
            "concept_path": None,
            "comparison_summary": "No existing concept.",
        }
    elif action == "attach_alias":
        paths = ["bundle/concepts/alpha.md"]
        body = None
        change = "Attach approved alias candidate Alpha Alias."
        comparison = {
            "x_kos_id": "ko_alpha",
            "concept_path": paths[0],
            "comparison_summary": "Unique existing target.",
        }
    else:
        paths = ["bundle/concepts/alpha.md"]
        body = None if action != "update_concept" else "# Alpha\n\nUpdated body."
        change = None if action == "update_concept" else "Add evidence-bound claim."
        comparison = {
            "x_kos_id": "ko_alpha",
            "concept_path": paths[0],
            "comparison_summary": "Exact existing target.",
        }
    item = {
        "resolution_id": "res-1",
        "action": action,
        "candidate_ids": ["cand-1"],
        "target_paths": paths,
        "proposed_concept_body": body,
        "proposed_change": change,
        "governed_tag_candidate_ids": [],
        "typed_relation_candidate_ids": [],
        "existing_comparison": comparison,
        "duplicate_conflict_analysis": {
            "duplicate": False,
            "ambiguity": False,
            "contradiction": False,
            "acl_conflict": False,
            "notes": [],
        },
        "audience": "public",
        "confidence": 0.8,
    }
    return extraction, governed, resolution_packet, [item]


def build(data):
    return build_review_source_pr_preparation(*data)


def test_builds_deterministic_review_and_bulk_packets():
    data = fixture()
    first = build(data)
    second = build(copy.deepcopy(data))
    assert first == second
    assert first["review_packets"]["schema"] == "knowledge-engine-human-review-packets/v1"
    assert first["bulk_preparation"]["schema"] == "knowledge-engine-bulk-source-pr-preparation/v1"
    assert first["review_packets"]["item_count"] == 1
    assert first["bulk_preparation"]["source_write_permitted"] is False
    assert first["bulk_preparation"]["github_pr_creation_permitted"] is False


def test_accepts_exact_existing_claim_change():
    result = build(fixture("exact_existing_match", "add_claim"))
    item = result["review_packets"]["items"][0]
    assert item["action"] == "add_claim"
    assert item["existing_comparison"]["x_kos_id"] == "ko_alpha"


def test_accepts_alias_attachment():
    result = build(fixture("attach_alias_candidate", "attach_alias"))
    assert result["review_packets"]["items"][0]["action"] == "attach_alias"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data[0].__setitem__("packet_sha256", "0" * 64),
        lambda data: data[1].__setitem__("extraction_packet_sha256", "0" * 64),
        lambda data: data[2].__setitem__("packaging_blocked", True),
        lambda data: data[2].__setitem__("contradictions", [{"contradiction_id": "x"}]),
        lambda data: data[3][0].__setitem__("audience", "internal"),
        lambda data: data[3][0].__setitem__("confidence", 0.95),
        lambda data: data[3][0].__setitem__("target_paths", ["../secrets.md"]),
        lambda data: data[3][0]["duplicate_conflict_analysis"].__setitem__("ambiguity", True),
        lambda data: data[3][0].__setitem__("candidate_ids", ["missing"]),
    ],
)
def test_rejects_invalid_or_blocking_inputs(mutator):
    data = list(fixture())
    mutator(data)
    with pytest.raises(IntegrityError):
        build(data)


def test_rejects_incomplete_review_coverage():
    extraction, governed, resolution, items = fixture()
    second = copy.deepcopy(resolution["resolutions"][0])
    second["resolution_id"] = "res-2"
    second["candidate_ids"] = ["cand-2"]
    second["evidence_spans"] = evidence("cand-2")
    extraction["candidates"].append(candidate("cand-2", "Beta"))
    extraction["candidate_count"] = 2
    extraction["packet_sha256"] = digest(
        {key: value for key, value in extraction.items() if key != "packet_sha256"}
    )
    governed["extraction_packet_sha256"] = extraction["packet_sha256"]
    governed["packet_sha256"] = digest(
        {key: value for key, value in governed.items() if key != "packet_sha256"}
    )
    resolution["extraction_packet_sha256"] = extraction["packet_sha256"]
    resolution["governed_packet_sha256"] = governed["packet_sha256"]
    resolution["resolutions"].append(second)
    resolution["resolution_count"] = 2
    resolution["packet_sha256"] = digest(
        {key: value for key, value in resolution.items() if key != "packet_sha256"}
    )
    with pytest.raises(IntegrityError, match="incomplete resolution review coverage"):
        build((extraction, governed, resolution, items))


def test_rejects_cross_item_path_collision():
    extraction, governed, resolution, items = fixture()
    second = copy.deepcopy(resolution["resolutions"][0])
    second["resolution_id"] = "res-2"
    second["candidate_ids"] = ["cand-2"]
    second["evidence_spans"] = evidence("cand-2")
    extraction["candidates"].append(candidate("cand-2", "Beta"))
    extraction["candidate_count"] = 2
    extraction["packet_sha256"] = digest(
        {key: value for key, value in extraction.items() if key != "packet_sha256"}
    )
    governed["extraction_packet_sha256"] = extraction["packet_sha256"]
    governed["packet_sha256"] = digest({k: v for k, v in governed.items() if k != "packet_sha256"})
    resolution["extraction_packet_sha256"] = extraction["packet_sha256"]
    resolution["governed_packet_sha256"] = governed["packet_sha256"]
    resolution["resolutions"].append(second)
    resolution["resolution_count"] = 2
    resolution["packet_sha256"] = digest(
        {key: value for key, value in resolution.items() if key != "packet_sha256"}
    )
    item2 = copy.deepcopy(items[0])
    item2["resolution_id"] = "res-2"
    item2["candidate_ids"] = ["cand-2"]
    items.append(item2)
    with pytest.raises(IntegrityError, match="path collision"):
        build((extraction, governed, resolution, items))


def test_secret_like_proposed_body_rejected():
    data = fixture()
    data[3][0]["proposed_concept_body"] = "api_key=supersecretvalue123"
    with pytest.raises(IntegrityError, match="secret-like"):
        build(data)
