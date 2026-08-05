from __future__ import annotations

from types import SimpleNamespace

from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime


def _document(*, title: str, concept_id: str, source_id: str) -> dict[str, str]:
    return {
        "title": title,
        "section_title": "Article overview",
        "description": "",
        "body": f"{title} is an article in the Widget Harness series.",
        "excerpt": "",
        "concept_id": concept_id,
        "section_id": concept_id,
        "source_id": source_id,
    }


def _bundle() -> SimpleNamespace:
    part_1 = "concept-widget-part-1"
    part_2 = "concept-widget-part-2"
    part_10 = "concept-widget-part-10"
    return SimpleNamespace(
        lexical_index={
            "documents": [
                _document(
                    title="Widget Harness Part 1",
                    concept_id=part_1,
                    source_id="widget-harness-part-1",
                ),
                _document(
                    title="Widget Harness Part 2",
                    concept_id=part_2,
                    source_id="widget-harness-part-2",
                ),
                _document(
                    title="Widget Harness Part 10",
                    concept_id=part_10,
                    source_id="widget-harness-part-10",
                ),
            ]
        },
        graph_v2={
            "edges": [
                {
                    "edge_id": "edge-correct-part-1-to-part-2",
                    "source": part_1,
                    "target": part_2,
                    "relation_type": "precedes",
                    "confidence": 0.80,
                },
                {
                    "edge_id": "edge-prefix-collision-part-10-to-part-2",
                    "source": part_10,
                    "target": part_2,
                    "relation_type": "precedes",
                    "confidence": 0.99,
                },
            ]
        },
    )


def test_part_endpoint_identity_is_token_bounded_not_numeric_prefix() -> None:
    bundle = _bundle()
    question = (
        "If the relation graph records Widget Harness Part 1 as preceding Part 2, "
        "what can we safely infer from that edge?"
    )

    edge = runtime._exact_named_graph_edge(bundle, question)

    assert edge is not None
    assert edge["edge_id"] == "edge-correct-part-1-to-part-2"
    assert edge["source"] == "concept-widget-part-1"
    assert edge["target"] == "concept-widget-part-2"
    assert edge["relation_type"] == "precedes"


def test_unknown_part_endpoint_does_not_fuzzy_bind_to_existing_part() -> None:
    bundle = _bundle()
    question = "Does Widget Harness Part 99 precede Part 2 in the relation graph?"

    assert runtime._exact_named_graph_edge(bundle, question) is None
