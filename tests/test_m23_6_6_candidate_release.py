from __future__ import annotations

import copy
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_candidate_release import (
    build_candidate_release,
    canonical_json_bytes,
    validate_candidate_release,
    write_candidate_release,
)


def test_real_candidate_release_accepts() -> None:
    report = validate_candidate_release(build_candidate_release())
    assert report["status"] == "pass"
    assert report["counts"] == {
        "candidate_concepts": 15,
        "typed_relations": 12,
        "semantic_sections": 107,
        "semantic_anchors": 3,
    }
    assert report["external_mutations"] == 0


def test_release_generation_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    report_a = write_candidate_release(first)
    report_b = write_candidate_release(second)
    assert canonical_json_bytes(report_a) == canonical_json_bytes(report_b)
    assert sorted(path.name for path in first.iterdir()) == sorted(
        path.name for path in second.iterdir()
    )
    for path in first.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes()


def test_rejects_renderer_field() -> None:
    artifacts = copy.deepcopy(build_candidate_release())
    artifacts["candidate-source-bundle.json"]["concepts"][0]["color"] = "red"
    with pytest.raises(IntegrityError, match="renderer fields"):
        validate_candidate_release(artifacts)


def test_rejects_candidate_authority_drift() -> None:
    artifacts = copy.deepcopy(build_candidate_release())
    artifacts["candidate-source-bundle.json"]["concepts"][0][
        "canonical_knowledge"
    ] = True
    with pytest.raises(IntegrityError, match="canonical_knowledge"):
        validate_candidate_release(artifacts)


def test_rejects_semantic_anchor_drift() -> None:
    artifacts = copy.deepcopy(build_candidate_release())
    artifacts["semantic-reference.json"]["anchor_counts"][
        "pilot/harness-theory-part-01"
    ] = 28
    with pytest.raises(IntegrityError, match="counts mismatch"):
        validate_candidate_release(artifacts)


def test_rejects_invented_per_concept_attribution() -> None:
    artifacts = copy.deepcopy(build_candidate_release())
    artifacts["semantic-reference.json"][
        "per_concept_section_attribution_available"
    ] = True
    with pytest.raises(IntegrityError, match="must not be claimed"):
        validate_candidate_release(artifacts)


def test_rejects_graph_semantic_conflation() -> None:
    artifacts = copy.deepcopy(build_candidate_release())
    artifacts["candidate-explorer-overlay.json"][
        "typed_graph_and_semantic_overlay_conflated"
    ] = True
    with pytest.raises(IntegrityError, match="cannot be conflated"):
        validate_candidate_release(artifacts)


def test_rejects_manifest_self_digest_drift() -> None:
    artifacts = copy.deepcopy(build_candidate_release())
    artifacts["candidate-release-manifest.json"]["graph"]["node_count"] = 14
    with pytest.raises(IntegrityError, match="self-digest mismatch"):
        validate_candidate_release(artifacts)
