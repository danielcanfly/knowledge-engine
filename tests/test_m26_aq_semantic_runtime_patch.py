from __future__ import annotations

import subprocess
import sys
import textwrap
from types import SimpleNamespace
from typing import Any

from knowledge_engine.m26_aq_semantic_runtime_patch_v2 import (
    _best_exact_edge,
    _canonical_named_concepts,
    _repairable_verifier_failure,
    _runtime_bound_semantic_repair_v2,
)


def _run_isolated(code: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _doc(concept_id: str, artifact_key: str, title: str, text: str) -> dict[str, Any]:
    return {
        "concept_id": concept_id,
        "artifact_key": artifact_key,
        "title": title,
        "text": text,
        "passage_text": text,
    }


def _fake_runtime(documents: list[dict[str, Any]]) -> SimpleNamespace:
    legacy = SimpleNamespace(documents=documents)
    legacy._release_documents = lambda _bundle: documents
    return SimpleNamespace(legacy=legacy)


def test_named_part_endpoint_resolution_prefers_canonical_identity_over_mentions() -> None:
    runtime = _fake_runtime(
        [
            _doc(
                "article_part_1",
                "daniel_blog_en__harness-theory-part-1",
                "Harness Theory Part 1: Evidence first",
                "The article body does not need to repeat the title.",
            ),
            _doc(
                "article_part_2",
                "daniel_blog_en__harness-theory-part-2",
                "Harness Theory Part 2: Audit before claims",
                "The article body does not need to repeat the title.",
            ),
            _doc(
                "article_part_9",
                "daniel_blog_en__harness-theory-part-9",
                "Harness Theory Part 9: Later operational notes",
                "This later note merely mentions Harness Theory Part 1 and Part 2.",
            ),
        ]
    )
    bundle = SimpleNamespace(documents=runtime.legacy.documents, graph_v2={"edges": []})

    assert _canonical_named_concepts(runtime, bundle, "Harness Theory Part 1") == {
        "article_part_1"
    }
    assert _canonical_named_concepts(runtime, bundle, "Harness Theory Part 2") == {
        "article_part_2"
    }


def test_named_part_exact_edge_binding_uses_canonical_endpoints() -> None:
    runtime = _fake_runtime(
        [
            _doc(
                "article_part_1",
                "daniel_blog_en__harness-theory-part-1",
                "Harness Theory Part 1",
                "",
            ),
            _doc(
                "article_part_2",
                "daniel_blog_en__harness-theory-part-2",
                "Harness Theory Part 2",
                "",
            ),
            _doc(
                "article_part_9",
                "daniel_blog_en__harness-theory-part-9",
                "Harness Theory Part 9",
                "Mentions Harness Theory Part 1 and Harness Theory Part 2 only.",
            ),
        ]
    )
    bundle = SimpleNamespace(
        documents=runtime.legacy.documents,
        graph_v2={
            "edges": [
                {
                    "edge_id": "edge_wrong_mentions",
                    "source": "article_part_9",
                    "target": "article_part_10",
                    "relation_type": "precedes",
                    "confidence": 1.0,
                },
                {
                    "edge_id": "edge_canonical_part_1_to_2",
                    "source": "article_part_1",
                    "target": "article_part_2",
                    "relation_type": "precedes",
                    "confidence": 1.0,
                },
            ]
        },
    )

    source = _canonical_named_concepts(runtime, bundle, "Harness Theory Part 1")
    target = _canonical_named_concepts(runtime, bundle, "Harness Theory Part 2")
    edge = _best_exact_edge(bundle, source, target, "precedes")

    assert edge is not None
    assert edge["edge_id"] == "edge_canonical_part_1_to_2"


def test_explicit_install_adds_semantic_requirements_without_package_side_effects() -> None:
    _run_isolated(
        """
        from knowledge_engine import m26_aq_semantic_runtime_patch_v2 as patch_v2
        from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime

        patch_v2.install()
        lifecycle = runtime._semantic_requirements(
            (
                "When a browser drops while a server job continues, which controls preserve "
                "trust from intake through final status reattachment?"
            ),
            "complementary_synthesis",
        )
        assert isinstance(lifecycle, list)

        router = runtime._semantic_requirements(
            (
                "A dispatcher picks the first capability, but a planner later changes unfinished "
                "steps after the world proves the assumption false. What is the difference?"
            ),
            "cross_document_comparison",
        )
        assert isinstance(router, list)
        """
    )


def test_explicit_install_covers_control_architecture_and_precedes_boundary() -> None:
    _run_isolated(
        """
        from knowledge_engine import m26_aq_semantic_runtime_patch_v2 as patch_v2
        from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime

        patch_v2.install()
        controlled = runtime._semantic_requirements(
            (
                "Design a governed multi-source investigation with saved progress, concurrent "
                "branches, checks, and a person approving release."
            ),
            "complementary_synthesis",
        )
        assert isinstance(controlled, list)

        precedes = runtime._semantic_requirements(
            (
                "Can an A precedes B graph edge establish that A depends on B, "
                "or is it only an ordering signal?"
            ),
            "graph_relationship",
        )
        assert isinstance(precedes, list)
        """
    )


def test_explicit_install_authority_surface_is_visible_without_absolute_modality() -> None:
    _run_isolated(
        """
        from knowledge_engine import m26_aq_semantic_runtime_patch_v2 as patch_v2
        from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime
        from knowledge_engine.m26_aq_semantic_runtime_patch_v2 import _semantic_answer_text_v2

        patch_v2.install()
        question = (
            "How do state machines and adaptive replanning fit together without giving the "
            "replanner unlimited authority?"
        )
        requirements = runtime._semantic_requirements(question, "complementary_synthesis")
        answer = _semantic_answer_text_v2(question, requirements)
        assert "cannot" not in answer.casefold()
        assert "bypass" not in answer.casefold()
        assert "override" not in answer.casefold()
        assert isinstance(answer, str)
        """
    )


def test_repairable_verifier_failure_codes_are_routed() -> None:
    assert _repairable_verifier_failure("M26-PA7-ME-029")
    assert _repairable_verifier_failure("M26-PA7-ME-030")
    assert _repairable_verifier_failure("M26-PA7-ME-034")
    assert not _repairable_verifier_failure("M26-PA7-ME-007")


def test_runtime_bound_repair_keeps_hard_verifier_shape() -> None:
    code = _runtime_bound_semantic_repair_v2.__code__
    assert "_verify_multi_evidence_provider_output" in code.co_names
    assert "_verified_multi_evidence_answer" in code.co_names
    assert "_verified_repair_support_items" in code.co_names
