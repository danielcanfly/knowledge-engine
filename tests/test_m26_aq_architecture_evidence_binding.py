from __future__ import annotations

from types import SimpleNamespace

from knowledge_engine import m25_blog_candidate_release as release
from knowledge_engine import m26_aq_semantic_contract as semantic_contract
from knowledge_engine import m26_pa7_arbitrary_query_runtime as runtime
from knowledge_engine import m26_pa7_semantic_closure_runtime as closure


def _article_document(title: str, concept_id: str, source_id: str) -> dict[str, object]:
    return {
        "title": title,
        "section_title": "Article overview",
        "body": title,
        "excerpt": title,
        "concept_id": concept_id,
        "section_id": concept_id,
        "source_id": source_id,
    }


def _graph_bundle() -> SimpleNamespace:
    part_1 = "concept-part-1"
    part_2 = "concept-part-2"
    part_10 = "concept-part-10"
    return SimpleNamespace(
        lexical_index={
            "documents": [
                _article_document("Widget Harness Part 01", part_1, "widget-harness-part-1"),
                _article_document("Widget Harness Part 02", part_2, "widget-harness-part-2"),
                _article_document("Widget Harness Part 10", part_10, "widget-harness-part-10"),
            ]
        },
        graph_v2={
            "edges": [
                {
                    "edge_id": "edge-wrong-high-confidence",
                    "source": part_1,
                    "target": part_10,
                    "relation_type": "precedes",
                    "confidence": 0.99,
                },
                {
                    "edge_id": "edge-correct",
                    "source": part_1,
                    "target": part_2,
                    "relation_type": "precedes",
                    "confidence": 0.80,
                },
            ]
        },
    )


def test_natural_series_order_repairs_lexicographic_precedes_edges() -> None:
    article_ids = ["series-part-1", "series-part-10", "series-part-2"]
    node_ids = {article_id: f"node-{article_id}" for article_id in article_ids}
    article_by_id = {
        article_id: {
            "article_id": article_id,
            "slug": article_id,
            "title": article_id.replace("-", " ").title(),
            "series_id": "series_example",
            "series_order": None,
        }
        for article_id in article_ids
    }
    pack = {
        "article_by_id": article_by_id,
        "source_bytes": {},
        "nodes": [
            {
                "node_id": node_ids[article_id],
                "node_type": "Article",
                "source_article_id": article_id,
            }
            for article_id in article_ids
        ],
        "edges": [
            {
                "edge_id": "old-1-10",
                "source": node_ids["series-part-1"],
                "target": node_ids["series-part-10"],
                "type": "precedes",
            },
            {
                "edge_id": "old-10-2",
                "source": node_ids["series-part-10"],
                "target": node_ids["series-part-2"],
                "type": "precedes",
            },
        ],
    }

    normalized = release.normalize_pack_series_precedes(pack)
    precedes = [
        (edge["source"], edge["target"])
        for edge in normalized["edges"]
        if edge.get("type") == "precedes"
    ]

    assert set(precedes) == {
        (node_ids["series-part-1"], node_ids["series-part-2"]),
        (node_ids["series-part-2"], node_ids["series-part-10"]),
    }
    assert len(precedes) == 2


def test_named_graph_edge_prefers_exact_endpoints_over_high_confidence_distractor() -> None:
    question = (
        "The production graph says Widget Harness Part 1 precedes Part 2. "
        "What can we safely infer from that edge?"
    )
    edge = runtime._named_question_graph_edge(_graph_bundle(), question)
    assert edge is not None
    assert edge["edge_id"] == "edge-correct"


def test_named_graph_edge_fails_closed_when_exact_endpoint_edge_is_absent() -> None:
    bundle = _graph_bundle()
    bundle.graph_v2["edges"] = [bundle.graph_v2["edges"][0]]
    question = (
        "The production graph says Widget Harness Part 1 precedes Part 2. "
        "What can we safely infer from that edge?"
    )

    assert runtime._named_question_graph_edge(bundle, question) is None
    assert runtime._first_authoritative_edge([], [], bundle, question=question) is None


def test_fast_candidate_rejects_wrong_named_graph_edge_even_when_citation_exists() -> None:
    question = (
        "Does the precedes edge between Widget Harness Part 1 and Part 2 "
        "prove that Part 1 depends on Part 2?"
    )
    wrong_evidence = {
        "evidence_id": "e-wrong",
        "evidence_type": "graph_edge",
        "locator_id": "loc-wrong",
        "source_id": "graph:wrong",
        "source_identity": "graph:wrong",
        "section_id": "edge-wrong",
        "concept_id": "concept-part-1",
        "edge_source": "concept-part-1",
        "edge_target": "concept-part-10",
        "edge_source_label": "Widget Harness Part 01",
        "edge_target_label": "Widget Harness Part 10",
        "relation_type": "precedes",
        "passage_text": "Widget Harness Part 01 precedes Widget Harness Part 10.",
        "passage_text_sha256": "x",
    }
    provider_output = {
        "parsed": {
            "status": "answer",
            "answer_text": "The edge supports ordering only, not dependency.",
            "citation_ids": ["e-wrong"],
            "abstention_reason": "",
        }
    }

    assert (
        runtime._validate_fast_provider_candidate(
            question=question,
            selected_evidence=[wrong_evidence],
            provider_output=provider_output,
        )
        is None
    )


def test_cross_source_truth_question_uses_mechanism_facets_not_generic_need() -> None:
    question = (
        "Why isn't simply increasing top_k enough when a question needs both "
        "database facts and document evidence?"
    )
    contract = runtime._question_contract(
        question=question,
        intent_class="direct_grounded_knowledge",
    )
    facet_ids = {
        str(item["facet_id"])
        for item in contract["required_facets"]
    }

    assert {
        "source_truth_routing",
        "cross_source_composition",
        "top_k_boundary",
    }.issubset(facet_ids)
    assert "need_relation" not in facet_ids


def test_cross_source_truth_facets_bind_to_source_backed_passage() -> None:
    passage = (
        "The pattern router chooses document RAG or SQL or API tool according to the "
        "source of truth. Once a query crosses retrieval patterns, first query SQL, "
        "then search policy documents. One retrieval pass cannot carry the task. "
        "The fix is not raising top_k; the fix is a bounded multi-step workflow."
    )
    question = (
        "Why isn't simply increasing top_k enough when a question needs both "
        "database facts and document evidence?"
    )
    facets = runtime._direct_question_facets(question)
    by_id = {str(item["facet_id"]): item for item in facets}

    for facet_id in (
        "source_truth_routing",
        "cross_source_composition",
        "top_k_boundary",
    ):
        assert runtime._direct_facet_text_matches(by_id[facet_id], passage)


def test_cross_source_truth_facets_bridge_into_semantic_requirements() -> None:
    question = (
        "Why isn't simply increasing top_k enough when a question needs both "
        "database facts and document evidence?"
    )
    requirements = semantic_contract.derive_semantic_requirements(
        question,
        "direct_grounded_knowledge",
    )
    requirement_ids = {item.requirement_id for item in requirements}

    assert {
        "source_truth_routing",
        "cross_source_composition",
        "top_k_boundary",
    }.issubset(requirement_ids)


def test_single_part_question_strips_interrogative_prefix() -> None:
    assert runtime._named_question_entities("What does Part 2 establish?") == ["Part 2"]


def _cross_source_evidence(text: str, evidence_id: str = "ev-cross-source") -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "locator_id": f"loc-{evidence_id}",
        "evidence_type": "passage",
        "source_id": "source-cross-source",
        "source_identity": "source-cross-source",
        "section_id": "section-cross-source",
        "concept_id": "concept-cross-source",
        "title": "Query Router and Agentic RAG",
        "section_title": "Routing has two layers: mode router and pattern router",
        "passage_text": text,
        "channels": ["required_facet_coverage"],
        "retrieval_metadata": {},
    }


def test_strong_top_k_requirement_rejects_generic_overlap() -> None:
    question = (
        "Why isn't simply increasing top_k enough when a question needs both "
        "database facts and document evidence?"
    )
    requirement = next(
        item
        for item in semantic_contract.derive_semantic_requirements(
            question,
            "direct_grounded_knowledge",
        )
        if item.requirement_id == "top_k_boundary"
    )
    generic = _cross_source_evidence(
        "A workflow can carry evidence and retrieval references between checkpoints.",
        "ev-generic",
    )
    exact = _cross_source_evidence(
        "One retrieval pass cannot carry the task. "
        "The fix is not raising `top_k`; the fix is a bounded multi-step workflow.",
        "ev-exact",
    )

    assert not closure._selected_evidence_supports_requirement(requirement, generic)
    assert closure._selected_evidence_supports_requirement(requirement, exact)


def test_explanatory_facet_inherits_material_support_only() -> None:
    question = (
        "Why isn't simply increasing top_k enough when a question needs both "
        "database facts and document evidence?"
    )
    requirements = semantic_contract.derive_semantic_requirements(
        question,
        "direct_grounded_knowledge",
    )
    evidence = [
        _cross_source_evidence(
            "The pattern router chooses document RAG or SQL/API tools according to "
            "the source of truth. Once a query crosses retrieval patterns, first query "
            "SQL, then search policy documents. One retrieval pass cannot carry the task. "
            "The fix is not raising `top_k`; the fix is a bounded multi-step workflow."
        )
    ]

    classification = closure._facet_support_classification(
        requirements=requirements,
        evidence=evidence,
    )
    by_id = {str(item["facet_id"]): item for item in classification}
    material_ids = {
        str(evidence_id)
        for facet_id in (
            "source_truth_routing",
            "cross_source_composition",
            "top_k_boundary",
        )
        for evidence_id in by_id[facet_id]["supporting_evidence_ids"]
    }

    assert material_ids == {"ev-cross-source"}
    assert by_id["explanatory_answer"]["support_state"] == "SUPPORTED"
    assert by_id["explanatory_answer"]["support_mode"] == "composite_structural_binding"
    assert by_id["explanatory_answer"]["supporting_evidence_ids"] == [
        "ev-cross-source"
    ]


def test_facet_local_top_k_quote_is_reused_by_claim_binding() -> None:
    question = (
        "Why isn't simply increasing top_k enough when a question needs both "
        "database facts and document evidence?"
    )
    requirements = semantic_contract.derive_semantic_requirements(
        question,
        "direct_grounded_knowledge",
    )
    evidence = [
        _cross_source_evidence(
            "The pattern router chooses document RAG or SQL/API tools according to "
            "the source of truth. Once a query crosses retrieval patterns, first query "
            "SQL, then search policy documents, then assemble a risk explanation. "
            "One retrieval pass cannot carry the task. "
            "The fix is not raising `top_k`; the fix is a bounded multi-step workflow."
        )
    ]
    classification = closure._facet_support_classification(
        requirements=requirements,
        evidence=evidence,
    )
    _payload, _ledger, label_map, snippet_map, slots = (
        closure._facet_local_provider_payload(
            question=question,
            intent_class="direct_grounded_knowledge",
            evidence=evidence,
            requirements=requirements,
            support_classification=classification,
            repair=False,
            previous_failures=[],
        )
    )
    top_k_slot = next(slot for slot in slots if slot["facet_id"] == "top_k_boundary")
    top_k_quote = top_k_slot["evidence"][0]["text"]

    assert "not raising `top_k`" in top_k_quote
    assert "bounded multi-step workflow" in top_k_quote

    drafts = {
        "claims": [
            {
                "slot_id": slot["slot_id"],
                "text": f"Supported prose for {slot['facet_id']}.",
                "claim_type": "EVIDENCE_SYNTHESIS",
            }
            for slot in slots
        ],
        "model_explanations": [],
    }
    candidate = closure._runtime_bound_facet_local_candidate(
        drafts=drafts,
        slots=slots,
        label_map=label_map,
        snippet_map=snippet_map,
        question=question,
        intent_class="direct_grounded_knowledge",
        unresolved_required_ids=[],
    )
    top_k_claim = next(
        claim
        for claim in candidate["claims"]
        if "top_k_boundary" in claim["facet_ids"]
    )

    assert top_k_claim["support_refs"][0]["exact_quote"] == top_k_quote
