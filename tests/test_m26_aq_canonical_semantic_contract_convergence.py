from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from decimal import Decimal
from typing import Any

from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes


EXPECTED_ENTRYPOINT = "knowledge_engine.m26_aq_semantic_contract.run_owner_arbitrary_query"
SEMANTIC_REVIEW_CALL_CLASS = "aq_claim_semantic_entailment"


class _CompactAbstainingProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.cost = Decimal("0")

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls += 1
        self.cost += Decimal("0.00001")
        return {
            "text": json.dumps({"status": "abstain", "answer": "", "used": []}),
            "usage": {"input_tokens": 16, "output_tokens": 4},
            "cost_usd": "0.00001",
            "latency_ms": 1,
            "response_id": f"compact-abstain-{self.calls}",
            "call_class": call_class,
        }


class _TypedCompactProvider:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.calls = 0
        self.cost = Decimal("0")

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls += 1
        self.cost += Decimal("0.00001")
        if call_class == SEMANTIC_REVIEW_CALL_CLASS:
            task = json.loads(payload["messages"][0]["content"])
            return {
                "text": json.dumps(
                    {
                        "schema_version": "m26-claim-entailment-review/v1",
                        "claim_judgments": [
                            {
                                "claim_id": str(case["claim_id"]),
                                "verdict": "ENTAILED",
                                "evidence_ids": [
                                    str(item["evidence_id"])
                                    for item in case["evidence"]
                                ],
                            }
                            for case in task["claim_cases"]
                        ],
                        "visible_coverage": {
                            "verdict": "COVERED",
                            "uncovered_assertions": [],
                        },
                    }
                ),
                "usage": {"input_tokens": 32, "output_tokens": 32},
                "cost_usd": "0.00001",
                "latency_ms": 1,
                "response_id": f"typed-compact-review-{self.calls}",
                "call_class": call_class,
            }
        return {
            "text": json.dumps(self.body),
            "usage": {"input_tokens": 32, "output_tokens": 32},
            "cost_usd": "0.00001",
            "latency_ms": 1,
            "response_id": f"typed-compact-{self.calls}",
            "call_class": call_class,
        }


def _passage(evidence_id: str, text: str, *, concept_id: str = "") -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "passage",
        "locator_id": f"loc-{evidence_id}",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "concept_id": concept_id or f"concept-{evidence_id}",
        "section_id": f"section-{evidence_id}",
        "release_id": "release-test",
        "source_id": f"source-{evidence_id}",
        "source_identity": f"source-{evidence_id}",
        "channels": ["semantic_requirement_recovery"],
        "passage_text": text,
        "passage_text_sha256": sha256_bytes(text.encode()),
        "provenance_record_sha256": "b" * 64,
        "retrieval_metadata": {
            "coverage_terms": [
                token.casefold()
                for token in text.replace(".", " ").replace(",", " ").split()
            ]
        },
    }


def _graph_edge(
    evidence_id: str,
    *,
    edge_id: str,
    source: str,
    target: str,
    text: str,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "graph_edge",
        "locator_id": f"loc-{evidence_id}",
        "artifact_key": "graph-test",
        "artifact_sha256": "c" * 64,
        "concept_id": source,
        "section_id": edge_id,
        "release_id": "release-test",
        "source_id": "relation-graph",
        "source_identity": "relation-graph",
        "channels": ["graph_edge"],
        "edge_id": edge_id,
        "edge_source": source,
        "edge_target": target,
        "relation_type": "precedes",
        "passage_text": text,
        "passage_text_sha256": sha256_bytes(text.encode()),
        "provenance_record_sha256": "d" * 64,
        "retrieval_metadata": {"coverage_terms": ["precedes", "ordering", "sequence"]},
    }


def _assert_abstention_is_not_recovered(
    answer: dict[str, Any],
    closure: dict[str, Any],
) -> None:
    assert answer["status"] == "owner_only_safe_abstention"
    assert answer["answer_source"] == "safe_abstention"
    assert answer["answer_text"] == ""
    assert answer["unsupported_accepted_claims"] == 0
    assert closure["broad_deterministic_fallback_used"] is False
    assert "semantic_synthesis_recovery" not in closure


def _run(code: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout.strip()


def test_fresh_process_fingerprints_converge() -> None:
    code = """
    from knowledge_engine.m26_aq_semantic_contract import (
        CANONICAL_RUNTIME_ENTRYPOINT,
        semantic_contract_fingerprint,
    )
    import knowledge_engine.m26_ask_api as ask
    import scripts.m26_aq_final_closure as final
    import scripts.m26_aq_generalized_closure as generalized
    import scripts.m26_aq_targeted_answerability_closure as targeted

    fingerprint = semantic_contract_fingerprint()
    values = {
        "canonical": fingerprint,
        "ask": ask.semantic_contract_fingerprint(),
        "final": final.semantic_contract_fingerprint(),
        "generalized": generalized.semantic_contract_fingerprint(),
        "targeted": targeted.semantic_contract_fingerprint(),
    }
    assert len(set(values.values())) == 1, values
    assert ask.RUNTIME_ENTRYPOINT == CANONICAL_RUNTIME_ENTRYPOINT
    assert final.CANONICAL_RUNTIME_ENTRYPOINT == CANONICAL_RUNTIME_ENTRYPOINT
    assert generalized.CANONICAL_RUNTIME_ENTRYPOINT == CANONICAL_RUNTIME_ENTRYPOINT
    assert targeted.CANONICAL_RUNTIME_ENTRYPOINT == CANONICAL_RUNTIME_ENTRYPOINT
    print(fingerprint)
    """
    assert _run(code)


def test_production_import_graph_has_no_aq_patch_modules() -> None:
    code = """
    import sys
    import knowledge_engine.m26_production_api  # noqa: F401
    loaded = [
        name for name in sys.modules
        if name.startswith("knowledge_engine.m26_aq_") and "patch" in name
    ]
    assert loaded == [], loaded
    """
    _run(code)


def test_entrypoint_single_source_and_no_stale_literal() -> None:
    paths = [
        "src/knowledge_engine/m26_ask_api.py",
        "src/knowledge_engine/m26_production_api.py",
        "scripts/m26_aq_remote_production_closure.sh",
        "scripts/m26_aq_final_closure.py",
        "scripts/m26_aq_generalized_closure.py",
        "scripts/m26_aq_targeted_answerability_closure.py",
    ]
    stale = "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
    for path in paths:
        text = open(path, encoding="utf-8").read()
        assert stale not in text, path
    canonical_source = open(
        "src/knowledge_engine/m26_aq_semantic_contract.py",
        encoding="utf-8",
    ).read()
    assert canonical_source.count(EXPECTED_ENTRYPOINT) == 1


def test_authority_boundary_positive_and_negative_controls() -> None:
    code = """
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        evaluate_visible_semantics,
    )
    question = "How should the state machine and adaptive replanner handle revisions?"
    requirements = derive_semantic_requirements(
        question,
        "direct_grounded_knowledge",
        base_requirements=[],
    )
    authority = [item for item in requirements if item.requirement_id == "authority_boundary"]
    assert requirements == authority
    assert len(authority) == 1
    positive = (
        "Revisions stay within the state-machine policy and approval gates rather "
        "than expanding the replanner's authority."
    )
    negative = "The state machine tracks workflow state and the replanner changes future steps."
    assert evaluate_visible_semantics(positive, authority, question) == []
    assert evaluate_visible_semantics(negative, authority, question) == [
        "SEMANTIC_VISIBLE_MISSING:authority_boundary"
    ]
    """
    _run(code)


def test_shared_part_entities_are_derived_without_case_specific_text() -> None:
    from knowledge_engine.m26_aq_semantic_contract import canonical_question_entities

    entities = canonical_question_entities(
        "If the relation graph records Widget Harness Part 1 as preceding Part 2, "
        "what follows from that edge?"
    )

    assert "Widget Harness Part 1" in entities
    assert "Widget Harness Part 2" in entities


def test_canonical_provider_paraphrase_does_not_require_patch_v2(monkeypatch: Any) -> None:
    import knowledge_engine.m26_aq_semantic_contract as contract

    def fail_if_called() -> None:
        raise AssertionError("canonical synthesis must not import compatibility patch modules")

    monkeypatch.setattr(contract, "_contract_compat_module", fail_if_called)
    question = "What does Graphology do for graph data?"
    answer_text = "Graphology keeps and analyzes graph data."
    requirements = [
        contract.SemanticRequirement(
            requirement_id="graphology_storage",
            instruction="Explain that Graphology stores and analyses graph data.",
            evidence_terms=("Graphology", "stores", "graph", "data", "analysis"),
            visible_patterns=(r"Graphology stores graph data exactly",),
        )
    ]
    evidence = [
        _passage(
            "ev-graphology",
            "Graphology stores graph data and supports graph analysis.",
            concept_id="Graphology",
        )
    ]
    provider = _TypedCompactProvider(
        {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": answer_text,
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": answer_text,
                    "evidence_labels": ["e1"],
                    "covers": ["graphology_storage"],
                }
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }
    )

    answer, closure = contract.synthesize_and_verify(
        question=question,
        trace_id="trace-canonical-paraphrase",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )

    assert provider.calls == 2
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_text"] == answer_text
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert "semantic_synthesis_recovery" not in closure
    assert closure["broad_deterministic_fallback_used"] is False


def test_provider_abstention_does_not_recover_precedes_relation() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    question = (
        "If the relation graph records Widget Harness Part 1 as preceding Part 2, "
        "what can we infer and what can we not infer from that edge?"
    )
    source = "concept-widget-part-1"
    target = "concept-widget-part-2"
    evidence = [
        _graph_edge(
            "ev-edge",
            edge_id="edge-widget-precedes",
            source=source,
            target=target,
            text=(
                "Widget Harness Part 1 precedes Widget Harness Part 2 in the "
                "relation graph."
            ),
        ),
        _passage(
            "ev-source",
            "Widget Harness Part 1 is the first article in the Widget Harness series.",
            concept_id=source,
        ),
        _passage(
            "ev-target",
            "Widget Harness Part 2 is the second article in the Widget Harness series.",
            concept_id=target,
        ),
        _passage(
            "ev-boundary",
            (
                "A precedes edge supports ordering and sequence navigation only. "
                "It does not prove dependency, causality, implementation, or requirement."
            ),
        ),
    ]

    answer, closure = synthesize_and_verify(
        question=question,
        trace_id="trace-precedes-recovery",
        intent_class="graph_relationship",
        evidence=evidence,
        provider_client=_CompactAbstainingProvider(),
        requirements=derive_semantic_requirements(question, "graph_relationship"),
        endpoint_proof={
            "required": True,
            "matched": True,
            "question_entities": ["Widget Harness Part 1", "Widget Harness Part 2"],
            "edge_id": "edge-widget-precedes",
            "edge_source": source,
            "edge_target": target,
            "relation_type": "precedes",
        },
    )

    _assert_abstention_is_not_recovered(answer, closure)


def test_provider_abstention_does_not_recover_adaptive_planning_answer() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    question = (
        "When should adaptive planning replan globally instead of repairing one step locally?"
    )
    evidence = [
        _passage(
            "ev-global",
            (
                "Adaptive planning should replan globally when a changed premise "
                "invalidates the remaining plan and local repair cannot preserve the "
                "later dependencies."
            ),
        ),
        _passage(
            "ev-local",
            (
                "Local repair is appropriate when one step implementation failed, the "
                "objective remains valid, and later dependencies remain unchanged."
            ),
        ),
    ]

    answer, closure = synthesize_and_verify(
        question=question,
        trace_id="trace-adaptive-recovery",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=_CompactAbstainingProvider(),
        requirements=derive_semantic_requirements(
            question,
            "direct_grounded_knowledge",
        ),
        endpoint_proof={"required": False, "matched": False},
    )

    _assert_abstention_is_not_recovered(answer, closure)


def test_provider_abstention_does_not_recover_disconnect_state_answer() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    question = (
        "Why is persisted run state important when a client disconnects before a "
        "long-running workflow has finished?"
    )
    requirements = derive_semantic_requirements(
        question,
        "direct_grounded_knowledge",
    )
    assert {item.requirement_id for item in requirements} == {
        "durable_state",
        "completion_verification",
        "observability",
    }
    evidence = [
        _passage(
            "ev-durable",
            (
                "Durable persisted server-side state preserves run progress and "
                "authority after a client disconnect while the workflow continues."
            ),
        ),
        _passage(
            "ev-status",
            "Observability and reattachment expose status for the continuing run.",
        ),
        _passage(
            "ev-complete",
            "Completion verification or acceptance happens before success is declared.",
        ),
    ]

    answer, closure = synthesize_and_verify(
        question=question,
        trace_id="trace-disconnect-recovery",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=_CompactAbstainingProvider(),
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )

    _assert_abstention_is_not_recovered(answer, closure)


def test_provider_abstention_does_not_recover_pure_precedes_ordering_relation() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        _canonical_intent_class,
        derive_semantic_requirements,
        synthesize_and_verify,
    )
    from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy

    question = (
        "Harness Theory Part 1 comes before Part 2 in the relation graph. "
        "What relationship is actually recorded between those two notes?"
    )
    source = "concept-harness-part-1"
    target = "concept-harness-part-2"
    evidence = [
        _graph_edge(
            "ev-edge",
            edge_id="edge-harness-precedes",
            source=source,
            target=target,
            text=(
                "Harness Theory Part 1 precedes Harness Theory Part 2 in the "
                "relation graph."
            ),
        ),
        _passage("ev-source", "Harness Theory Part 1 is the first note.", concept_id=source),
        _passage("ev-target", "Harness Theory Part 2 is the second note.", concept_id=target),
    ]
    intent = _canonical_intent_class(question, legacy._intent_class(question))

    answer, closure = synthesize_and_verify(
        question=question,
        trace_id="trace-pure-precedes",
        intent_class=intent,
        evidence=evidence,
        provider_client=_CompactAbstainingProvider(),
        requirements=derive_semantic_requirements(question, intent),
        endpoint_proof={
            "required": True,
            "matched": True,
            "question_entities": ["Harness Theory Part 1", "Harness Theory Part 2"],
            "edge_id": "edge-harness-precedes",
            "edge_source": source,
            "edge_target": target,
            "relation_type": "precedes",
        },
    )

    assert intent == "graph_relationship"
    _assert_abstention_is_not_recovered(answer, closure)


def test_provider_abstention_does_not_recover_natural_control_comparison_surfaces() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    scenarios = [
        (
            "Compare a dependency DAG with persisted run state: what does each constrain or preserve, and why can one not replace the other?",
            [
                _passage(
                    "ev-dag",
                    (
                        "A dependency DAG constrains ordering and dependencies between "
                        "steps, so it constrains what each step can do."
                    ),
                ),
                _passage(
                    "ev-state",
                    (
                        "Persisted run state preserves progress and authority across "
                        "interruption; persisted state does not replace the DAG "
                        "dependency structure."
                    ),
                ),
            ],
            ("whereas", "dag", "persisted run state"),
        ),
        (
            "Compare post-execution verification with human approval before a sensitive action. What different failure modes are those controls meant to address?",
            [
                _passage(
                    "ev-verify",
                    (
                        "Post-execution verification checks whether the produced result "
                        "is supported and complete, addressing incorrect output failure modes."
                    ),
                ),
                _passage(
                    "ev-human",
                    (
                        "Human approval is an authority gate before a sensitive action "
                        "is taken, addressing unapproved action failure modes."
                    ),
                ),
            ],
            ("while", "verification", "human approval"),
        ),
    ]

    for question, evidence, expected_terms in scenarios:
        answer, closure = synthesize_and_verify(
            question=question,
            trace_id="trace-natural-comparison",
            intent_class="cross_document_comparison",
            evidence=evidence,
            provider_client=_CompactAbstainingProvider(),
            requirements=derive_semantic_requirements(
                question,
                "cross_document_comparison",
            ),
            endpoint_proof={"required": False, "matched": False},
        )
        del expected_terms
        _assert_abstention_is_not_recovered(answer, closure)


def test_provider_abstention_does_not_recover_sigma_authority_surface() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    question = (
        "If a Sigma.js visualization appears to disagree with the underlying source "
        "material, which layer should be treated as authority and what should a "
        "trustworthy answer cite?"
    )
    evidence = [
        _passage(
            "ev-sigma",
            "Sigma.js is a visualization rendering surface for graph interaction.",
        ),
        _passage(
            "ev-source",
            (
                "The canonical source material and provenance record are the source "
                "of trust and authority."
            ),
        ),
    ]

    answer, closure = synthesize_and_verify(
        question=question,
        trace_id="trace-sigma-authority",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=_CompactAbstainingProvider(),
        requirements=derive_semantic_requirements(
            question,
            "direct_grounded_knowledge",
        ),
        endpoint_proof={"required": False, "matched": False},
    )

    _assert_abstention_is_not_recovered(answer, closure)


def test_provider_abstention_does_not_recover_persistence_correctness_boundary() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    question = (
        "Persisted run state can survive a client disconnect. Does that persistence "
        "by itself prove that the workflow output is correct and verified?"
    )
    requirements = derive_semantic_requirements(
        question,
        "direct_grounded_knowledge",
    )
    assert {item.requirement_id for item in requirements} == {
        "durable_state",
        "completion_verification",
    }
    evidence = [
        _passage(
            "ev-state-and-verify",
            (
                "Persisted run state can survive a client disconnect and preserve "
                "durable progress, but persistence by itself does not prove correctness. "
                "Completion verification and acceptance evidence are required before "
                "the workflow output is correct and verified; verification is separate evidence."
            ),
        ),
    ]

    answer, closure = synthesize_and_verify(
        question=question,
        trace_id="trace-persistence-correctness",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=_CompactAbstainingProvider(),
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )

    _assert_abstention_is_not_recovered(answer, closure)


def test_cobalt_orchid_bb18_remains_safe_abstention() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    question = (
        "What launch date was announced for the nonexistent cobalt-orchid "
        "moon-ferry ticketing protocol?"
    )
    evidence = [
        _passage(
            "ev-incidental",
            "A production article discusses launch planning for an unrelated system.",
        )
    ]

    answer, closure = synthesize_and_verify(
        question=question,
        trace_id="trace-bb18",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=_CompactAbstainingProvider(),
        requirements=derive_semantic_requirements(
            question,
            "direct_grounded_knowledge",
        ),
        endpoint_proof={"required": False, "matched": False},
    )

    assert answer["status"] == "owner_only_safe_abstention"
    assert answer["answer_text"] == ""
    assert closure["failures"]


def test_provider_abstention_does_not_recover_unestablished_compound_subjects() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    evidence = [
        _passage(
            "ev-adjacent-retry",
            (
                "The workflow engine records failed executions, uses retry logic, "
                "stores interval configuration, and documents protocol boundaries."
            ),
        )
    ]
    questions = [
        (
            "What retry interval is specified by the nonexistent silver-pine "
            "lunar relay protocol for failed workflow executions?"
        ),
        "What retry interval is specified by the aurora-maple orbital dispatch protocol?",
        "How often does the Helio Delta Routing Module's retry timer fire?",
        "The retry interval of the invented cedar-ridge workflow lattice is what?",
    ]

    for question in questions:
        answer, closure = synthesize_and_verify(
            question=question,
            trace_id="trace-compound-subject-recovery-stop",
            intent_class="direct_grounded_knowledge",
            evidence=evidence,
            provider_client=_CompactAbstainingProvider(),
            requirements=derive_semantic_requirements(
                question,
                "direct_grounded_knowledge",
            ),
            endpoint_proof={"required": False, "matched": False},
        )

        assert answer["status"] == "owner_only_safe_abstention"
        assert answer["answer_source"] == "safe_abstention"
        assert answer["answer_text"] == ""
        assert closure["failures"]
        assert "semantic_synthesis_recovery" not in closure


def test_provider_abstention_does_not_recover_unsupported_external_marker_question() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    question = "Which exact database table stores Contoso 2025 audited quarterly revenue?"
    evidence = [
        _passage(
            "ev-incidental-year",
            "Production concept 2025 has a hydrated section, source, and provenance record.",
        )
    ]

    answer, closure = synthesize_and_verify(
        question=question,
        trace_id="trace-ood-hard-stop",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=_CompactAbstainingProvider(),
        requirements=derive_semantic_requirements(
            question,
            "direct_grounded_knowledge",
        ),
        endpoint_proof={"required": False, "matched": False},
    )

    assert answer["status"] == "owner_only_safe_abstention"
    assert answer["answer_source"] == "safe_abstention"
    assert answer["answer_text"] == ""
    assert closure["failures"]
    assert closure["broad_deterministic_fallback_used"] is False
