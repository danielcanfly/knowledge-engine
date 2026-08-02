from __future__ import annotations

from knowledge_engine.m26_pa7_semantic_closure_runtime import (
    _parse_compact_provider_result,
    _requirement_support_failures,
    _semantic_requirements,
    _visible_semantic_failures,
)


def _failures(
    question: str,
    answer: str,
    intent: str = "direct_grounded_knowledge",
) -> list[str]:
    requirements = _semantic_requirements(question, intent)
    return _visible_semantic_failures(answer, requirements, question)


def test_nc01_cited_but_irrelevant_disconnect_answer_is_rejected() -> None:
    question = (
        "If an agent keeps working after the client disconnects, what parts of the surrounding "
        "control system keep the run trustworthy from admission to completion?"
    )
    answer = (
        "Deployment pitfalls include bad ACLs and network retries. A service should log failures "
        "and watch infrastructure health."
    )
    failures = _failures(question, answer)
    assert failures
    assert any("admission_policy" in item for item in failures)
    assert any("durable_state" in item for item in failures)


def test_nc02_generic_multi_entity_answer_is_rejected() -> None:
    question = (
        "In the LLM Wiki architecture, what are Obsidian, Graphology, and Sigma.js each "
        "responsible for, and which one is actually the source of trust?"
    )
    answer = (
        "The architecture separates storage, processing, and display while keeping trust "
        "elsewhere."
    )
    failures = _failures(question, answer)
    assert failures
    assert any("entity_obsidian" in item for item in failures)
    assert any("entity_graphology" in item for item in failures)
    assert any("entity_sigma_js" in item for item in failures)


def test_nc03_precedes_without_non_entailment_is_rejected() -> None:
    question = (
        "Does the precedes edge between Harness Theory Part 1 and Harness Theory Part 2 prove "
        "that Part 1 depends on Part 2?"
    )
    answer = "Harness Theory Part 1 precedes Harness Theory Part 2 in the production graph."
    failures = _failures(question, answer, intent="graph_relationship")
    assert any("non_entailment" in item for item in failures)


def test_nc04_selected_evidence_without_requirement_support_is_rejected() -> None:
    question = (
        "Sketch a controlled architecture for a complex request that needs different sources, "
        "persisted progress, parallel research branches, verification, and human approval."
    )
    requirements = _semantic_requirements(question, "direct_grounded_knowledge")
    irrelevant = [
        {
            "evidence_id": "e1",
            "evidence_type": "passage",
            "source_id": "unrelated",
            "source_identity": "unrelated",
            "concept_id": "unrelated",
            "title": "Unrelated deployment note",
            "section_title": "Networking",
            "passage_text": "A reverse proxy can retry a failed upstream connection.",
        }
    ]
    failures, proof = _requirement_support_failures(
        requirements=requirements,
        evidence=irrelevant,
    )
    assert failures
    assert proof
    assert any(not item["supported"] for item in proof)


def test_compact_provider_contract_accepts_small_json() -> None:
    parsed = _parse_compact_provider_result(
        '{"status":"answer","answer":"A short grounded answer.","used":["e1","e2"]}'
    )
    assert parsed == {
        "status": "answer",
        "answer": "A short grounded answer.",
        "used": ["e1", "e2"],
    }


def test_compact_provider_contract_rejects_extra_keys() -> None:
    try:
        _parse_compact_provider_result(
            '{"status":"answer","answer":"x","used":["e1"],"extra":"bad"}'
        )
    except ValueError as exc:
        assert "unknown keys" in str(exc)
    else:
        raise AssertionError("extra provider key should fail closed")


def test_graph_false_premise_contract_binds_full_named_entities() -> None:
    question = (
        "The production graph says Harness Theory Part 1 precedes Harness Theory Part 2. "
        "What can we safely infer from that edge, and what can't we infer?"
    )
    requirements = _semantic_requirements(question, "graph_relationship")
    ids = {item.requirement_id for item in requirements}
    assert "entity_harness_theory_part_1" in ids
    assert "entity_harness_theory_part_2" in ids
    assert "ordering_semantics" in ids
    assert "non_entailment" in ids


def test_router_vs_replanner_implicit_wording_gets_both_roles() -> None:
    question = (
        "One mechanism decides where a request should go; another changes the remaining work "
        "when reality invalidates the plan. How are their jobs different?"
    )
    requirements = _semantic_requirements(question, "cross_document_comparison")
    ids = {item.requirement_id for item in requirements}
    assert {"initial_routing_role", "replanning_role", "role_contrast"}.issubset(ids)
