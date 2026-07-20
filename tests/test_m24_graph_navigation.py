from __future__ import annotations

import pytest

from knowledge_engine.m24_graph_navigation import (
    GRAPH_NAVIGATION_SCHEMA,
    build_graph_navigation_state,
)


def _overview() -> dict:
    return {
        "schema_version": "knowledge-engine-graph-api/v1",
        "release": {"release_id": "20260720T000000Z-m24"},
        "read_only": True,
        "nodes": [
            {
                "concept_id": "concepts/agent",
                "title": "Agent",
                "description": "Executes tasks.",
                "type": "concept",
                "audience": "public",
                "tags": ["agents"],
            },
            {
                "concept_id": "concepts/compiler",
                "title": "Knowledge Compiler",
                "description": "Builds governed releases.",
                "type": "system",
                "audience": "public",
                "tags": ["runtime"],
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


def _focus() -> dict:
    return {
        **_overview(),
        "root_concept_id": "concepts/compiler",
        "depth": 1,
        "truncated": False,
    }


def test_graph_navigation_state_is_read_only_and_renderer_neutral() -> None:
    state = build_graph_navigation_state(
        _overview(),
        selected_concept_id="concepts/compiler",
        focus_neighborhood=_focus(),
    )
    payload = state.model_dump()

    assert payload["schema_version"] == GRAPH_NAVIGATION_SCHEMA
    assert payload["selected_concept_id"] == "concepts/compiler"
    assert payload["focus_neighbor_ids"] == ["concepts/agent"]
    assert payload["nodes"][1]["selected"] is True
    assert payload["nodes"][0]["focus_neighbor"] is True
    assert payload["edges"][0]["focus_edge"] is True
    assert payload["available_actions"] == [
        "select_node",
        "open_concept",
        "open_source_viewer",
    ]
    assert payload["authority"] == {
        "graph_authority": "read_only",
        "retrieval_authority": "lexical",
        "production_retrieval": "lexical",
        "semantic_serving_enabled": False,
        "semantic_promotion_enabled": False,
        "hybrid_retrieval_enabled": False,
        "renderer_mutation_authorized": False,
        "source_mutation_authorized": False,
    }
    assert "query_vector" not in state.model_dump_json()
    assert "evaluation" not in state.model_dump_json()


def test_graph_navigation_rejects_renderer_fields_and_invisible_selection() -> None:
    overview = _overview()
    overview["nodes"][0]["x"] = 1
    with pytest.raises(ValueError, match="renderer-neutral"):
        build_graph_navigation_state(overview)

    with pytest.raises(ValueError, match="visible"):
        build_graph_navigation_state(_overview(), selected_concept_id="concepts/missing")


def test_graph_navigation_rejects_cross_release_focus_context() -> None:
    focus = _focus()
    focus["release"] = {"release_id": "different-release"}

    with pytest.raises(ValueError, match="release identity"):
        build_graph_navigation_state(
            _overview(),
            selected_concept_id="concepts/compiler",
            focus_neighborhood=focus,
        )
