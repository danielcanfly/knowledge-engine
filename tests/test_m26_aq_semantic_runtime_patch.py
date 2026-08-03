from __future__ import annotations

from types import SimpleNamespace

from knowledge_engine import m26_aq_semantic_runtime_patch as base_patch
from knowledge_engine.m26_aq_semantic_runtime_patch_v2 import (
    _best_exact_edge,
    _canonical_named_concepts,
    _runtime_bound_semantic_repair_v2,
)
from knowledge_engine.m26_pa7_semantic_closure_runtime import (
    _compact_provider_payload,
    _semantic_requirements,
    _visible_semantic_failures,
)


def _ids(question: str, intent: str = "direct_grounded_knowledge") -> set[str]:
    return {item.requirement_id for item in _semantic_requirements(question, intent)}


def test_runtime_bound_semantic_repair_v2_preserves_base_repair() -> None:
    original = base_patch._m26_aq_original_runtime_bound_semantic_repair
    assert original is not _runtime_bound_semantic_repair_v2
    assert base_patch._runtime_bound_semantic_repair is _runtime_bound_semantic_repair_v2


def test_named_part_endpoint_resolution_prefers_canonical_identity_over_mentions() -> None:
    runtime = _fake_runtime(
        [
            _doc(
                "article_part_1",
                "daniel_blog_en__harness-theory-part-1",
                "Harness Theory Part 1: Evidence first",
                "The article itself does not need to mention its own title in body.",
            ),
            _doc(
                "article_part_2",
                "daniel_blog_en__harness-theory-part-2",
                "Harness Theory Part 2: Audit before claims",
                "The article itself does not need to mention its own title in body.",
            ),
            _doc(
                "article_part_9",
                "daniel_blog_en__harness-theory-part-9",
                "Harness Theory Part 9: Later operational notes",
                (
                    "This later article merely mentions Harness Theory Part 1 "
                    "and Harness Theory Part 2."
                ),
            ),
            _doc(
                "article_part_10",
                "daniel_blog_en__harness-theory-part-10",
                "Harness Theory Part 10: Later closure notes",
                (
                    "Another distractor mention of Harness Theory Part 1 "
                    "and Harness Theory Part 2."
                ),
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
                "Mentions Harness Theory Part 1 and Harness Theory Part 2 only as references.",
            ),
            _doc(
                "article_part_10",
                "daniel_blog_en__harness-theory-part-10",
                "Harness Theory Part 10",
                "Mentions Harness Theory Part 1 and Harness Theory Part 2 only as references.",
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


def test_named_part_resolution_fails_closed_without_canonical_identity() -> None:
    runtime = _fake_runtime(
        [
            _doc(
                "article_part_9",
                "daniel_blog_en__harness-theory-part-9",
                "Harness Theory Part 9",
                "This text mentions Harness Theory Part 1 without being that canonical article.",
            )
        ]
    )
    bundle = SimpleNamespace(documents=runtime.legacy.documents, graph_v2={"edges": []})

    assert _canonical_named_concepts(runtime, bundle, "Harness Theory Part 1") == set()


def test_heldout_router_replanner_contrast_terms_are_visible() -> None:
    question = (
        "A dispatcher picks the first capability, but a planner later changes unfinished "
        "steps after the world proves the assumption false.  What is the difference?"
    )
    answer = (
        "The router handles the initial path and capability choice.  Adaptive replanning "
        "is different because it later changes the remaining work after evidence "
        "invalidates the assumption."
    )
    requirements = _semantic_requirements(question, "cross_document_comparison")
    assert {"initial_routing_role", "replanning_role", "role_contrast"}.issubset(
        {item.requirement_id for item in requirements}
    )
    assert not _visible_semantic_failures(answer, requirements, question)


def test_heldout_router_dag_composition_requires_both_jobs() -> None:
    question = "How should a query router and DAG cooperate inside an owner-only ask pipeline?"
    answer = (
        "The query router selects the route, path, mode, or capability under policy and "
        "capability constraints.  Inside that chosen path, the DAG orders dependent steps "
        "and parallel work so the same flow can execute and verify the route safely."
    )
    requirements = _semantic_requirements(question, "complementary_synthesis")
    assert {"router_role", "dag_role", "router_dag_composition"}.issubset(
        {item.requirement_id for item in requirements}
    )
    assert not _visible_semantic_failures(answer, requirements, question)


def test_heldout_precedes_false_premise_preserves_relation_boundary() -> None:
    question = (
        "Can an A precedes B graph edge establish that A depends on B, or is it only an "
        "ordering signal?"
    )
    answer = (
        "No.  A precedes B is an ordering or navigation relation; it does not prove a "
        "dependency, causality, implementation, or requirement relationship."
    )
    requirements = _semantic_requirements(question, "graph_relationship")
    assert {"ordering_semantics", "non_entailment"}.issubset(
        {item.requirement_id for item in requirements}
    )
    assert not _visible_semantic_failures(answer, requirements, question)


def test_heldout_state_machine_bounds_replanner_authority() -> None:
    question = "How can a replanner change a plan without escaping the state machine?"
    answer = (
        "The state machine defines legal transitions, permissions, policy, and approval "
        "gates.  The replanner may change remaining steps when assumptions become invalid, "
        "but it cannot override or bypass the state machine authority."
    )
    requirements = _semantic_requirements(question, "complementary_synthesis")
    assert {"state_machine_authority", "adaptive_replan", "authority_boundary"}.issubset(
        {item.requirement_id for item in requirements}
    )
    assert not _visible_semantic_failures(answer, requirements, question)


def test_heldout_controlled_architecture_requires_all_components() -> None:
    question = (
        "Design a governed multi-source investigation with saved progress, concurrent "
        "branches, checks, and a person approving release."
    )
    answer = (
        "Start with source selection that routes the request to the relevant sources.  Store "
        "persisted progress in durable state, run parallel branches for research work, close "
        "them through a verification gate, and require human approval before release."
    )
    requirements = _semantic_requirements(question, "complementary_synthesis")
    assert {
        "source_selection",
        "persisted_progress",
        "parallel_branches",
        "verification_gate",
        "human_approval",
    }.issubset({item.requirement_id for item in requirements})
    assert not _visible_semantic_failures(answer, requirements, question)


def test_heldout_obsidian_graphology_sigma_trust_anchor() -> None:
    question = "Separate Obsidian, Graphology, and Sigma.js, then name the trust anchor."
    answer = (
        "Obsidian is the human Markdown vault authoring and inspection surface.  Graphology "
        "is the graph data model and processing layer, while Sigma.js renders the graph for "
        "visual interaction.  The source of trust is the canonical source/provenance artifact "
        "authority, not any UI or graph library."
    )
    requirements = _semantic_requirements(question, "complementary_synthesis")
    assert {"obsidian_role", "graphology_role", "sigma_role", "trust_anchor"}.issubset(
        {item.requirement_id for item in requirements}
    )
    assert not _visible_semantic_failures(answer, requirements, question)


def test_compact_payload_exposes_semantic_contract_without_case_ids() -> None:
    question = "Can a precedes relation prove a dependency?"
    requirements = _semantic_requirements(question, "graph_relationship")
    payload, _, _ = _compact_provider_payload(
        question=question,
        intent_class="graph_relationship",
        evidence=[
            {
                "evidence_id": "ev1",
                "evidence_type": "graph_edge",
                "source_identity": "graph",
                "locator_id": "loc1",
                "relation_type": "precedes",
                "edge_source": "A",
                "edge_target": "B",
                "passage_text": "A precedes B in the graph.",
            }
        ],
        requirements=requirements,
        repair=True,
        previous_failures=["SEMANTIC_VISIBLE_MISSING:non_entailment"],
    )
    content = payload["messages"][0]["content"]
    assert "semantic_requirement_contract" in content
    assert "does not prove" in content
    assert "R3-Q" not in content


def _doc(concept_id: str, source_identity: str, title: str, body: str) -> dict[str, str]:
    return {
        "concept_id": concept_id,
        "section_id": concept_id,
        "source_identity": source_identity,
        "source_id": source_identity,
        "title": title,
        "section_title": title,
        "body": body,
        "excerpt": body,
    }


def _fake_runtime(documents: list[dict[str, str]]) -> SimpleNamespace:
    class FakeLegacy:
        @staticmethod
        def _release_documents(bundle: SimpleNamespace) -> list[dict[str, str]]:
            return list(bundle.documents)

        @staticmethod
        def _is_article_root_document(document: dict[str, str]) -> bool:
            return document.get("section_id") == document.get("concept_id")

        @staticmethod
        def _document_text(document: dict[str, str]) -> str:
            return str(document.get("body", ""))

    FakeLegacy.documents = documents
    return SimpleNamespace(legacy=FakeLegacy, documents=documents)
