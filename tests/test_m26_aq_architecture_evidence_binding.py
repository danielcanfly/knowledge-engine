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


def test_exact_phrase_support_ignores_hidden_body_when_passage_is_bound() -> None:
    requirement = closure.SemanticRequirement(
        requirement_id="entity_production_router",
        instruction="Name and address production router explicitly.",
        evidence_terms=("production router",),
        visible_patterns=(r"production\\ router",),
        exact_phrase="production router",
    )
    misleading = {
        "evidence_id": "ev-hidden-body",
        "evidence_type": "passage",
        "title": "Router notes",
        "section_title": "What to log",
        "passage_text": "Log router input, selected route, policy version, and risk checks.",
        "body": "Earlier in this section: A production router needs an escape path.",
        "excerpt": "A production router needs an escape path.",
    }
    exact = {
        **misleading,
        "evidence_id": "ev-exact-passage",
        "section_title": "A production router needs an escape path",
        "passage_text": (
            "A production router needs an escape path for unknown or "
            "unsupported inputs."
        ),
    }

    assert not closure._selected_evidence_supports_requirement(requirement, misleading)
    assert closure._selected_evidence_supports_requirement(requirement, exact)


def test_exact_phrase_facet_local_quote_contains_required_identity() -> None:
    requirement = closure.SemanticRequirement(
        requirement_id="entity_production_router",
        instruction="Name and address production router explicitly.",
        evidence_terms=("production router",),
        visible_patterns=(r"production\\ router",),
        exact_phrase="production router",
    )
    item = {
        "evidence_id": "ev-router-passage",
        "evidence_type": "passage",
        "title": "The Atlas of Agent Design Patterns Part 2",
        "section_title": "What to log",
        "passage_text": (
            "What to log: router input, selected route, policy version, and risk checks. "
            "A production router needs an escape path for unknown or unsupported inputs."
        ),
    }

    quote = closure._facet_local_support_quote(item, requirement)

    assert "production router" in quote.casefold()
    assert "escape path" in quote.casefold()


def test_entity_identity_slot_compacts_into_material_claim_slot() -> None:
    entity_requirement = closure.SemanticRequirement(
        requirement_id="entity_production_router",
        instruction="Name and address production router explicitly.",
        evidence_terms=("production router",),
        visible_patterns=(r"production\\ router",),
        exact_phrase="production router",
    )
    decision_requirement = closure.SemanticRequirement(
        requirement_id="router_decision",
        instruction="Explain how the router selects a downstream path.",
        evidence_terms=("router", "path", "route"),
        visible_patterns=(r"router.{0,100}(?:path|route)",),
    )
    slots = [
        {
            "slot_id": "slot_1",
            "facet_id": "entity_production_router",
            "instruction": entity_requirement.instruction,
            "requirement": entity_requirement,
            "allowed_evidence_ids": ["ev-identity"],
            "allowed_evidence_labels": ["e1"],
            "support_quote_by_evidence_id": {
                "ev-identity": "A production router needs an escape path."
            },
            "evidence": [
                {
                    "context_index": 1,
                    "evidence_type": "passage",
                    "title": "Router",
                    "section": "Escape path",
                    "text": "A production router needs an escape path.",
                }
            ],
        },
        {
            "slot_id": "slot_2",
            "facet_id": "router_decision",
            "instruction": decision_requirement.instruction,
            "requirement": decision_requirement,
            "allowed_evidence_ids": ["ev-decision"],
            "allowed_evidence_labels": ["e2"],
            "support_quote_by_evidence_id": {
                "ev-decision": "A router selects one or more downstream paths."
            },
            "evidence": [
                {
                    "context_index": 1,
                    "evidence_type": "passage",
                    "title": "Router",
                    "section": "Choose path",
                    "text": "A router selects one or more downstream paths.",
                }
            ],
        },
    ]

    compacted = closure._compact_entity_identity_slots(slots)

    assert len(compacted) == 1
    slot = compacted[0]
    assert slot["facet_id"] == "router_decision"
    assert slot["co_facet_ids"] == ["entity_production_router"]
    assert "Explicitly name production router." in slot["instruction"]
    assert set(slot["allowed_evidence_ids"]) == {"ev-identity", "ev-decision"}


def test_entity_identity_slot_compacts_into_material_slot() -> None:
    entity_requirement = closure.SemanticRequirement(
        requirement_id="entity_production_router",
        instruction="Name and address production router explicitly.",
        evidence_terms=("production router",),
        visible_patterns=(r"production\\ router",),
        exact_phrase="production router",
    )
    decision_requirement = closure.SemanticRequirement(
        requirement_id="router_decision",
        instruction="Explain what the router inspects and how it selects a path.",
        evidence_terms=("router", "path"),
        visible_patterns=(r"router.{0,100}path",),
    )
    slots = [
        {
            "slot_id": "slot_1",
            "facet_id": "entity_production_router",
            "instruction": entity_requirement.instruction,
            "requirement": entity_requirement,
            "allowed_evidence_ids": ["ev-identity"],
            "allowed_evidence_labels": ["e1"],
            "support_quote_by_evidence_id": {
                "ev-identity": "A production router needs an escape path."
            },
            "evidence": [
                {
                    "context_index": 1,
                    "evidence_type": "passage",
                    "title": "Router",
                    "section": "Escape path",
                    "text": "A production router needs an escape path.",
                }
            ],
        },
        {
            "slot_id": "slot_2",
            "facet_id": "router_decision",
            "instruction": decision_requirement.instruction,
            "requirement": decision_requirement,
            "allowed_evidence_ids": ["ev-decision"],
            "allowed_evidence_labels": ["e2"],
            "support_quote_by_evidence_id": {
                "ev-decision": "A router selects one or more downstream paths."
            },
            "evidence": [
                {
                    "context_index": 1,
                    "evidence_type": "passage",
                    "title": "Router",
                    "section": "Choose the path",
                    "text": "A router selects one or more downstream paths.",
                }
            ],
        },
    ]

    compacted = closure._compact_entity_identity_slots(slots)

    assert len(compacted) == 1
    slot = compacted[0]
    assert slot["slot_id"] == "slot_1"
    assert slot["facet_id"] == "router_decision"
    assert slot["co_facet_ids"] == ["entity_production_router"]
    assert slot["instruction"].startswith("Explicitly name production router.")
    assert set(slot["allowed_evidence_ids"]) == {"ev-identity", "ev-decision"}
    assert any("production router" in item["text"] for item in slot["evidence"])


def test_compacted_entity_facet_is_covered_by_bound_claim() -> None:
    requirement = closure.SemanticRequirement(
        requirement_id="router_decision",
        instruction="Explain router selection.",
        evidence_terms=("router", "path"),
        visible_patterns=(r"router.{0,100}path",),
    )
    item = _cross_source_evidence(
        "A production router selects a downstream path from request features.",
        "ev-router",
    )
    slots = [
        {
            "slot_id": "slot_1",
            "facet_id": "router_decision",
            "co_facet_ids": ["entity_production_router"],
            "instruction": "Explicitly name production router. Explain router selection.",
            "requirement": requirement,
            "allowed_evidence_ids": ["ev-router"],
            "allowed_evidence_labels": ["e1"],
            "support_quote_by_evidence_id": {
                "ev-router": "A production router selects a downstream path from request features."
            },
            "evidence": [
                {
                    "context_index": 1,
                    "evidence_type": "passage",
                    "title": "Router",
                    "section": "Routing",
                    "text": "A production router selects a downstream path from request features.",
                }
            ],
        }
    ]
    candidate = closure._runtime_bound_facet_local_candidate(
        drafts={
            "claims": [
                {
                    "slot_id": "slot_1",
                    "text": "A production router selects a downstream path from request features.",
                    "claim_type": "EVIDENCE_FACT",
                }
            ],
            "model_explanations": [],
        },
        slots=slots,
        label_map={"e1": item},
        snippet_map={"ev-router": item["passage_text"]},
        question="What should a production router inspect?",
        intent_class="direct_grounded_knowledge",
        unresolved_required_ids=[],
    )

    claim = candidate["claims"][0]
    assert claim["facet_ids"] == ["router_decision", "entity_production_router"]
    assert claim["covers"] == ["router_decision", "entity_production_router"]


def test_fast_surface_rejects_unsolicited_internal_article_id() -> None:
    token = "article_deadbeefcafebabe"
    assert runtime._contains_internal_fragment_leak(
        f"The graph links {token} to another article.",
        "What does the graph relationship mean?",
    )
    assert not runtime._contains_internal_fragment_leak(
        f"{token} is the identifier you asked about.",
        f"What does {token} mean?",
    )


def test_fast_candidate_validator_rejects_internal_id_leak_before_publish() -> None:
    publication = runtime._validate_fast_provider_candidate(
        question="What does this graph relationship mean?",
        selected_evidence=[],
        provider_output={
            "parsed": {
                "status": "answer",
                "answer_text": (
                    "Harness Theory Part 1 (article_deadbeefcafebabe) precedes Part 2."
                ),
                "citation_ids": ["ev-1"],
                "abstention_reason": None,
            }
        },
    )
    assert publication is None


def test_complementary_synthesis_contract_uses_named_entities() -> None:
    question = "How can a query router and a DAG work together in a production /ask flow?"
    contract = runtime._question_contract(
        question=question,
        intent_class="complementary_synthesis",
    )
    facets = {item["facet_id"]: item for item in contract["required_facets"]}

    assert "entity_query_router" in facets
    assert facets["entity_query_router"]["terms"] == ["query router"]
    assert "router_role" in facets
    assert "entity_dag" in facets
    assert facets["entity_dag"]["terms"] == ["DAG"]
    assert "dag_role" in facets
    assert "composition_relationship" in facets


def test_entity_facet_requires_exact_phrase_not_token_overlap() -> None:
    facet = {"facet_id": "entity_query_router", "terms": ["query router"]}

    assert runtime._direct_facet_text_matches(
        facet, "The query router chooses a downstream path."
    )
    assert not runtime._direct_facet_text_matches(
        facet, "The query planner hands work to a router later."
    )


def test_existing_required_facet_metadata_is_preserved_by_truncate() -> None:
    existing = {
        "evidence_id": "ev-existing",
        "retrieval_metadata": {
            "required_facet_id": "entity_dag",
            "covered_facet_terms": ["dag"],
            "required_facet_reused_existing": True,
        },
    }
    ordinary = [{"evidence_id": f"ev-{idx}", "retrieval_metadata": {}} for idx in range(10)]

    truncated = runtime._truncate_selected_evidence([*ordinary, existing], budget=3)

    assert truncated[0]["evidence_id"] == "ev-existing"
    assert truncated[0]["retrieval_metadata"]["required_facet_id"] == "entity_dag"


def test_series_evolution_between_parts_extracts_part_entities() -> None:
    question = (
        "How did the Harness Theory series move from defining the harness "
        "boundary to a full responsibility architecture between Part 1 and Part 2?"
    )

    assert runtime._named_question_entities(question)[:2] == [
        "Harness Theory Part 1",
        "Harness Theory Part 2",
    ]
    assert all("move from" not in entity for entity in runtime._named_question_entities(question))


def test_part_number_entity_matching_is_zero_padded_and_boundary_safe() -> None:
    part_two = {"facet_id": "entity_harness_theory_part_2", "terms": ["Harness Theory Part 2"]}
    part_one = {"facet_id": "entity_harness_theory_part_1", "terms": ["Harness Theory Part 1"]}

    assert runtime._direct_facet_text_matches(
        part_two,
        "Harness Theory Part 02 | The Complete Harness Architecture",
    )
    assert not runtime._direct_facet_text_matches(
        part_one,
        "Harness Theory Part 12 | Pattern catalogue",
    )
    requirement = closure.SemanticRequirement(
        requirement_id="entity_harness_theory_part_2",
        instruction="Name Harness Theory Part 2 explicitly.",
        evidence_terms=("Harness Theory Part 2",),
        visible_patterns=(r"Harness Theory Part 2",),
        exact_phrase="Harness Theory Part 2",
    )
    assert closure._selected_evidence_supports_requirement(
        requirement,
        {
            "evidence_id": "ev-part-02",
            "evidence_type": "passage",
            "title": "Harness Theory Part 02",
            "section_title": "Architecture",
            "passage_text": "Harness Theory Part 02 describes the responsibility architecture.",
        },
    )
    assert not closure._selected_evidence_supports_requirement(
        requirement,
        {
            "evidence_id": "ev-part-12",
            "evidence_type": "passage",
            "title": "Harness Theory Part 12",
            "section_title": "Catalogue",
            "passage_text": "Harness Theory Part 12 describes the pattern catalogue.",
        },
    )


def test_structural_multi_dimension_slot_compacts_into_material_slot() -> None:
    material_requirement = closure.SemanticRequirement(
        requirement_id="trust_anchor",
        instruction="State the trust boundary.",
        evidence_terms=("source of trust", "underlying material"),
        visible_patterns=(r"source of trust",),
    )
    structural_requirement = closure.SemanticRequirement(
        requirement_id="multi_dimension_structure",
        instruction="Cover the requested architecture parts.",
        evidence_terms=("architecture", "parts"),
        visible_patterns=(r"architecture",),
    )
    slots = [
        {
            "slot_id": "slot_1",
            "facet_id": "trust_anchor",
            "instruction": material_requirement.instruction,
            "requirement": material_requirement,
            "allowed_evidence_ids": ["ev-trust"],
            "allowed_evidence_labels": ["e1"],
            "support_quote_by_evidence_id": {"ev-trust": "The graph is not the source of trust."},
            "evidence": [],
        },
        {
            "slot_id": "slot_2",
            "facet_id": "multi_dimension_structure",
            "instruction": structural_requirement.instruction,
            "requirement": structural_requirement,
            "allowed_evidence_ids": ["ev-trust", "ev-parts"],
            "allowed_evidence_labels": ["e1", "e2"],
            "support_quote_by_evidence_id": {"ev-parts": "The architecture has several parts."},
            "evidence": [],
        },
    ]

    compacted = closure._compact_structural_slots(slots)

    assert len(compacted) == 1
    assert compacted[0]["facet_id"] == "trust_anchor"
    assert compacted[0]["co_facet_ids"] == ["multi_dimension_structure"]
    assert set(compacted[0]["allowed_evidence_ids"]) == {"ev-trust", "ev-parts"}


def test_source_of_trust_contract_recovers_traceability_terms() -> None:
    question = (
        "In the LLM Wiki architecture, what are Obsidian, Graphology, "
        "and Sigma.js each responsible for, and which one is actually the source of trust?"
    )
    contract = runtime._question_contract(
        question=question,
        intent_class="direct_grounded_knowledge",
    )
    source_terms = next(
        item["terms"]
        for item in contract["required_facets"]
        if item["facet_id"] == "source_of_trust"
    )

    assert "not the source of trust" in source_terms
    assert "underlying material" in source_terms
    assert "claim-to-source" in source_terms


def test_comparison_structural_slot_compacts_into_material_slot() -> None:
    material_requirement = closure.SemanticRequirement(
        requirement_id="verification_gate",
        instruction="Include an explicit verification/completion gate.",
        evidence_terms=("verification", "completion", "gate"),
        visible_patterns=(r"verification",),
    )
    comparison_requirement = closure.SemanticRequirement(
        requirement_id="comparison_or_distinction",
        instruction="Distinguish the compared items and state their relationship.",
        evidence_terms=("compare", "contrast", "different", "relationship"),
        visible_patterns=(r"different",),
    )
    slots = [
        {
            "slot_id": "slot_1",
            "facet_id": "verification_gate",
            "instruction": material_requirement.instruction,
            "requirement": material_requirement,
            "allowed_evidence_ids": ["ev-verification"],
            "allowed_evidence_labels": ["e1"],
            "support_quote_by_evidence_id": {
                "ev-verification": "Verify completion before accepting the result."
            },
            "evidence": [],
        },
        {
            "slot_id": "slot_2",
            "facet_id": "comparison_or_distinction",
            "instruction": comparison_requirement.instruction,
            "requirement": comparison_requirement,
            "allowed_evidence_ids": ["ev-verification", "ev-relationship"],
            "allowed_evidence_labels": ["e1", "e2"],
            "support_quote_by_evidence_id": {
                "ev-relationship": (
                    "A controlled architecture needs verification, approval, "
                    "progress, and parallel branches."
                )
            },
            "evidence": [
                {
                    "text": (
                        "A controlled architecture needs verification, approval, "
                        "progress, and parallel branches."
                    )
                }
            ],
        },
    ]

    compacted = closure._compact_structural_slots(slots)

    assert len(compacted) == 1
    assert compacted[0]["facet_id"] == "verification_gate"
    assert compacted[0]["co_facet_ids"] == ["comparison_or_distinction"]
    assert set(compacted[0]["allowed_evidence_ids"]) == {
        "ev-verification",
        "ev-relationship",
    }
