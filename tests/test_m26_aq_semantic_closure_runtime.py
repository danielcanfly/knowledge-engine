from __future__ import annotations

import json
import time
from typing import Any

import pytest

from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy
from knowledge_engine.m26_aq_semantic_contract import (
    _contract_compat_module,
    _publish_support_proof_recovered_answer,
    _recover_supported_semantic_answer,
    _should_attempt_semantic_recovery,
    _supported_semantic_recovery_candidate,
    derive_semantic_requirements,
    evaluate_visible_semantics,
)
from knowledge_engine.m26_pa7_semantic_closure_runtime import (
    SemanticRequirement,
    _parse_compact_provider_result,
    _requirement_support_failures,
    _response_from_verification,
    _runtime_bound_candidate,
    _semantic_requirements,
    _synthesize_and_verify,
    _visible_semantic_failures,
)
from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes


class _AbstainingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], str]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append((payload, call_class))
        return {
            "text": json.dumps({"status": "abstain", "answer": "", "used": []}),
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "cost_usd": "0.00",
            "call_class": call_class,
        }


def _failures(
    question: str,
    answer: str,
    intent: str = "direct_grounded_knowledge",
) -> list[str]:
    requirements = _semantic_requirements(question, intent)
    return _visible_semantic_failures(answer, requirements, question)


def _passage(
    evidence_id: str,
    text: str,
    source: str,
) -> dict[str, str]:
    return {
        "evidence_id": evidence_id,
        "locator_id": f"loc_{evidence_id}",
        "evidence_type": "passage",
        "source_id": source,
        "source_identity": source,
        "concept_id": f"concept_{evidence_id}",
        "title": source,
        "section_title": source,
        "passage_text": text,
    }


def _rich_passage(evidence_id: str, text: str, source: str) -> dict[str, Any]:
    return {
        **_passage(evidence_id, text, source),
        "release_id": "release-test",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "section_id": f"section_{evidence_id}",
        "channels": ["dense"],
        "passage_text_sha256": sha256_bytes(text.encode("utf-8")),
        "provenance_record_sha256": "b" * 64,
        "retrieved_at": "",
        "retrieval_metadata": {"query_overlap_score": 1.0},
    }


def _metadata_only_passage(
    evidence_id: str,
    source: str,
) -> dict[str, str]:
    return {
        "evidence_id": evidence_id,
        "locator_id": f"loc_{evidence_id}",
        "evidence_type": "passage",
        "source_id": source,
        "source_identity": source,
        "concept_id": f"concept_{evidence_id}",
        "title": source,
        "section_title": source,
        "passage_text": "",
    }


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


def test_controlled_lifecycle_composition_derives_all_roles_from_paraphrases() -> None:
    questions = [
        (
            "Describe one controlled agent lifecycle that combines initial routing, "
            "a dependency DAG, durable state, verification, and human approval without "
            "treating those controls as interchangeable."
        ),
        (
            "Walk through a governed agent workflow: route the request first, run "
            "dependent parallel steps, persist run state, verify completion, then "
            "require human approval while keeping those controls in separate roles."
        ),
        (
            "How would a controlled architecture combine route selection, dependency "
            "ordering, durable progress, a completion gate, and an approval authority "
            "without conflating the controls?"
        ),
    ]

    for question in questions:
        requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
        ids = {item.requirement_id for item in requirements}
        assert {
            "source_selection",
            "parallel_branches",
            "persisted_progress",
            "verification_gate",
            "human_approval",
            "control_role_distinction",
        }.issubset(ids)


def test_controlled_lifecycle_recovery_mentions_dag_and_distinct_roles() -> None:
    question = (
        "Describe one controlled agent lifecycle that combines initial routing, "
        "a dependency DAG, durable state, verification, and human approval without "
        "treating those controls as interchangeable."
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    evidence = [
        _passage(
            "route",
            "A Router sends different requests to different capabilities and sources of truth.",
            "routing-note",
        ),
        _passage(
            "dag",
            (
                "A dependency DAG expresses directional dependencies, fan-out, "
                "branches, and joins without cycles inside one run."
            ),
            "dag-note",
        ),
        _passage(
            "state",
            (
                "Durable server-side state governs persisted progress, legal "
                "transitions, recovery, and terminal outcomes."
            ),
            "state-note",
        ),
        _passage(
            "verify",
            (
                "Evidence verification and completion acceptance checks form the "
                "gate before success or release."
            ),
            "verification-note",
        ),
        _passage(
            "approval",
            "Human approval is required before publication or another sensitive release action.",
            "approval-note",
        ),
        _passage(
            "roles",
            (
                "Routers, DAGs, state machines, verification, and approval gates "
                "solve different parts of the problem and are not interchangeable."
            ),
            "roles-note",
        ),
    ]

    candidate = _supported_semantic_recovery_candidate(
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )

    assert candidate is not None
    answer_text = str(candidate["answer_text"])
    lowered = answer_text.casefold()
    assert not evaluate_visible_semantics(answer_text, requirements, question)
    assert "initial routing" in lowered or "route selection" in lowered
    assert "DAG" in answer_text
    assert "durable" in lowered and "state" in lowered
    assert "verification" in lowered
    assert "human approval" in lowered
    assert "not interchangeable" in lowered or "distinct roles" in lowered
    assert set(candidate["selected_evidence_ids"]) >= {
        "route",
        "dag",
        "state",
        "verify",
        "approval",
    }


def test_controlled_lifecycle_requirements_do_not_attach_to_venture_state_question() -> None:
    question = (
        "Why is a durable venture more than a product when operations, resources, "
        "team, finance, and risk all matter?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    ids = {item.requirement_id for item in requirements}
    assert not {
        "source_selection",
        "parallel_branches",
        "persisted_progress",
        "verification_gate",
        "human_approval",
        "control_role_distinction",
    } & ids


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


def test_provider_abstain_with_available_evidence_uses_verified_deterministic_fallback() -> None:
    question = (
        "If a client disconnects, how does the admission policy, durable state authority, "
        "continued execution, completion verification, and observability reattachment keep "
        "the run trustworthy from admission to completion?"
    )
    evidence = [
        _rich_passage(
            "ev1",
            (
                "An admitted task remains trustworthy through admission policy, durable "
                "persisted state authority, continued execution after disconnect, completion "
                "verification, and observability for reattachment status."
            ),
            "source-a",
        )
    ]
    provider = _AbstainingProvider()

    answer, closure = _synthesize_and_verify(
        question=question,
        trace_id="trace-test",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=_semantic_requirements(question, "direct_grounded_knowledge"),
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        "aq_semantic_closure_repair",
    ]
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_source"] == "deterministic_verified_evidence_synthesis"
    assert answer["safe_abstention"] is False
    assert answer["citations"]
    verification = answer["multi_evidence_verification"]
    assert verification["deterministic_evidence_synthesis_used"] is True
    assert verification["provider_contract"] == "compact_runtime_bound_semantic_closure/v1"
    assert closure["failures"] == []
    assert closure["broad_deterministic_fallback_used"] is True
    assert "PROVIDER_ABSTAINED_WITH_AVAILABLE_EVIDENCE" in closure["pre_recovery_failures"]


def test_resource_constraints_do_not_trigger_multi_source_requirement() -> None:
    question = (
        "When is pausing a venture a rational survival decision rather than evidence "
        "that the founder no longer believes in the problem? Separate conviction in "
        "the problem from runway, timing, people and resource constraints."
    )
    facet_ids = {
        item["facet_id"]
        for item in legacy._direct_question_facets(question)
    }
    assert "multi_source_selection" not in facet_ids
    assert {
        "venture_pause_rationality",
        "conviction_problem_boundary",
        "runway_constraint",
        "timing_constraint",
        "people_constraint",
        "resource_constraint",
    }.issubset(facet_ids)


def test_manual_false_green_answers_are_question_alignment_failures() -> None:
    cases = [
        (
            (
                "When is pausing a venture a rational survival decision rather than "
                "evidence that the founder no longer believes in the problem? Separate "
                "conviction in the problem from runway, timing, people and resource constraints."
            ),
            (
                "multi source selection: The build side: how documents come in "
                "**Station 1 - Data source** This is not an AI problem."
            ),
            {
                "venture_pause_rationality",
                "conviction_problem_boundary",
                "runway_constraint",
                "timing_constraint",
                "people_constraint",
                "resource_constraint",
            },
        ),
        (
            (
                "Why does evidence of demand still not prove that there is a viable "
                "business? Walk through the extra questions a founder must answer "
                "about value capture, economics, delivery and repeatability."
            ),
            (
                "non entailment boundary: A precedes relationship does not by itself "
                "prove dependency; What measurable numbers prove value?"
            ),
            {
                "demand_not_business_proof",
                "value_capture",
                "business_economics",
                "business_delivery",
                "business_repeatability",
            },
        ),
        (
            (
                "A downloaded ComfyUI workflow opens with red nodes or runs out of "
                "memory. Explain how checkpoints, LoRAs, VAE, CLIP/T5XXL, GGUF/FP8, "
                "missing requirements and memory pressure can produce different "
                "failure modes, and how you would debug them in a sensible order."
            ),
            (
                "direct answer: SDXL is the best balanced all-round starting point "
                "for a 16GB Mac, SD 1.5 is the easiest old friend, Flux is excellent "
                "but heavier, and HiDream is exciting but not where I would begin."
            ),
            {
                "comfyui_failure_modes",
                "comfyui_checkpoints",
                "comfyui_loras",
                "comfyui_vae",
                "comfyui_clip_t5xxl",
                "comfyui_quantization",
                "comfyui_requirements",
                "comfyui_memory_debug_order",
            },
        ),
    ]
    for question, answer, expected_missing in cases:
        failures = _visible_semantic_failures(
            answer,
            _semantic_requirements(question, "direct_grounded_knowledge"),
            question,
        )
        missing_ids = {
            item.removeprefix("SEMANTIC_VISIBLE_MISSING:")
            for item in failures
        }
        assert expected_missing & missing_ids


def test_bb02_business_change_question_stays_direct_not_temporal() -> None:
    question = (
        "When a startup changes direction more than once in a short period, how can you "
        "distinguish evidence-driven learning from aimless founder drift? Focus on what "
        "changed in the problem, constraints and market reality rather than how often the "
        "pitch deck changed."
    )
    assert legacy._intent_class(question) == "direct_grounded_knowledge"


def test_bb12_durable_venture_question_derives_venture_facets_not_lifecycle() -> None:
    question = (
        "Why is a venture more than its product? Explain how operations, resources, team, "
        "finance and risk turn a promising product into—or prevent it from becoming—a durable "
        "venture system."
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    ids = {item.requirement_id for item in requirements}
    assert "durable_state" not in ids
    assert {
        "venture_not_product",
        "operations_system",
        "venture_resources",
        "team_capacity",
        "finance_model",
        "risk_management",
    }.issubset(ids)


def test_bb03_pain_adoption_question_derives_bilingual_facets() -> None:
    question = (
        "如果客戶明明都承認問題存在，為什麼市場仍然可能完全不動？請用旅宿業者的實際經驗解釋 "
        "「有痛點」和「願意改變／願意採用」之間還差了哪些條件。"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    ids = {item.requirement_id for item in requirements}
    assert {
        "pain_acknowledgement",
        "change_willingness",
        "adoption_conditions",
        "market_movement",
    }.issubset(ids)


def test_bb24_quote_level_support_rejects_generic_model_family_paragraph() -> None:
    generic = _passage(
        "generic",
        "SDXL is the best balanced all-round starting point for a 16GB Mac.",
        "comfyui-generic",
    )
    specific = _passage(
        "specific",
        (
            "Model-related selectors inside nodes Checkpoints, VAEs and LoRAs are "
            "chosen in the nodes that need them."
        ),
        "comfyui-specific",
    )
    generic_ref = legacy._deterministic_support_ref_for_facet(
        generic,
        {"facet_id": "comfyui_checkpoints", "terms": ["checkpoint", "checkpoints"]},
    )
    specific_ref = legacy._deterministic_support_ref_for_facet(
        specific,
        {"facet_id": "comfyui_checkpoints", "terms": ["checkpoint", "checkpoints"]},
    )
    assert generic_ref is None
    assert specific_ref is not None


def test_bb05_resource_constraint_rejects_generic_harness_resources() -> None:
    generic = _passage(
        "generic",
        (
            "A summary should retain current objective, user constraints, modified "
            "resources, tests and evidence, remaining work, and next safe action."
        ),
        "harness",
    )
    venture = _passage(
        "venture",
        (
            "But when the people, timing and resources are wrong, forcing yourself "
            "to keep going is not bravery."
        ),
        "venture",
    )
    facet = {"facet_id": "resource_constraint", "terms": ["resource", "resources"]}

    assert legacy._deterministic_support_ref_for_facet(generic, facet) is None
    assert legacy._deterministic_support_ref_for_facet(venture, facet) is not None


def test_bb24_quote_window_keeps_late_facet_terms_visible() -> None:
    passage = _passage(
        "late",
        (
            "SDXL is the best balanced all-round starting point for a 16GB Mac, and "
            "this introductory model discussion is intentionally long before it moves "
            "to the practical mess: what checkpoints, clips, LoRAs, and VAE files "
            "are, where they go, and why Flux workflows open with red nodes."
        ),
        "comfyui",
    )
    facet = {"facet_id": "comfyui_checkpoints", "terms": ["checkpoint", "checkpoints"]}
    ref = legacy._deterministic_support_ref_for_facet(passage, facet)

    assert ref is not None
    assert "checkpoint" in ref["exact_quote"].casefold()


def test_comfyui_memory_pressure_does_not_satisfy_debug_order_support() -> None:
    question = (
        "A downloaded ComfyUI workflow opens with red nodes or runs out of memory. "
        "Explain how checkpoints, LoRAs, VAE, CLIP/T5XXL, GGUF/FP8, missing requirements "
        "and memory pressure can produce different failure modes, and how you would debug "
        "them in a sensible order."
    )
    requirements = _semantic_requirements(question, "direct_grounded_knowledge")
    evidence = [
        _rich_passage(
            "ev1",
            "If ComfyUI runs out of memory, reduce batch size and close other apps.",
            "comfyui-memory-note",
        )
    ]
    failures, proof = _requirement_support_failures(
        requirements=requirements,
        evidence=evidence,
    )
    assert "SEMANTIC_SUPPORT_MISSING:comfyui_memory_debug_order" in failures
    assert any(
        item["requirement_id"] == "comfyui_memory_debug_order" and not item["supported"]
        for item in proof
    )


def test_comfyui_direct_debug_order_requires_exact_strategy_phrase() -> None:
    question = (
        "A downloaded ComfyUI workflow opens with red nodes or runs out of memory. "
        "Explain how checkpoints, LoRAs, VAE, CLIP/T5XXL, GGUF/FP8, missing requirements "
        "and memory pressure can produce different failure modes, and how you would debug "
        "them in a sensible order."
    )
    facet = next(
        item
        for item in legacy._question_contract(
            question=question,
            intent_class="direct_grounded_knowledge",
        )["required_facets"]
        if item["facet_id"] == "comfyui_memory_debug_order"
    )
    generic_memory = "If ComfyUI runs out of memory, reduce batch size and close other apps."
    ordered_debugging = "A steadier method is to go back to a minimal working state."

    assert not legacy._direct_facet_text_matches(facet, generic_memory)
    assert legacy._direct_facet_text_matches(facet, ordered_debugging)


def test_router_vs_replanner_implicit_wording_gets_both_roles() -> None:
    question = (
        "One mechanism decides where a request should go; another changes the remaining work "
        "when reality invalidates the plan. How are their jobs different?"
    )
    requirements = _semantic_requirements(question, "cross_document_comparison")
    ids = {item.requirement_id for item in requirements}
    assert {"initial_routing_role", "replanning_role", "role_contrast"}.issubset(ids)


def test_bb01_initial_route_vs_revision_question_derives_positive_requirements() -> None:
    question = (
        "Explain the difference between the component that chooses an initial request route "
        "and the component that revises a plan after execution has already started."
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    ids = {item.requirement_id for item in requirements}
    assert {"initial_routing_role", "replanning_role", "role_contrast"}.issubset(ids)


def test_bb01_provider_abstention_recovers_to_visible_cited_route_replan_answer() -> None:
    question = (
        "Explain the difference between the component that chooses an initial request route "
        "and the component that revises a plan after execution has already started."
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    evidence = [
        _passage(
            "route",
            (
                "The query router chooses the initial route, path, or capability "
                "for a request before execution begins."
            ),
            "router-note",
        ),
        _passage(
            "replan",
            (
                "Adaptive replanning revises the remaining work after execution "
                "has started when evidence invalidates the plan."
            ),
            "replan-note",
        ),
        _passage(
            "contrast",
            (
                "Initial dispatch and later replanning are different jobs: the first "
                "route happens upfront, and the later revision corrects the plan after "
                "runtime reality changes."
            ),
            "contrast-note",
        ),
    ]
    candidate = _supported_semantic_recovery_candidate(
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )
    assert candidate is not None
    answer_text = str(candidate["answer_text"])
    assert not evaluate_visible_semantics(answer_text, requirements, question)
    assert "initial" in answer_text.casefold()
    assert "remaining" in answer_text.casefold()
    assert len(candidate["claims"][0]["support_refs"]) >= 2


def test_bb02_supported_lifecycle_facets_recover_to_visible_answer() -> None:
    question = (
        "Why is persisted run state important when a client disconnects before "
        "a long-running workflow has finished?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    evidence = [
        _passage(
            "admission",
            (
                "The request admission boundary records the effective policy and task "
                "contract before execution."
            ),
            "admission-note",
        ),
        _passage(
            "durable",
            (
                "A durable persisted server-side run state preserves authority after "
                "the client disconnects."
            ),
            "durable-note",
        ),
        _passage(
            "completion",
            (
                "Completion verification and acceptance checks happen before the system "
                "declares terminal success."
            ),
            "completion-note",
        ),
        _passage(
            "observability",
            (
                "Observability, status, and reattach or resume handles let clients "
                "follow a headless continuing run."
            ),
            "observability-note",
        ),
    ]
    candidate = _supported_semantic_recovery_candidate(
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )
    assert candidate is not None
    answer_text = str(candidate["answer_text"])
    assert not evaluate_visible_semantics(answer_text, requirements, question)
    assert {item.requirement_id for item in requirements} == {
        "durable_state",
        "completion_verification",
        "observability",
    }
    assert "admission" not in answer_text.casefold()
    assert "durable" in answer_text.casefold()
    assert "completion" in answer_text.casefold()
    assert "observability" in answer_text.casefold()


def test_bb02_support_proof_ref_only_recovers_without_passage_text() -> None:
    question = (
        "Why is persisted run state important when a client disconnects before "
        "a long-running workflow has finished?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    requirement_ids = {item.requirement_id for item in requirements}
    assert {
        "durable_state",
        "completion_verification",
        "observability",
    }.issubset(requirement_ids)
    evidence = [
        _metadata_only_passage("durable", "daniel_blog_en__harness-theory-part-6"),
        _metadata_only_passage("completion", "daniel_blog_en__harness-theory-part-2"),
        _metadata_only_passage("observability", "daniel_blog_en__harness-theory-part-2"),
    ]

    support_proof = [
        {
            "requirement_id": "durable_state",
            "supported": True,
            "score": 3.0,
            "evidence_id": "durable",
            "source_identity": "daniel_blog_en__harness-theory-part-6",
            "source_id": "daniel_blog_en__harness-theory-part-6",
            "locator_id": "loc_durable",
        },
        {
            "requirement_id": "completion_verification",
            "supported": True,
            "score": 2.0,
            "evidence_id": "completion",
            "source_identity": "daniel_blog_en__harness-theory-part-2",
            "source_id": "daniel_blog_en__harness-theory-part-2",
            "locator_id": "loc_completion",
        },
        {
            "requirement_id": "observability",
            "supported": True,
            "score": 2.0,
            "evidence_id": "observability",
            "source_identity": "daniel_blog_en__harness-theory-part-2",
            "source_id": "daniel_blog_en__harness-theory-part-2",
            "locator_id": "loc_observability",
        },
    ]
    recovered = _recover_supported_semantic_answer(
        compatibility=_contract_compat_module(),
        question=question,
        trace_id="trace-lifecycle-support-proof",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
        verification={
            "status": "owner_only_safe_abstention",
            "answer_source": "safe_abstention",
            "reason_codes": ["M26-PA7-ME-029", "SEMANTIC_CLOSURE_FAILED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
        },
        closure={
            "failures": ["M26-PA7-ME-029"],
            "support_proof": support_proof,
            "local_repair_rejection_codes": ["NO_SEMANTIC_TEXT"],
        },
    )

    assert recovered is not None
    answer, closure = recovered
    text = answer["answer_text"].casefold()
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert answer["multi_evidence_verification"]["support_proof_ref_only_used"] is True
    assert answer["unsupported_accepted_claims"] == 0
    assert answer["citation_locator_valid"] is True
    assert "durable" in text
    assert "continues" in text
    assert "observability" in text
    assert "completion verification" in text
    assert "exact_quote" not in json.dumps(answer)
    assert "exact_support_snippet" not in json.dumps(answer)
    assert closure["failures"] == []
    assert "NO_SEMANTIC_TEXT" not in closure.get("local_repair_rejection_codes", [])
    assert closure["pre_recovery_local_repair_rejection_codes"] == ["NO_SEMANTIC_TEXT"]
    assert {
        item["requirement_id"]
        for item in closure["support_proof"]
        if item.get("supported") is True
    }.issuperset({"durable_state", "completion_verification", "observability"})
    assert {item["evidence_id"] for item in answer["citations"]} == {
        "durable",
        "completion",
        "observability",
    }


def test_bb02_support_proof_ref_only_recovers_when_observability_and_completion_share_ref() -> None:
    question = (
        "Why is persisted run state important when a client disconnects before "
        "a long-running workflow has finished?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    requirement_ids = {item.requirement_id for item in requirements}
    assert {
        "durable_state",
        "completion_verification",
        "observability",
    }.issubset(requirement_ids)
    evidence = [
        _metadata_only_passage("durable", "daniel_blog_en__harness-theory-part-6"),
        _metadata_only_passage("lifecycle", "daniel_blog_en__harness-theory-part-2"),
    ]
    support_proof = [
        {
            "requirement_id": "durable_state",
            "supported": True,
            "score": 3.0,
            "evidence_id": "durable",
            "source_identity": "daniel_blog_en__harness-theory-part-6",
            "source_id": "daniel_blog_en__harness-theory-part-6",
            "locator_id": "loc_durable",
        },
        {
            "requirement_id": "completion_verification",
            "supported": True,
            "score": 2.0,
            "evidence_id": "lifecycle",
            "source_identity": "daniel_blog_en__harness-theory-part-2",
            "source_id": "daniel_blog_en__harness-theory-part-2",
            "locator_id": "loc_lifecycle",
        },
        {
            "requirement_id": "observability",
            "supported": True,
            "score": 2.0,
            "evidence_id": "lifecycle",
            "source_identity": "daniel_blog_en__harness-theory-part-2",
            "source_id": "daniel_blog_en__harness-theory-part-2",
            "locator_id": "loc_lifecycle",
        },
    ]

    recovered = _recover_supported_semantic_answer(
        compatibility=_contract_compat_module(),
        question=question,
        trace_id="trace-bb02-shared-ref",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
        verification={
            "status": "owner_only_safe_abstention",
            "answer_source": "safe_abstention",
            "reason_codes": ["M26-PA7-ME-034", "SEMANTIC_CLOSURE_FAILED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
            "raw_answer": "",
            "answer_text": "",
        },
        closure={
            "failures": ["M26-PA7-ME-034"],
            "support_proof": support_proof,
            "local_repair_rejection_codes": ["NO_SEMANTIC_TEXT"],
        },
    )

    assert recovered is not None
    answer, closure = recovered
    lowered = answer["answer_text"].casefold()
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert answer["safe_abstention"] is False
    assert answer["reason_codes"] == []
    assert "durable" in lowered
    assert "observability" in lowered
    assert "completion verification" in lowered
    assert "exact_quote" not in json.dumps(answer)
    assert "exact_support_snippet" not in json.dumps(answer)
    assert closure["failures"] == []
    assert {item["evidence_id"] for item in answer["citations"]} == {
        "durable",
        "lifecycle",
    }


def test_bb02_lifecycle_paraphrase_recovers_without_exact_question_string() -> None:
    question = (
        "How does durable run state help when a browser disconnects during a "
        "long-running agent workflow, and why is verification still separate?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    evidence = [
        _metadata_only_passage("durable", "daniel_blog_en__harness-theory-part-6"),
        _metadata_only_passage("lifecycle", "daniel_blog_en__harness-theory-part-2"),
    ]
    recovered = _publish_support_proof_recovered_answer(
        compatibility=_contract_compat_module(),
        question=question,
        trace_id="trace-bb02-paraphrase",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
        verification={
            "status": "owner_only_safe_abstention",
            "terminal_status": "safe_abstention",
            "answer_source": "safe_abstention",
            "safe_abstention": True,
            "reason_codes": ["M26-PA7-ME-034", "SEMANTIC_CLOSURE_FAILED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
            "raw_answer": "",
            "answer_text": "",
        },
        closure={
            "failures": ["M26-PA7-ME-034"],
            "support_proof": [
                {
                    "requirement_id": "durable_state",
                    "supported": True,
                    "score": 3.0,
                    "evidence_id": "durable",
                    "source_identity": "daniel_blog_en__harness-theory-part-6",
                },
                {
                    "requirement_id": "completion_verification",
                    "supported": True,
                    "score": 2.0,
                    "evidence_id": "lifecycle",
                    "source_identity": "daniel_blog_en__harness-theory-part-2",
                },
                {
                    "requirement_id": "observability",
                    "supported": True,
                    "score": 2.0,
                    "evidence_id": "lifecycle",
                    "source_identity": "daniel_blog_en__harness-theory-part-2",
                },
            ],
            "local_repair_rejection_codes": ["NO_SEMANTIC_TEXT"],
        },
    )

    answer, closure = recovered
    lowered = answer["answer_text"].casefold()
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert answer["safe_abstention"] is False
    assert "durable" in lowered
    assert "verification" in lowered
    assert "resume" in lowered or "rejoined" in lowered or "continues" in lowered
    assert closure["failures"] == []


def test_bb13_support_proof_ref_only_recovers_without_passage_text() -> None:
    question = (
        "How should a long-running controlled agent recover after a client disconnect "
        "without replaying completed work or skipping the verification that still has "
        "to happen later?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    requirement_ids = {item.requirement_id for item in requirements}
    assert {"durable_state", "completion_verification"}.issubset(requirement_ids)

    evidence = [
        _metadata_only_passage("durable", "daniel_blog_en__harness-theory-part-6"),
        _metadata_only_passage("completion", "daniel_blog_en__harness-theory-part-9"),
    ]
    support_proof = [
        {
            "requirement_id": "durable_state",
            "supported": True,
            "score": 3.0,
            "evidence_id": "durable",
            "source_identity": "daniel_blog_en__harness-theory-part-6",
            "source_id": "daniel_blog_en__harness-theory-part-6",
            "locator_id": "loc_durable",
        },
        {
            "requirement_id": "completion_verification",
            "supported": True,
            "score": 2.0,
            "evidence_id": "completion",
            "source_identity": "daniel_blog_en__harness-theory-part-9",
            "source_id": "daniel_blog_en__harness-theory-part-9",
            "locator_id": "loc_completion",
        },
    ]
    recovered = _recover_supported_semantic_answer(
        compatibility=_contract_compat_module(),
        question=question,
        trace_id="trace-bb13-support-proof",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
        verification={
            "status": "owner_only_safe_abstention",
            "answer_source": "safe_abstention",
            "reason_codes": ["M26-PA7-ME-034", "SEMANTIC_CLOSURE_FAILED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
            "raw_answer": "",
            "answer_text": "",
        },
        closure={
            "failures": ["M26-PA7-ME-034"],
            "support_proof": support_proof,
            "local_repair_rejection_codes": ["NO_SEMANTIC_TEXT"],
        },
    )

    assert recovered is not None
    answer, closure = recovered
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["multi_evidence_verification"]["support_proof_ref_only_used"] is True
    assert answer["unsupported_accepted_claims"] == 0
    assert closure["failures"] == []
    assert "NO_SEMANTIC_TEXT" not in closure.get("local_repair_rejection_codes", [])
    assert {item["evidence_id"] for item in answer["citations"]} == {"durable", "completion"}
    assert "exact_quote" not in json.dumps(answer)


def test_bb10_support_proof_ref_only_comparison_precedes_lifecycle_wording() -> None:
    question = (
        "Why do durable state and post-execution verification solve different "
        "reliability problems in a controlled agent architecture?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    assert {item.requirement_id for item in requirements} == {
        "durable_state",
        "completion_verification",
    }
    evidence = [
        _metadata_only_passage("durable", "durable-note"),
        _metadata_only_passage("completion", "completion-note"),
    ]
    support_proof = [
        {
            "requirement_id": "completion_verification",
            "supported": True,
            "score": 4.5,
            "evidence_id": "completion",
            "source_identity": "completion-note",
            "source_id": "completion-note",
            "locator_id": "loc_completion",
        },
        {
            "requirement_id": "durable_state",
            "supported": True,
            "score": 4.5,
            "evidence_id": "durable",
            "source_identity": "durable-note",
            "source_id": "durable-note",
            "locator_id": "loc_durable",
        },
    ]

    recovered = _recover_supported_semantic_answer(
        compatibility=_contract_compat_module(),
        question=question,
        trace_id="trace-bb10-support-proof-comparison",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
        verification={
            "status": "owner_only_safe_abstention",
            "answer_source": "safe_abstention",
            "reason_codes": ["M26-PA7-ME-034", "SEMANTIC_CLOSURE_FAILED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
            "raw_answer": "",
            "answer_text": "",
        },
        closure={
            "failures": ["M26-PA7-ME-034"],
            "support_proof": support_proof,
            "local_repair_rejection_codes": ["NO_SEMANTIC_TEXT"],
        },
    )

    assert recovered is not None
    answer, closure = recovered
    lowered = answer["answer_text"].casefold()
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert answer["answer_claims"][0]["claim_role"] == "comparison"
    assert answer["relationship_summary"]["relation"] == "contrasts_with"
    assert answer["unsupported_accepted_claims"] == 0
    assert "different reliability problems" in lowered
    assert "continuity" in lowered or "recovery" in lowered
    assert "correctness" in lowered or "acceptance" in lowered or "trust" in lowered
    assert "one preserves run state" in lowered
    assert "process state" in lowered
    assert "evaluates the result" in lowered
    assert "persistence alone does not prove correctness" in lowered
    assert "client disconnect because" not in lowered
    assert "exact_quote" not in json.dumps(answer)
    assert "exact_support_snippet" not in json.dumps(answer)
    assert closure["failures"] == []
    assert closure["semantic_synthesis_recovery"]["comparison_precedence_used"] is True
    assert {item["evidence_id"] for item in answer["citations"]} == {
        "durable",
        "completion",
    }


def test_support_proof_recovery_publishes_into_final_response_envelope() -> None:
    question = (
        "Why is persisted run state important when a client disconnects before "
        "a long-running workflow has finished?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    evidence = [
        _metadata_only_passage("durable", "daniel_blog_en__harness-theory-part-6"),
        _metadata_only_passage("completion", "daniel_blog_en__harness-theory-part-2"),
        _metadata_only_passage("observability", "daniel_blog_en__harness-theory-part-2"),
    ]
    support_proof = [
        {
            "requirement_id": "durable_state",
            "supported": True,
            "score": 4.5,
            "evidence_id": "durable",
            "source_identity": "daniel_blog_en__harness-theory-part-6",
        },
        {
            "requirement_id": "completion_verification",
            "supported": True,
            "score": 1.5,
            "evidence_id": "completion",
            "source_identity": "daniel_blog_en__harness-theory-part-2",
        },
        {
            "requirement_id": "observability",
            "supported": True,
            "score": 3.5,
            "evidence_id": "observability",
            "source_identity": "daniel_blog_en__harness-theory-part-2",
        },
    ]

    verification, closure = _publish_support_proof_recovered_answer(
        compatibility=_contract_compat_module(),
        question=question,
        trace_id="trace-publication-support-proof",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
        verification={
            "status": "owner_only_safe_abstention",
            "terminal_status": "safe_abstention",
            "answer_source": "safe_abstention",
            "safe_abstention": True,
            "reason_codes": ["M26-PA7-ME-034", "SEMANTIC_CLOSURE_FAILED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
            "raw_answer": "provider abstained",
            "answer_text": "",
            "provider_call_count": 1,
            "payg_equivalent_cost_usd": "0.001",
            "multi_evidence_verification": {
                "provider_attempt_telemetry": [{"attempt": 1}]
            },
        },
        closure={
            "failures": ["M26-PA7-ME-034"],
            "support_proof": support_proof,
        },
    )

    response = _response_from_verification(
        gate={"self_sha256": "gate-sha"},
        bundle=None,
        dense_result=None,
        lexical_result=None,
        evidence=evidence,
        verification=verification,
        trace_id="trace-publication-support-proof",
        question_sha="q" * 64,
        started=time.monotonic(),
        intent_class="direct_grounded_knowledge",
        semantic_closure=closure,
    )

    assert response["status"] == "owner_only_cited_answer"
    assert response["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert response["safe_abstention"] is False
    assert response["answer_text"]
    assert response["citations"]
    assert response["reason_codes"] == []
    assert response["unsupported_accepted_claims"] == 0
    assert response["semantic_closure"]["failures"] == []
    assert response["multi_evidence_verification"]["support_proof_ref_only_used"] is True
    assert {item["evidence_id"] for item in response["citations"]} == {
        "durable",
        "completion",
        "observability",
    }


def test_support_proof_recovery_publishes_two_facet_lifecycle_response() -> None:
    question = (
        "How should a long-running controlled agent recover after a client disconnect "
        "without replaying completed work or skipping the verification that still has "
        "to happen later?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    evidence = [
        _metadata_only_passage("durable", "daniel_blog_en__harness-theory-part-6"),
        _metadata_only_passage("completion", "daniel_blog_en__harness-theory-part-7"),
    ]
    verification, closure = _publish_support_proof_recovered_answer(
        compatibility=_contract_compat_module(),
        question=question,
        trace_id="trace-two-facet-lifecycle",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
        verification={
            "status": "owner_only_safe_abstention",
            "terminal_status": "safe_abstention",
            "answer_source": "safe_abstention",
            "safe_abstention": True,
            "reason_codes": ["M26-PA7-ME-034", "SEMANTIC_CLOSURE_FAILED"],
            "unsupported_accepted_claims": 0,
            "citation_locator_valid": True,
            "raw_answer": "",
            "answer_text": "",
        },
        closure={
            "failures": ["M26-PA7-ME-034"],
            "support_proof": [
                {
                    "requirement_id": "durable_state",
                    "supported": True,
                    "score": 3.0,
                    "evidence_id": "durable",
                    "source_identity": "daniel_blog_en__harness-theory-part-6",
                },
                {
                    "requirement_id": "completion_verification",
                    "supported": True,
                    "score": 4.5,
                    "evidence_id": "completion",
                    "source_identity": "daniel_blog_en__harness-theory-part-7",
                },
            ],
        },
    )

    text = verification["answer_text"].casefold()
    assert verification["status"] == "owner_only_cited_answer"
    assert verification["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert verification["safe_abstention"] is False
    assert verification["reason_codes"] == []
    assert "durable" in text
    assert "completion verification" in text
    assert "observability" not in text
    assert closure["failures"] == []
    assert {item["evidence_id"] for item in verification["citations"]} == {
        "durable",
        "completion",
    }


def test_bb10_supported_lifecycle_facets_recover_to_visible_answer() -> None:
    question = (
        "Why do durable state and post-execution verification solve different "
        "reliability problems in a controlled agent architecture?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    evidence = [
        _passage(
            "durable",
            (
                "Persisted server-side state preserves run progress after a client "
                "disconnect."
            ),
            "durable-note",
        ),
        _passage(
            "completion",
            (
                "Completion verification and acceptance checks happen before the "
                "system declares terminal success."
            ),
            "completion-note",
        ),
    ]
    candidate = _supported_semantic_recovery_candidate(
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )
    assert candidate is not None
    answer_text = str(candidate["answer_text"])
    assert not evaluate_visible_semantics(answer_text, requirements, question)
    assert "durable" in answer_text.casefold()
    assert "post-execution verification" in answer_text.casefold()
    assert "different reliability problems" in answer_text.casefold()
    assert "one preserves run state" in answer_text.casefold()
    assert "trusted" in answer_text.casefold()


def test_positive_answerability_recovery_still_abstains_when_support_is_insufficient() -> None:
    question = (
        "Why is persisted run state important when a client disconnects before "
        "a long-running workflow has finished?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    candidate = _supported_semantic_recovery_candidate(
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=[
            _passage(
                "unrelated",
                "A reverse proxy can retry a failed upstream connection.",
                "network-note",
            )
        ],
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )
    assert candidate is None


def test_bb19_persistence_correctness_boundary_recovers_no_answer() -> None:
    question = (
        "Persisted run state can survive a client disconnect. Does that persistence "
        "by itself prove that the workflow output is correct and verified?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    evidence = [
        _passage(
            "durable",
            (
                "Persisted server-side state preserves run progress after a client "
                "disconnect."
            ),
            "durable-note",
        ),
        _passage(
            "completion",
            (
                "Completion verification and acceptance checks happen before the "
                "system declares terminal success."
            ),
            "completion-note",
        ),
    ]
    candidate = _supported_semantic_recovery_candidate(
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )
    assert candidate is not None
    answer_text = str(candidate["answer_text"])
    assert not evaluate_visible_semantics(answer_text, requirements, question)
    assert answer_text.casefold().startswith("no.")
    assert "does not by itself prove" in answer_text.casefold()
    assert "completion verification" in answer_text.casefold()


def test_positive_answerability_recovery_does_not_override_ood_external_marker() -> None:
    question = "What does ZZZAlienProtocol say about client disconnect recovery?"
    verification = {
        "status": "owner_only_safe_abstention",
        "reason_codes": ["PROVIDER_ABSTAINED_WITH_AVAILABLE_EVIDENCE"],
        "unsupported_accepted_claims": 0,
        "citation_locator_valid": True,
    }
    closure = {"failures": ["SEMANTIC_CLOSURE_FAILED"]}
    evidence = [
        _passage(
            "disconnect",
            (
                "A durable persisted server-side run state preserves authority after "
                "the client disconnects."
            ),
            "durable-note",
        )
    ]
    assert not _should_attempt_semantic_recovery(question, verification, closure, evidence)


def test_tesc_partial_candidate_keeps_supported_a_and_explicit_unsupported_b_boundary() -> None:
    question = "Explain durable state and observability for disconnected work."
    durable = _rich_passage(
        "durable",
        "Durable state preserves workflow progress after a client disconnect.",
        "durable-note",
    )
    requirements = [
        SemanticRequirement(
            requirement_id="durable_state",
            instruction="Explain durable state.",
            evidence_terms=("durable", "state", "progress"),
            visible_patterns=(r"\bdurable.{0,80}(?:state|progress)",),
        ),
        SemanticRequirement(
            requirement_id="observability",
            instruction="Explain observability status.",
            evidence_terms=("observability", "status"),
            visible_patterns=(r"\bobservability.{0,80}status",),
        ),
    ]
    candidate = _runtime_bound_candidate(
        answer="Durable state preserves workflow progress after a client disconnect [[claim_1]].",
        question=question,
        intent_class="direct_grounded_knowledge",
        used_items=[durable],
        claims=[
            {
                "claim_id": "claim_1",
                "claim_type": "EVIDENCE_FACT",
                "surface_text": (
                    "Durable state preserves workflow progress after a client disconnect."
                ),
                "evidence_labels": ["e1"],
                "covers": ["durable_state"],
            }
        ],
        label_map={"e1": durable},
        snippet_map={"durable": durable["passage_text"]},
        provider_status="partial",
        requirements=requirements,
        unanswered_dimensions=["observability"],
        semantic_failures=["SEMANTIC_SUPPORT_MISSING:observability"],
    )

    assert candidate["status"] == "partial_candidate"
    assert "Durable state preserves workflow progress" in candidate["answer_text"]
    assert "Unsupported boundary" in candidate["answer_text"]
    assert "observability" in candidate["answer_text"]
    assert all(
        "observability status" not in str(claim.get("surface_text", "")).casefold()
        for claim in candidate["claims"]
        if claim.get("claim_type") != "MODEL_EXPLANATION"
    )


def test_tesc_provider_claim_without_evidence_label_does_not_fallback_to_used_items() -> None:
    question = "Explain durable state for disconnected work."
    durable = _rich_passage(
        "durable",
        "Durable state preserves workflow progress after a client disconnect.",
        "durable-note",
    )

    with pytest.raises(ValueError, match="provider claim to evidence labels"):
        _runtime_bound_candidate(
            answer="Durable state preserves workflow progress after a client disconnect.",
            question=question,
            intent_class="direct_grounded_knowledge",
            used_items=[durable],
            claims=[
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": (
                        "Durable state preserves workflow progress after a client disconnect."
                    ),
                    "evidence_labels": [],
                    "covers": ["durable_state"],
                }
            ],
            label_map={"e1": durable},
            snippet_map={"durable": durable["passage_text"]},
            requirements=[],
        )
