from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_6_acceptance import (
    build_m23_6_acceptance_report,
    canonical_acceptance_evidence,
    validate_m23_6_acceptance,
)


def evidence():
    return canonical_acceptance_evidence()


def test_canonical_evidence_passes_and_report_is_deterministic():
    first = build_m23_6_acceptance_report(evidence())
    second = build_m23_6_acceptance_report(evidence())
    assert first == second
    assert first["status"] == "pass"
    assert first["chain_count"] == 7
    assert first["qdrant_point_count"] == 107
    assert first["rollback"] == {
        "mode": "lexical-only",
        "candidate_dependency_required": False,
        "immediate": True,
    }
    assert first["production_authority"] is False


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda item: item["chains"].pop(2),
            "seven evidence chains|repair chain",
        ),
        (
            lambda item: item["chains"][3].__setitem__(
                "entry_base", "0" * 40
            ),
            "entry_base mismatch|chain is broken",
        ),
        (
            lambda item: item["chains"][4]["workflows"][0].__setitem__(
                "head_sha", "1" * 40
            ),
            "workflow evidence mismatch",
        ),
        (
            lambda item: item["qdrant"].__setitem__(
                "first_upsert_receipt_sha256", "2" * 64
            ),
            "qdrant identity mismatch",
        ),
        (
            lambda item: item["qdrant"].__setitem__(
                "production_authority", True
            ),
            "qdrant identity mismatch",
        ),
        (
            lambda item: item["runtime"].__setitem__(
                "retrieval_mode", "semantic"
            ),
            "runtime identity mismatch|lexical rollback",
        ),
        (
            lambda item: item["candidate_release"].__setitem__(
                "per_concept_section_attribution_available", True
            ),
            "candidate_release identity mismatch|invented per-concept",
        ),
        (
            lambda item: item["source_pr"].__setitem__("merged", True),
            "source_pr identity mismatch",
        ),
        (
            lambda item: item["protected_state"].__setitem__(
                "production", True
            ),
            "protected mutation",
        ),
        (
            lambda item: item["explorer"].__setitem__(
                "typed_graph_and_semantic_overlay_conflation_allowed", True
            ),
            "explorer identity mismatch|conflated",
        ),
    ],
)
def test_fail_closed_adversarial_cases(mutator, match):
    item = copy.deepcopy(evidence())
    mutator(item)
    with pytest.raises(IntegrityError, match=match):
        validate_m23_6_acceptance(item)


def test_semantic_anchors_cover_exact_qdrant_count():
    item = evidence()
    assert sum(
        item["candidate_release"]["semantic_anchor_counts"].values()
    ) == item["qdrant"]["points_count"] == 107


def test_every_workflow_is_bound_to_its_implementation_head():
    item = validate_m23_6_acceptance(evidence())
    for chain in item["chains"]:
        assert chain["workflows"]
        assert all(
            workflow["head_sha"] == chain["implementation_head"]
            and workflow["conclusion"] == "success"
            for workflow in chain["workflows"]
        )
