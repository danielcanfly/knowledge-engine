from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime
from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes

REPRESENTATIVE_CASES = {
    "S05/F006": (
        "How can long-running Codex tasks avoid going in circles?",
        "Codex long-running tasks persist state after each step. A verification boundary "
        "stops the process when completion criteria pass because repeating unchanged work "
        "is rejected.",
    ),
    "S18/F119": (
        "How are OpenClaw's TUI, Dashboard, and Gateway different?",
        "OpenClaw's TUI is the terminal interface, while the Dashboard is the browser "
        "interface and the Gateway coordinates both surfaces.",
    ),
    "S23/F145": (
        "Why does local fine-tuning need a clear definition of what it should change?",
        "Local fine-tuning needs a defined change target because training data and "
        "evaluation must measure that target; otherwise failure cannot be diagnosed.",
    ),
    "S29/F187": (
        "How should someone decide whether a task belongs in OpenClaw?",
        "OpenClaw uses decision criteria before admission because durable agent work needs "
        "boundaries. First evaluate whether the task needs its durable agent workflow.\n"
        "- It needs persistent coordination.\n"
        "- It requires tool execution across steps.\n"
        "- It has a verification boundary.",
    ),
    "S30/F195": (
        "Why is funnel SQL mainly an argument about definitions?",
        "Funnel SQL is mainly definitional because each metric must use the same cohort and "
        "event boundary.\n"
        "1. Which event starts the funnel?\n"
        "2. Which identity joins events?\n"
        "3. Which time window ends the funnel?",
    ),
}


UNTARGETED_CASES = {
    "F008": (
        "What practical Codex workflows combine browser control, computer use, and memory?",
        "Codex workflows combine browser control, computer use, and memory together: "
        "browser control navigates pages, computer use operates interfaces, and memory "
        "preserves context.",
    ),
    "F047": (
        "What do SFT, LoRA, and full fine-tuning each change?",
        "SFT changes behavior through supervised examples, LoRA changes low-rank adapter "
        "weights, and full fine-tuning changes all model weights.",
    ),
    "F078": (
        "How should I evaluate whether a new agent pattern changes my architecture?",
        "First evaluate the agent pattern against architecture decision criteria because "
        "state, tools, and boundaries determine whether migration is needed.",
    ),
    "F079": (
        "How do Codex skills, MCP, hooks, and plugins differ?",
        "Codex skills supply instructions, while MCP supplies external tool contracts, "
        "hooks run lifecycle actions, and plugins package capabilities.",
    ),
    "F105": (
        "How should an LLM wiki handle contradictions?",
        "An LLM wiki should first compare source authority and dates because newer "
        "authoritative evidence can resolve a conflict; then record the conflict and stop "
        "publication until verification.",
    ),
    "F176": (
        "Why are permissions, approvals, and sandboxes not interchangeable?",
        "Permissions grant capabilities, approvals authorize particular actions, while "
        "sandboxes constrain execution because the controls enforce different boundaries.",
    ),
}


def _evidence(evidence_id: str, text: str) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "locator_id": f"loc-{evidence_id}",
        "source_identity": f"source-{evidence_id}",
        "source_id": f"source-{evidence_id}",
        "concept_id": f"concept-{evidence_id}",
        "section_id": f"section-{evidence_id}",
        "section_title": f"section-{evidence_id}",
        "evidence_type": "passage",
        "release_id": "r1-selected-release",
        "artifact_key": "r1-selected-artifact",
        "artifact_sha256": "a" * 64,
        "provenance_record_sha256": "b" * 64,
        "channels": ["r1_selected"],
        "passage_text": text,
        "passage_text_sha256": sha256_bytes(text.encode("utf-8")),
    }


def _plan(
    question: str, evidence: list[Mapping[str, Any]]
) -> tuple[list[runtime.SemanticRequirement], list[dict[str, Any]]]:
    requirements = runtime._compose_selected_evidence_requirements(
        question=question,
        requirements=runtime._semantic_requirements(
            question, "direct_grounded_knowledge"
        ),
        evidence=evidence,
    )
    return requirements, runtime._facet_support_classification(
        requirements=requirements,
        evidence=evidence,
    )


def _grounded_candidate(classification: list[dict[str, Any]]) -> dict[str, Any]:
    claims = []
    for index, facet in enumerate(classification, start=1):
        if facet["support_state"] != "SUPPORTED":
            continue
        evidence_id = facet["supporting_evidence_ids"][0]
        claims.append(
            {
                "claim_id": f"claim-{index}",
                "claim_type": "EVIDENCE_FACT",
                "surface_text": f"Grounded closure for {facet['facet_id']}.",
                "covers": [facet["facet_id"]],
                "support_refs": [
                    {
                        "evidence_id": evidence_id,
                        "locator_id": f"loc-{evidence_id}",
                        "exact_quote": "selected evidence",
                    }
                ],
            }
        )
    return {"status": "answer_candidate", "claims": claims}


@pytest.mark.parametrize(
    ("case_id", "question", "selected_text"),
    [(case_id, *case) for case_id, case in REPRESENTATIVE_CASES.items()],
)
def test_representative_failure_first_facet_closure(
    case_id: str,
    question: str,
    selected_text: str,
) -> None:
    evidence = [_evidence(f"{case_id}-e1", selected_text)]
    requirements, classification = _plan(question, evidence)
    assert requirements
    assert {item["support_state"] for item in classification} == {"SUPPORTED"}
    candidate = _grounded_candidate(classification)
    supported = [
        requirement
        for requirement, state in zip(requirements, classification, strict=True)
        if state["support_state"] == "SUPPORTED"
    ]
    assert not runtime._candidate_lacks_material_requirement_coverage(
        candidate, requirements=supported
    )
    trace = runtime._facet_closure_trace(
        classification=classification,
        candidate=candidate,
    )
    assert trace["supported_subset_of_grounded_coverage"] is True
    assert trace["post_r1_corpus_reachback"] is False


@pytest.mark.parametrize(
    ("failure_id", "question", "selected_text"),
    [(failure_id, *case) for failure_id, case in UNTARGETED_CASES.items()],
)
def test_untargeted_same_family_facet_closure(
    failure_id: str,
    question: str,
    selected_text: str,
) -> None:
    requirements, classification = _plan(
        question, [_evidence(f"{failure_id}-e1", selected_text)]
    )
    assert requirements
    assert all(item["support_state"] == "SUPPORTED" for item in classification)
    assert not runtime._candidate_lacks_material_requirement_coverage(
        _grounded_candidate(classification), requirements=requirements
    )


def test_compositional_entity_and_question_shape_facets_coexist() -> None:
    requirements = runtime._semantic_requirements(
        "How do Codex skills, MCP, hooks, and plugins differ?",
        "direct_grounded_knowledge",
    )
    ids = {item.requirement_id for item in requirements}
    assert {
        "entity_codex_skills",
        "entity_mcp",
        "entity_hooks",
        "entity_plugins",
        "comparison_or_distinction",
        "explanatory_answer",
    }.issubset(ids)


def test_supported_required_facets_use_subset_not_existential_gate() -> None:
    requirements = [
        runtime.SemanticRequirement("facet_a", "A", ("a",), ()),
        runtime.SemanticRequirement("facet_b", "B", ("b",), ()),
    ]
    one = {
        "claims": [
            {
                "claim_type": "EVIDENCE_FACT",
                "covers": ["facet_a"],
                "support_refs": [{"evidence_id": "e1"}],
            }
        ]
    }
    assert runtime._candidate_lacks_material_requirement_coverage(
        one, requirements=requirements
    )
    one["claims"].append(
        {
            "claim_type": "EVIDENCE_SYNTHESIS",
            "covers": ["facet_b"],
            "support_refs": [{"evidence_id": "e2"}],
        }
    )
    assert not runtime._candidate_lacks_material_requirement_coverage(
        one, requirements=requirements
    )


def test_model_explanation_cannot_close_material_facet() -> None:
    requirement = runtime.SemanticRequirement("facet_a", "A", ("a",), ())
    candidate = {
        "claims": [
            {
                "claim_type": "MODEL_EXPLANATION",
                "covers": ["facet_a"],
                "support_refs": [],
            }
        ]
    }
    assert runtime._candidate_lacks_material_requirement_coverage(
        candidate, requirements=[requirement]
    )
    trace = runtime._facet_closure_trace(
        classification=[
            {
                "facet_id": "facet_a",
                "support_state": "SUPPORTED",
                "supporting_evidence_ids": ["e1"],
            }
        ],
        candidate=candidate,
    )
    assert trace["material_claim_ids_by_facet"]["facet_a"] == []


def test_support_states_are_selected_evidence_only() -> None:
    requirements = [
        runtime.SemanticRequirement("supported", "", ("alpha", "boundary"), ()),
        runtime.SemanticRequirement("unsupported", "", ("zeta", "protocol"), ()),
    ]
    evidence = [_evidence("e1", "Alpha has a defined boundary and policy.")]
    states = runtime._facet_support_classification(
        requirements=requirements, evidence=evidence
    )
    assert [item["support_state"] for item in states] == [
        "SUPPORTED",
        "UNSUPPORTED",
    ]
    unknown = runtime._facet_support_classification(
        requirements=requirements,
        evidence=[{"evidence_id": "e2"}],
    )
    assert {item["support_state"] for item in unknown} == {"UNKNOWN"}
    assert states[0]["selected_evidence_ids_considered"] == ["e1"]


def test_provider_contract_exposes_supported_and_unresolved_stable_facets() -> None:
    requirements = [
        runtime.SemanticRequirement(
            "supported", "State alpha boundary.", ("alpha", "boundary"), ()
        ),
        runtime.SemanticRequirement(
            "unsupported", "State zeta protocol.", ("zeta", "protocol"), ()
        ),
    ]
    payload, _label_map, _snippets = runtime._compact_provider_payload(
        question="How should alpha handle zeta?",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence("e1", "Alpha has a defined boundary.")],
        requirements=requirements,
        repair=False,
        previous_failures=[],
    )
    task = json.loads(payload["messages"][0]["content"])
    facets = {item["facet_id"]: item for item in task["required_facets"]}
    assert facets["supported"]["support_state"] == "SUPPORTED"
    assert facets["supported"]["supporting_evidence_labels"] == ["e1"]
    assert facets["unsupported"]["support_state"] == "UNSUPPORTED"
    assert task["must_state"] == ["State alpha boundary."]
    assert task["required_answer_status"] == "partial"
    assert task["unresolved_facet_ids"] == ["unsupported"]


def test_strengthening_is_closed_r1_selected_evidence_universe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("post-R1 corpus reachback")

    monkeypatch.setattr(runtime.legacy, "_release_documents", forbidden)
    monkeypatch.setattr(runtime, "_exact_named_graph_edge", forbidden)
    selected = [_evidence("e1", "Selected evidence remains closed.")]
    strengthened, proof = runtime._strengthen_evidence(
        bundle=object(),
        evidence=selected,
        lexical_result={"results": [{"section_id": "not-authorized"}]},
        trace_id="closed-r1",
        question="What does selected evidence establish?",
        intent_class="direct_grounded_knowledge",
        requirements=[],
    )
    assert [item["evidence_id"] for item in strengthened] == ["e1"]
    assert all(
        "semantic_requirement_recovery" not in item.get("channels", [])
        for item in strengthened
    )
    assert proof["matched"] is False


def test_m03_comparison_order_reversal_preserves_facet_set() -> None:
    left = runtime._semantic_requirements(
        "How are SFT, LoRA, and full fine-tuning different?",
        "direct_grounded_knowledge",
    )
    right = runtime._semantic_requirements(
        "How are full fine-tuning, LoRA, and SFT different?",
        "direct_grounded_knowledge",
    )
    assert {item.requirement_id for item in left} == {
        item.requirement_id for item in right
    }


def test_m04_and_m10_finite_list_and_cross_chunk_closure() -> None:
    question = "How are Alpha, Beta, and Gamma different?"
    evidence = [
        _evidence("e1", "Alpha stores state before execution."),
        _evidence("e2", "Beta validates output after execution."),
        _evidence("e3", "Gamma reports status while the other components execute."),
        _evidence("e4", "Components include:\n1. Alpha state\n2. Beta validation\n3. Gamma status"),
    ]
    requirements, classification = _plan(question, evidence)
    ids = {item.requirement_id for item in requirements}
    assert len([item for item in ids if item.startswith("enumeration_member_")]) == 3
    assert next(
        item for item in classification if item["facet_id"] == "comparison_or_distinction"
    )["support_state"] == "SUPPORTED"


def test_m08_selected_evidence_order_does_not_change_support_state() -> None:
    question = "How are Alpha, Beta, and Gamma different?"
    evidence = [
        _evidence("e1", "Alpha stores state."),
        _evidence("e2", "Beta validates output."),
        _evidence("e3", "Gamma reports status while work runs."),
    ]
    _requirements, forward = _plan(question, evidence)
    _requirements, reverse = _plan(question, list(reversed(evidence)))
    assert {item["facet_id"]: item["support_state"] for item in forward} == {
        item["facet_id"]: item["support_state"] for item in reverse
    }


def test_m11_and_m16_source_removal_and_unsupported_addition_are_not_fabricated() -> None:
    question = "How are Alpha, Beta, and Gamma different?"
    evidence = [
        _evidence("e1", "Alpha stores state."),
        _evidence("e2", "Beta validates output."),
        _evidence("e3", "Gamma reports status."),
    ]
    requirements, complete = _plan(question, evidence)
    reduced = runtime._facet_support_classification(
        requirements=requirements,
        evidence=evidence[:2],
    )
    assert any(item["support_state"] == "UNSUPPORTED" for item in reduced)
    added = [
        *requirements,
        runtime.SemanticRequirement(
            "unsupported_added_facet", "Do not invent this.", ("qzxv", "frobnicate"), ()
        ),
    ]
    states = runtime._facet_support_classification(
        requirements=added,
        evidence=evidence,
    )
    assert complete
    assert states[-1]["support_state"] == "UNSUPPORTED"


class _NoCallProvider:
    def __init__(self) -> None:
        self.calls = 0

    def call(self, *_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
        self.calls += 1
        raise AssertionError("provider must not be called")


class _ContractDrivenProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def call(self, payload: dict[str, Any], call_class: str) -> Mapping[str, Any]:
        self.calls.append(call_class)
        task = json.loads(payload["messages"][0]["content"])
        if call_class == runtime.SEMANTIC_REVIEW_CALL_CLASS:
            return {
                "text": json.dumps(
                    {
                        "schema_version": runtime.SEMANTIC_REVIEW_SCHEMA_VERSION,
                        "claim_judgments": [
                            {
                                "claim_id": case["claim_id"],
                                "verdict": "ENTAILED",
                                "evidence_ids": case["allowed_evidence_ids"],
                            }
                            for case in task["claim_cases"]
                        ],
                        "visible_coverage": {
                            "verdict": "COVERED",
                            "uncovered_assertions": [],
                        },
                    }
                ),
                "call_class": call_class,
                "usage": {},
                "cost_usd": "0",
            }
        supported = [
            item
            for item in task["required_facets"]
            if item["support_state"] == "SUPPORTED"
        ]
        labels = list(
            dict.fromkeys(
                label
                for item in supported
                for label in item["supporting_evidence_labels"]
            )
        )
        unresolved = list(task["unresolved_facet_ids"])
        return {
            "text": json.dumps(
                {
                    "schema_version": runtime.COMPACT_CLOSURE_SCHEMA_VERSION,
                    "status": "partial" if unresolved else "answer",
                    "segments": [
                        {
                            "segment_id": "s1",
                            "semantic_role": "material_claim",
                            "claim_id": "claim_1",
                            "claim_type": "EVIDENCE_SYNTHESIS",
                            "text": "Selected evidence supports the requested bounded answer.",
                            "evidence_labels": labels,
                            "covers": [item["facet_id"] for item in supported],
                        }
                    ],
                    "unanswered_dimensions": unresolved,
                    "abstention_reason": None,
                }
            ),
            "call_class": call_class,
            "usage": {},
            "cost_usd": "0",
        }


def test_provider_free_complete_candidate_publishes_only_after_set_closure() -> None:
    question, text = REPRESENTATIVE_CASES["S18/F119"]
    evidence = [_evidence("e1", text)]
    provider = _ContractDrivenProvider()
    answer, closure = runtime._synthesize_and_verify(
        question=question,
        trace_id="complete-closure",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=runtime._semantic_requirements(
            question, "direct_grounded_knowledge"
        ),
        endpoint_proof={"required": False, "matched": False},
    )
    assert answer["status"] == "owner_only_cited_answer"
    assert closure["facet_closure"]["supported_subset_of_grounded_coverage"] is True
    assert closure["facet_closure"]["unresolved_required_facet_ids"] == []
    supported_ids = closure["facet_closure"]["supported_required_facet_ids"]
    assert all(
        closure["facet_closure"]["material_claim_ids_by_facet"][facet_id]
        for facet_id in supported_ids
    )
    assert all(
        closure["facet_closure"]["claim_local_evidence_ids_by_facet"][facet_id]
        for facet_id in supported_ids
    )
    assert provider.calls == [
        "aq_semantic_closure",
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
    ]


def test_provider_free_unsupported_facet_publishes_honest_partial() -> None:
    evidence = [_evidence("e1", "Alpha has a defined boundary and policy.")]
    requirements = [
        runtime.SemanticRequirement("supported", "", ("alpha", "boundary"), ()),
        runtime.SemanticRequirement("unsupported", "", ("zeta", "protocol"), ()),
    ]
    provider = _ContractDrivenProvider()
    answer, closure = runtime._synthesize_and_verify(
        question="How should alpha handle the zeta protocol?",
        trace_id="unsupported-partial",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["multi_evidence_verification"]["partial_answer"] is True
    assert closure["facet_closure"]["unresolved_required_facet_ids"] == [
        "unsupported"
    ]
    assert closure["facet_closure"]["supported_subset_of_grounded_coverage"] is True


@pytest.mark.parametrize(
    "question",
    [
        "What is the orbital composition of a fictional element named qzxv?",
        "Explain the unpublished protocol frobnicate-771 in the source corpus.",
        "Which source documents the imaginary zorp telemetry standard?",
    ],
)
def test_ta01_ta03_empty_r1_selection_abstains_without_provider(question: str) -> None:
    provider = _NoCallProvider()
    answer, closure = runtime._synthesize_and_verify(
        question=question,
        trace_id="true-abstain",
        intent_class="direct_grounded_knowledge",
        evidence=[],
        provider_client=provider,
        requirements=runtime._semantic_requirements(
            question, "direct_grounded_knowledge"
        ),
        endpoint_proof={"required": False, "matched": False},
    )
    assert answer["status"] == "owner_only_safe_abstention"
    assert provider.calls == 0
    assert closure["failures"] == ["NO_R1_SELECTED_EVIDENCE"]
