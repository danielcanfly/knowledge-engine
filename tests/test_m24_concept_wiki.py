from __future__ import annotations

import pytest

from knowledge_engine.m14_public_contracts import public_search_response_from_runtime
from knowledge_engine.m24_concept_wiki import (
    CONCEPT_WIKI_SCHEMA,
    build_concept_wiki_page,
)


def _runtime_result() -> dict:
    citation = {
        "source_id": "source-1",
        "source_kind": "web",
        "source_title": "Compiler Specification",
        "publisher": "Example Foundation",
        "uri": "https://example.com/compiler",
        "retrieved_at": "2026-07-20T00:00:00Z",
        "content_sha256": "e" * 64,
        "snapshot_available": True,
        "concept_id": "concepts/compiler",
        "section_id": "concepts/compiler#overview",
        "citation_scope": "claim",
        "claim_id": "claim-1",
        "support": "direct",
        "locator": {"heading": "Overview"},
    }
    return {
        "status": "answered",
        "release": {
            "release_id": "20260720T000000Z-m24",
            "manifest_sha256": "f" * 64,
        },
        "results": [
            {
                "concept_id": "concepts/compiler",
                "section_id": "concepts/compiler#overview",
                "title": "Knowledge Compiler",
                "section_title": "Overview",
                "excerpt": "The compiler validates reviewed knowledge.",
                "score": 14,
                "citations": [citation],
            },
            {
                "concept_id": "concepts/other",
                "section_id": "concepts/other#overview",
                "title": "Other",
                "section_title": "Overview",
                "excerpt": "A different concept.",
                "score": 6,
                "citations": [
                    {
                        **citation,
                        "source_id": "source-2",
                        "source_title": "Other Source",
                        "uri": "https://example.com/other",
                        "concept_id": "concepts/other",
                        "section_id": "concepts/other#overview",
                    }
                ],
            },
        ],
        "not_found_reason": None,
    }


def _response():
    return public_search_response_from_runtime(
        _runtime_result(),
        query="compiler",
        max_results=10,
        audience="public",
    )


def _neighborhood() -> dict:
    return {
        "schema_version": "knowledge-engine-graph-api/v1",
        "release": {"release_id": "20260720T000000Z-m24"},
        "read_only": True,
        "root_concept_id": "concepts/compiler",
        "depth": 1,
        "nodes": [
            {
                "concept_id": "concepts/compiler",
                "title": "Knowledge Compiler",
                "description": "Builds governed knowledge releases.",
            },
            {
                "concept_id": "concepts/agent",
                "title": "Agent",
                "description": "Executes tasks.",
            },
        ],
        "edges": [
            {
                "edge_id": "edge_1",
                "source": "concepts/compiler",
                "target": "concepts/agent",
                "relation_type": "supports",
                "directed": True,
                "confidence": 0.91,
                "generated_inverse": False,
            }
        ],
        "truncated": False,
    }


def test_concept_wiki_page_binds_sections_relationships_and_sources() -> None:
    page = build_concept_wiki_page(
        _response(),
        concept_id="concepts/compiler",
        graph_neighborhood=_neighborhood(),
    )
    payload = page.model_dump()

    assert payload["schema_version"] == CONCEPT_WIKI_SCHEMA
    assert payload["title"] == "Knowledge Compiler"
    assert payload["description"] == "Builds governed knowledge releases."
    assert payload["sections"][0]["section_id"] == "concepts/compiler#overview"
    assert payload["sections"][0]["source_viewer_ids"]
    assert payload["relationships"] == [
        {
            "edge_id": "edge_1",
            "relation_type": "supports",
            "direction": "outbound",
            "neighbor_concept_id": "concepts/agent",
            "neighbor_title": "Agent",
            "confidence": 0.91,
            "generated_inverse": False,
        }
    ]
    assert len(payload["source_viewers"]) == 1
    assert payload["source_viewers"][0]["citations"][0]["claim_ids"] == ["claim-1"]
    assert payload["authority"] == {
        "retrieval_authority": "lexical",
        "graph_authority": "read_only",
        "production_retrieval": "lexical",
        "semantic_serving_enabled": False,
        "semantic_promotion_enabled": False,
        "hybrid_retrieval_enabled": False,
        "source_mutation_authorized": False,
        "raw_evidence_exposed": False,
    }
    serialized = page.model_dump_json()
    assert "query_vector" not in serialized
    assert "evaluation" not in serialized


def test_concept_wiki_rejects_cross_release_graph_context() -> None:
    neighborhood = _neighborhood()
    neighborhood["release"] = {"release_id": "different-release"}

    with pytest.raises(ValueError, match="release identity"):
        build_concept_wiki_page(
            _response(),
            concept_id="concepts/compiler",
            graph_neighborhood=neighborhood,
        )


def test_concept_wiki_requires_visible_public_search_result() -> None:
    with pytest.raises(ValueError, match="not present"):
        build_concept_wiki_page(_response(), concept_id="concepts/missing")
