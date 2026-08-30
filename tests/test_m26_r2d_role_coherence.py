from __future__ import annotations

from knowledge_engine import m26_pa7_arbitrary_query_runtime as runtime


def _evidence(text: str, *, metadata: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "evidence_type": "passage",
        "source_id": "fixture_source",
        "source_identity": "fixture_source",
        "section_id": "fixture_section",
        "concept_id": "fixture_concept",
        "title": "",
        "section_title": "",
        "passage_text": text,
        "retrieval_metadata": metadata or {},
    }


def _record(question: str, text: str) -> dict[str, object]:
    signal = runtime._query_context_signal(question=question, text=text)
    return runtime._context_relevance_record(
        signal,
        intent_class="direct_grounded_knowledge",
    )


def test_query_context_phrases_preserve_true_adjacency() -> None:
    phrases = runtime._query_context_phrases(
        "What kind of skill does a Product Manager need?"
    )

    assert "product manager" in phrases
    assert "skill product" not in phrases


def test_final_floor_rejects_founder_style_surface_overlap_without_role_anchor() -> None:
    question = "What kind of skill does a Product Manager need?"
    founder = _evidence(
        "Team and culture decide who can build this venture. The product is visible, "
        "and the founder needs market fit, customer language, business operations, "
        "and endurance as a venture skill."
    )
    pm_data = _evidence(
        "PMs need data fluency: metric dictionaries, governance, semantic layers, "
        "and experiment interpretation."
    )
    pm_research = _evidence(
        "A PM should use user research to interpret analytics, recover customer "
        "context, and feed hypotheses back into product decisions."
    )

    retained = runtime._apply_final_context_relevance_floor(
        evidence=[founder, pm_data, pm_research],
        question=question,
        limit=5,
        intent_class="direct_grounded_knowledge",
    )

    retained_text = " ".join(str(item["passage_text"]) for item in retained)
    assert "founder needs market fit" not in retained_text
    assert "PMs need data fluency" in retained_text
    assert "A PM should use user research" in retained_text


def test_final_floor_rejects_harness_style_scattered_anchor_components() -> None:
    question = "What kind of skill does a Product Manager need?"
    harness = _evidence(
        "The AI harness uses a Skill Library, Plugin Manager, and Tool Registry "
        "to define its own internal capability system for products."
    )

    retained = runtime._apply_final_context_relevance_floor(
        evidence=[harness],
        question=question,
        limit=5,
        intent_class="direct_grounded_knowledge",
    )

    assert retained == []


def test_inherited_relevance_flag_is_not_authoritative_for_final_passage() -> None:
    item = _evidence(
        "A venture founder may connect product, business, and operations as a skill.",
        metadata={
            "relevance_qualified": True,
            "query_context_score": 99,
            "query_context_terms": ["manager", "product", "skill"],
            "query_context_coverage_terms": ["manager", "product", "skill"],
        },
    )

    record = runtime._evidence_context_relevance_record(
        item,
        question="What kind of skill does a Product Manager need?",
        intent_class="direct_grounded_knowledge",
    )

    assert record["qualified"] is False
    assert record["has_strong_context"] is False


def test_exact_product_manager_phrase_still_qualifies() -> None:
    record = _record(
        "What kind of skill does a Product Manager need?",
        "Product Manager skill judgment should connect customer evidence to decisions.",
    )

    assert record["qualified"] is True
    assert record["has_strong_context"] is True


def test_generic_acronym_alias_keeps_sre_evidence_and_rejects_scattered_terms() -> None:
    question = "What skills does a Site Reliability Engineer need?"

    assert _record(
        question,
        "SREs need incident response, service ownership, reliability reviews, and "
        "operational judgment.",
    )["qualified"]
    assert not _record(
        question,
        "The site has a skill catalog for reliability tooling, and a different "
        "paragraph mentions an engineer, but it never establishes the role being asked about.",
    )["qualified"]


def test_direct_grounded_controls_for_ai_skill_user_research_and_short_query() -> None:
    assert runtime._contextual_definition_query_parts(
        "What is a skill in an AI agent architecture?"
    ) is not None
    assert runtime._contextual_definition_query_parts(
        "What is the role of user research in product management?"
    ) is None
    assert _record(
        "What is a skill in an AI agent architecture?",
        "In an agent architecture, a skill is task methodology above lower-level tools.",
    )["qualified"]
    assert _record(
        "What is the role of user research in product management?",
        "User research helps product management recover context behind metrics and "
        "turn customer evidence into better decisions.",
    )["qualified"]

    short_signal = runtime._query_context_signal(
        question="What skills matter?",
        text="Skill judgment matters when choosing a workflow.",
    )
    short_record = runtime._context_relevance_record(
        short_signal,
        intent_class="direct_grounded_knowledge",
    )
    assert short_record["qualified"]
