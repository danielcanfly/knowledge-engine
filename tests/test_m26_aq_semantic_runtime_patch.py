from __future__ import annotations

import json
from types import SimpleNamespace

from knowledge_engine import m26_aq_semantic_runtime_patch as base_patch
from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy_runtime
from knowledge_engine import m26_pa7_semantic_closure_runtime as semantic_runtime
from knowledge_engine.m26_aq_semantic_runtime_patch_v2 import (
    _best_exact_edge,
    _canonical_named_concepts,
    _provider_integrity_safe_synthesize,
    _repairable_verifier_failure,
    _runtime_bound_semantic_repair_v2,
    _semantic_answer_text_v2,
    _verified_repair_support_items,
)
from knowledge_engine.m26_pa7_semantic_closure_runtime import (
    _compact_provider_payload,
    _semantic_requirements,
    _visible_semantic_failures,
)


def _ids(question: str, intent: str = "direct_grounded_knowledge") -> set[str]:
    return {item.requirement_id for item in _semantic_requirements(question, intent)}


def test_runtime_bound_semantic_repair_v2_is_installed() -> None:
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
            _doc(
                "article_part_10",
                "daniel_blog_en__harness-theory-part-10",
                "Harness Theory Part 10",
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


def test_named_part_resolution_fails_closed_without_canonical_identity() -> None:
    runtime = _fake_runtime(
        [
            _doc(
                "article_part_9",
                "daniel_blog_en__harness-theory-part-9",
                "Harness Theory Part 9",
                "This text mentions Harness Theory Part 1 without being it.",
            )
        ]
    )
    bundle = SimpleNamespace(documents=runtime.legacy.documents, graph_v2={"edges": []})

    assert _canonical_named_concepts(runtime, bundle, "Harness Theory Part 1") == set()


def test_background_run_repair_covers_full_control_lifecycle_paraphrase() -> None:
    question = (
        "When a browser drops while a server job continues, which controls preserve "
        "trust from intake through final status reattachment?"
    )
    requirements = _semantic_requirements(question, "complementary_synthesis")
    assert {
        "admission_policy",
        "durable_state",
        "completion_verification",
        "observability",
    }.issubset({item.requirement_id for item in requirements})

    answer = _semantic_answer_text_v2(question, requirements)

    assert "R3-Q" not in answer
    assert not _visible_semantic_failures(answer, requirements, question)


def test_provider_integrity_repair_avoids_malformed_second_attempt() -> None:
    question = (
        "Sketch a controlled architecture for a complex request that needs different "
        "sources, persisted progress, parallel research branches, verification, and "
        "human approval."
    )
    requirements = _semantic_requirements(question, "complementary_synthesis")
    evidence = [
        _evidence(
            "ev_control_a",
            "source-control-a",
            "Source selection routes work to different sources. Persisted progress "
            "is durable state. Parallel research branches keep work concurrent.",
        ),
        _evidence(
            "ev_control_b",
            "source-control-b",
            "Parallel research branches join at a verification gate. Human approval "
            "is the final authority gate before release.",
        ),
    ]
    provider = _OneShotIncompleteProvider()

    answer, closure = _provider_integrity_safe_synthesize(
        runtime=semantic_runtime,
        legacy=legacy_runtime,
        question=question,
        trace_id="trace_provider_integrity",
        intent_class="complementary_synthesis",
        evidence=evidence,
        provider_client=provider,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )

    attempts = answer["multi_evidence_verification"]["provider_attempt_telemetry"]
    assert provider.calls == 1
    assert len(attempts) == 1
    assert attempts[0]["parse_telemetry"]["parse_ok"] is True
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["material_claim_support_verified"] is True
    assert answer["citation_locator_valid"] is True
    assert answer["unsupported_accepted_claims"] == 0
    assert closure["failures"] == []
    assert all(item.get("supported") is True for item in closure["support_proof"])
    assert not _visible_semantic_failures(answer["answer_text"], requirements, question)


def test_repairable_verifier_failure_codes_are_routed() -> None:
    assert _repairable_verifier_failure("M26-PA7-ME-029")
    assert _repairable_verifier_failure("M26-PA7-ME-030")
    assert _repairable_verifier_failure("M26-PA7-ME-034")
    assert not _repairable_verifier_failure("M26-PA7-ME-007")


def test_parse_failure_remains_visible_and_fails_closed() -> None:
    question = (
        "Sketch a controlled architecture for a complex request that needs different "
        "sources, persisted progress, parallel research branches, verification, and "
        "human approval."
    )
    requirements = _semantic_requirements(question, "complementary_synthesis")
    evidence = [
        _evidence(
            "ev_a",
            "source-a",
            "Source selection routes work to different sources and persisted progress "
            "is durable state.",
        ),
        _evidence(
            "ev_b",
            "source-b",
            "Parallel research branches join at a verification gate with human approval.",
        ),
    ]
    provider = _MalformedProvider()

    answer, closure = _provider_integrity_safe_synthesize(
        runtime=semantic_runtime,
        legacy=legacy_runtime,
        question=question,
        trace_id="trace_parse_failure",
        intent_class="complementary_synthesis",
        evidence=evidence,
        provider_client=provider,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )

    attempts = answer["multi_evidence_verification"]["provider_attempt_telemetry"]
    assert provider.calls == 1
    assert attempts[0]["parse_telemetry"]["parse_ok"] is False
    assert answer["terminal_status"] == "safe_abstention"
    assert closure["failures"]


def test_local_repair_cannot_self_certify_unsupported_requirements() -> None:
    question = (
        "When a browser disconnects but the job continues, what control plane keeps "
        "trust from admission through final status reattachment?"
    )
    requirements = _semantic_requirements(question, "complementary_synthesis")
    evidence = [
        _evidence(
            "ev_admission_only",
            "source-admission",
            "Admission and effective policy decide whether the run may start.",
        )
    ]

    selected, support_proof, support_failures = _verified_repair_support_items(
        runtime=semantic_runtime,
        evidence=evidence,
        requirements=requirements,
        question=question,
        intent_class="complementary_synthesis",
    )

    assert selected == []
    assert support_failures
    assert any(item.get("supported") is not True for item in support_proof)


def test_heldout_router_replanner_contrast_terms_are_visible() -> None:
    question = (
        "A dispatcher picks the first capability, but a planner later changes unfinished "
        "steps after the world proves the assumption false. What is the difference?"
    )
    answer = (
        "The router handles the initial path and capability choice. Adaptive replanning "
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
        "capability constraints. Inside that chosen path, the DAG orders dependent steps "
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
        "No. A precedes B is an ordering or navigation relation; it does not prove a "
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
        "gates. The replanner may change remaining steps when assumptions become invalid, "
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
        "Start with source selection that routes the request to the relevant sources. Store "
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
        "Obsidian is the human Markdown vault authoring and inspection surface. Graphology "
        "is the graph data model and processing layer, while Sigma.js renders the graph for "
        "visual interaction. The source of trust is the canonical source/provenance artifact "
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


class _OneShotIncompleteProvider:
    def __init__(self) -> None:
        self.calls = 0

    def call(self, payload: object, call_class: str) -> dict[str, object]:
        del payload
        self.calls += 1
        assert call_class == "aq_semantic_closure"
        return {
            "text": json.dumps(
                {
                    "status": "answer",
                    "answer": "Use source selection for the request.",
                    "used": ["e1"],
                }
            ),
            "call_class": call_class,
            "stop_reason": "end_turn",
            "content_block_types": ["text"],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "cost_usd": "0",
            "latency_ms": 1,
            "response_id": "fake-response-id",
        }


class _MalformedProvider:
    def __init__(self) -> None:
        self.calls = 0

    def call(self, payload: object, call_class: str) -> dict[str, object]:
        del payload, call_class
        self.calls += 1
        return {
            "text": "not json at all",
            "call_class": "aq_semantic_closure",
            "stop_reason": "end_turn",
            "content_block_types": ["text"],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "cost_usd": "0",
            "latency_ms": 1,
            "response_id": "malformed-response-id",
        }


def _evidence(evidence_id: str, source_identity: str, passage_text: str) -> dict[str, str]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "passage",
        "source_identity": source_identity,
        "source_id": source_identity,
        "locator_id": f"loc_{evidence_id}",
        "title": source_identity,
        "section_title": source_identity,
        "concept_id": f"concept_{evidence_id}",
        "passage_text": passage_text,
    }


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
