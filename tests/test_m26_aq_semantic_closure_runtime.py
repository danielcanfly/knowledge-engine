from __future__ import annotations

from knowledge_engine.m26_aq_semantic_contract import (
    _contract_compat_module,
    _recover_supported_semantic_answer,
    _should_attempt_semantic_recovery,
    _supported_semantic_recovery_candidate,
    derive_semantic_requirements,
    evaluate_visible_semantics,
)
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


def test_lifecycle_support_proof_recovers_no_semantic_text_without_exact_question() -> None:
    question = (
        "When a browser session is interrupted during a long-running workflow, "
        "why should durable run state be persisted so status and completion can be checked?"
    )
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    requirement_ids = {item.requirement_id for item in requirements}
    assert {
        "durable_state",
        "completion_verification",
        "observability",
    }.issubset(requirement_ids)
    assert "client disconnects before a long-running workflow has finished" not in question

    evidence = [
        _passage("durable", "", "daniel_blog_en__harness-theory-part-6"),
        _passage("completion", "", "daniel_blog_en__harness-theory-part-2"),
        _passage("observability", "", "daniel_blog_en__harness-theory-part-2"),
    ]
    support_proof = [
        {
            "requirement_id": "durable_state",
            "supported": True,
            "score": 3.0,
            "evidence_id": "durable",
            "source_identity": "daniel_blog_en__harness-theory-part-6",
            "exact_support_snippet": (
                "Durable persisted server-side state preserves run progress and "
                "authority after interruption while the workflow continues."
            ),
        },
        {
            "requirement_id": "completion_verification",
            "supported": True,
            "score": 2.0,
            "evidence_id": "completion",
            "source_identity": "daniel_blog_en__harness-theory-part-2",
            "exact_support_snippet": (
                "Completion verification and acceptance checks happen before the "
                "system declares workflow success."
            ),
        },
        {
            "requirement_id": "observability",
            "supported": True,
            "score": 2.0,
            "evidence_id": "observability",
            "source_identity": "daniel_blog_en__harness-theory-part-2",
            "exact_support_snippet": (
                "Observability, status, and reattach handles let the owner inspect "
                "or resume the continuing run."
            ),
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
    assert answer["unsupported_accepted_claims"] == 0
    assert answer["citation_locator_valid"] is True
    assert "durable" in text
    assert "continues" in text
    assert "observability" in text
    assert "completion verification" in text
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
