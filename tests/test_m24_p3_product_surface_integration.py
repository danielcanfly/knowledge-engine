from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    P3_ISSUE_NUMBER,
    build_p3_product_surface_report,
    canonical_all_concepts_response,
    canonical_concept_wiki_page,
    canonical_graph_navigation_state,
    canonical_obsidian_export,
    canonical_runtime_search,
    load_canonical_release,
)

EVIDENCE_PATH = Path("pilot/m24/m24-p3-product-surface-integration.json")


def _evidence() -> dict:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_m24_p3_evidence_is_digest_bound() -> None:
    evidence = _evidence()
    unsigned = dict(evidence)
    digest = unsigned.pop("self_sha256")

    assert digest != "TO_BE_FILLED"
    assert canonical_sha256(unsigned) == digest


def test_m24_p3_loads_exact_p2_canonical_release() -> None:
    bundle = load_canonical_release()

    assert bundle.release_id == CANONICAL_RELEASE_ID
    assert bundle.manifest_sha256 == CANONICAL_MANIFEST_SHA256
    assert bundle.manifest["source"]["commit_sha"] == (
        "acf78596ace8a7366688ccef72b507204d09d9f9"
    )
    assert bundle.manifest["counts"] == {
        "concepts": 20,
        "edges": 0,
        "provenance_records": 20,
        "sections": 92,
        "source_snapshots": 7,
        "tombstones": 0,
    }
    assert len(bundle.graph_v2["nodes"]) == 20
    assert len(bundle.graph_v2["edges"]) == 28
    assert bundle.artifact_sha256["graph_v2"] == (
        "6737dfb3fa9cd4d992c26dce562329c95e06066cd475f97f2fdffdbab8f25abe"
    )
    assert bundle.artifact_sha256["lexical_index"] == (
        "1106857e4eb2438674bc74a074bf81132f54b77f4c5d2dfe52954328b8271b83"
    )
    assert bundle.artifact_sha256["provenance"] == (
        "0593d6669661df0d639e13b3b93d744b36f6fa934ca4faf7566d05574a573a05"
    )


def test_m24_p3_lexical_search_uses_canonical_release_and_source_viewers() -> None:
    bundle = load_canonical_release()

    response = canonical_runtime_search(
        query="canonical run authority",
        max_results=5,
        bundle=bundle,
    )

    assert response.status == "answered"
    assert response.release_id == CANONICAL_RELEASE_ID
    assert response.audience == "internal"
    assert response.results[0].concept_id == "concepts/canonical-run-authority"
    assert response.source_viewers
    assert all(viewer.release_id == CANONICAL_RELEASE_ID for viewer in response.source_viewers)
    assert all(
        viewer.summary.retrieval_authority == "lexical"
        for viewer in response.source_viewers
    )
    assert all(not viewer.summary.raw_evidence_exposed for viewer in response.source_viewers)


def test_m24_p3_concept_wiki_and_graph_navigation_share_release_identity() -> None:
    bundle = load_canonical_release()
    page = canonical_concept_wiki_page(
        concept_id="concepts/harness",
        query="harness",
        bundle=bundle,
    )
    state = canonical_graph_navigation_state(
        selected_concept_id="concepts/harness",
        bundle=bundle,
    )

    assert page.release_id == CANONICAL_RELEASE_ID
    assert page.concept_id == "concepts/harness"
    assert page.sections
    assert {item.neighbor_concept_id for item in page.relationships} >= {
        "concepts/harness-agent-loop",
        "concepts/headless-harness-service",
    }
    assert page.authority.production_retrieval == "lexical"
    assert page.authority.semantic_serving_enabled is False
    assert state.release_id == CANONICAL_RELEASE_ID
    assert state.selected_concept_id == "concepts/harness"
    assert len(state.nodes) == 20
    assert len(state.edges) == 28
    assert state.authority.semantic_promotion_enabled is False


def test_m24_p3_obsidian_export_contains_one_note_per_canonical_concept() -> None:
    bundle = load_canonical_release()
    response = canonical_all_concepts_response(bundle=bundle)
    export = canonical_obsidian_export(bundle=bundle)

    concept_notes = [item for item in export.files if item.path.startswith("concepts/")]
    source_notes = [item for item in export.files if item.path.startswith("sources/")]

    assert response.release_id == CANONICAL_RELEASE_ID
    assert len(response.results) == 20
    assert len(concept_notes) == 20
    assert len(source_notes) == 7
    assert any("[[sources/" in item.content for item in concept_notes)
    assert export.authority.semantic_serving_enabled is False
    assert export.authority.source_mutation_authorized is False


def test_m24_p3_report_records_surface_exit_gate_and_non_serving_boundary() -> None:
    report = build_p3_product_surface_report()
    evidence = _evidence()

    assert report.model_dump(mode="json") == evidence
    assert report.issue_number == P3_ISSUE_NUMBER
    assert report.status == "product_surface_integration_complete"
    assert report.release_id == CANONICAL_RELEASE_ID
    assert report.shared_exit_gate == {
        "same_canonical_candidate_release": True,
        "surface_count": 5,
        "queries": [
            "harness",
            "stopping policy",
            "canonical run authority",
            "tool call proposal",
        ],
        "semantic_promotion_required_before_production_semantic_or_hybrid": True,
    }
    assert {item.surface for item in report.product_surfaces} == {
        "lexical_search",
        "source_viewer",
        "concept_wiki",
        "sigma_graph",
        "obsidian_export",
    }
    assert report.authority.production_retrieval == "lexical"
    assert report.authority.semantic_promotion_enabled is False
    assert report.authority.semantic_serving_enabled is False
    assert report.authority.hybrid_retrieval_enabled is False
    assert report.authority.production_pointer_mutation is False
    assert report.authority.production_r2_mutation is False
    assert report.authority.qdrant_mutation is False
    assert report.authority.source_mutation is False
    assert report.authority.credential_mutation is False
    assert report.authority.traffic_mutation is False
