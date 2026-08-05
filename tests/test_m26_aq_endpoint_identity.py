from __future__ import annotations

import subprocess
import sys
import textwrap


def test_part_endpoint_identity_is_token_bounded_in_fresh_runtime() -> None:
    probe = textwrap.dedent(
        r'''
        from types import SimpleNamespace
        from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime

        def document(title, concept_id, source_id):
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

        part_1 = "concept-widget-part-1"
        part_2 = "concept-widget-part-2"
        part_10 = "concept-widget-part-10"
        bundle = SimpleNamespace(
            lexical_index={
                "documents": [
                    document("Widget Harness Part 1", part_1, "widget-harness-part-1"),
                    document("Widget Harness Part 2", part_2, "widget-harness-part-2"),
                    document("Widget Harness Part 10", part_10, "widget-harness-part-10"),
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

        candidates = runtime._entity_concepts(bundle, "Widget Harness Part 1")
        assert candidates == {part_1}, candidates

        question = (
            "If the relation graph records Widget Harness Part 1 as preceding Part 2, "
            "what can we safely infer from that edge?"
        )
        edge = runtime._exact_named_graph_edge(bundle, question)
        assert edge is not None
        assert edge["edge_id"] == "edge-correct-part-1-to-part-2", edge
        assert edge["source"] == part_1
        assert edge["target"] == part_2
        assert edge["relation_type"] == "precedes"

        unknown = runtime._exact_named_graph_edge(
            bundle,
            "Does Widget Harness Part 99 precede Part 2 in the relation graph?",
        )
        assert unknown is None, unknown
        '''
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
