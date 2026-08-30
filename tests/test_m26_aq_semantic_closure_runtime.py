from __future__ import annotations

import inspect
import json
import time
from typing import Any

import pytest

from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy
from knowledge_engine import m26_pa7_semantic_closure_runtime as closure_runtime
from knowledge_engine.m26_aq_semantic_contract import (
    _contract_compat_module,
    _publish_support_proof_recovered_answer,
    _recover_supported_semantic_answer,
    _should_attempt_semantic_recovery,
    _supported_semantic_recovery_candidate,
    derive_semantic_requirements,
    evaluate_visible_semantics,
)
from knowledge_engine.m26_cloudflare_provider_router import (
    CLOUDFLARE_PROVIDER,
    MINIMAX_PROVIDER,
    MINIMAX_REVIEWER_RATE_LIMIT_429,
    SEMANTIC_REVIEW_CALL_CLASS,
    CloudflareRouterState,
    ProviderRoutingClient,
)
from knowledge_engine.m26_pa5_v8_live import LiveGateError
from knowledge_engine.m26_pa7_semantic_closure_runtime import (
    SemanticRequirement,
    _bounded_publication_candidate,
    _compact_provider_payload,
    _parse_compact_provider_result,
    _requirement_support_failures,
    _response_from_verification,
    _runtime_bound_candidate,
    _semantic_requirements,
    _semantic_review_payload,
    _synthesize_and_verify,
    _verification_candidate,
    _visible_semantic_failures,
)
from knowledge_engine.m26_production_answer_bundle import ProductionAnswerBundle
from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes

SEGMENT_SCHEMA_VERSION = "m26-fas-synthesis/segments/v1"


def _segment_body_from_legacy(body: dict[str, Any]) -> dict[str, Any]:
    if "segments" in body:
        return body
    claims = [
        dict(claim)
        for claim in body.get("claims", [])
        if isinstance(claim, dict)
    ]
    segments = []
    for index, claim in enumerate(claims, start=1):
        claim_type = str(claim.get("claim_type", "EVIDENCE_FACT"))
        segments.append(
            {
                "segment_id": f"s{index}",
                "semantic_role": (
                    "model_explanation"
                    if claim_type == "MODEL_EXPLANATION"
                    else "material_claim"
                ),
                "claim_id": str(claim.get("claim_id", f"claim_{index}")),
                "claim_type": claim_type,
                "text": str(claim.get("surface_text", "")),
                "evidence_labels": (
                    []
                    if claim_type == "MODEL_EXPLANATION"
                    else list(claim.get("evidence_labels", []))
                ),
                "covers": list(claim.get("covers", [])),
                "unanswered_dimensions": list(
                    claim.get("unanswered_dimensions", [])
                ),
            }
        )
    return {
        "schema_version": SEGMENT_SCHEMA_VERSION,
        "status": str(body.get("status", "answer")),
        "segments": segments,
        "unanswered_dimensions": list(body.get("unanswered_dimensions", [])),
        "abstention_reason": body.get("abstention_reason"),
    }


class _AbstainingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], str]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append((payload, call_class))
        return {
            "text": json.dumps(
                _segment_body_from_legacy(
                    {"status": "abstain", "answer_text": "", "claims": []}
                )
            ),
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "cost_usd": "0.00",
            "call_class": call_class,
        }


class _SemanticReviewRepairProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], str]] = []
        self.review_claim_cases: list[list[dict[str, Any]]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append((payload, call_class))
        if call_class in {"aq_semantic_closure", "aq_semantic_closure_repair"}:
            task = json.loads(payload["messages"][0]["content"])
            label_by_text = {
                str(item["id"]): str(item.get("text", "")).casefold()
                for item in task["evidence"]
            }
            router_label = next(
                label for label, text in label_by_text.items() if "router" in text
            )
            monitor_label = next(
                label for label, text in label_by_text.items() if "monitor" in text
            )
            if call_class == "aq_semantic_closure_repair":
                body = {
                    "schema_version": "m26-fas-synthesis/v1",
                    "status": "partial",
                    "answer_text": "The router keeps graph snapshots.",
                    "claims": [
                        {
                            "claim_id": "claim_1",
                            "claim_type": "EVIDENCE_FACT",
                            "surface_text": "The router keeps graph snapshots.",
                            "evidence_labels": [router_label],
                            "covers": ["router_snapshots"],
                        }
                    ],
                    "unanswered_dimensions": ["monitor_events"],
                    "abstention_reason": None,
                }
            else:
                body = {
                    "schema_version": "m26-fas-synthesis/v1",
                    "status": "answer",
                    "answer_text": (
                        "The router keeps graph snapshots. The monitor rejects events."
                    ),
                    "claims": [
                        {
                            "claim_id": "claim_1",
                            "claim_type": "EVIDENCE_FACT",
                            "surface_text": "The router keeps graph snapshots.",
                            "evidence_labels": [router_label],
                            "covers": ["router_snapshots"],
                        },
                        {
                            "claim_id": "claim_2",
                            "claim_type": "EVIDENCE_FACT",
                            "surface_text": "The monitor rejects events.",
                            "evidence_labels": [monitor_label],
                            "covers": ["monitor_events"],
                        },
                    ],
                    "unanswered_dimensions": [],
                    "abstention_reason": None,
                }
            return {
                "text": json.dumps(_segment_body_from_legacy(body)),
                "usage": {"input_tokens": 10, "output_tokens": 10},
                "cost_usd": "0.001",
                "call_class": call_class,
            }

        task = json.loads(payload["messages"][0]["content"])
        claim_cases = task["claim_cases"]
        self.review_claim_cases.append(claim_cases)
        judgments = []
        for case in claim_cases:
            claim_id = str(case["claim_id"])
            local_ids = [str(item["evidence_id"]) for item in case["evidence"]]
            surface = str(case["surface_text"]).casefold()
            if "rejects" in surface:
                judgments.append(
                    {
                        "claim_id": claim_id,
                        "verdict": "CONTRADICTED",
                        "evidence_ids": local_ids,
                    }
                )
            elif str(case["claim_type"]) == "MODEL_EXPLANATION":
                judgments.append(
                    {
                        "claim_id": claim_id,
                        "verdict": "GENERIC_EXPLANATION",
                        "evidence_ids": [],
                    }
                )
            else:
                judgments.append(
                    {
                        "claim_id": claim_id,
                        "verdict": "ENTAILED",
                        "evidence_ids": local_ids,
                    }
                )
        return {
            "text": json.dumps(
                {
                    "schema_version": "m26-claim-entailment-review/v1",
                    "claim_judgments": judgments,
                    "visible_coverage": {
                        "verdict": "COVERED",
                        "uncovered_assertions": [],
                    },
                }
            ),
            "usage": {"input_tokens": 10, "output_tokens": 10},
            "cost_usd": "0.001",
            "call_class": call_class,
        }


class _ScriptedSemanticClosureProvider:
    def __init__(
        self,
        synthesis_results: list[Any],
        review_result: Any | None = None,
    ) -> None:
        self.synthesis_results = list(synthesis_results)
        self.review_result = review_result
        self.calls: list[tuple[dict[str, Any], str]] = []
        self.review_claim_cases: list[list[dict[str, Any]]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append((payload, call_class))
        if call_class in {"aq_semantic_closure", "aq_semantic_closure_repair"}:
            task = json.loads(payload["messages"][0]["content"])
            if self.synthesis_results:
                result = self.synthesis_results.pop(0)
            else:
                result = {"status": "abstain", "answer_text": "", "claims": []}
            body = result(task) if callable(result) else result
            return {
                "text": json.dumps(_segment_body_from_legacy(body)),
                "usage": {"input_tokens": 10, "output_tokens": 10},
                "cost_usd": "0.001",
                "call_class": call_class,
            }

        task = json.loads(payload["messages"][0]["content"])
        claim_cases = task["claim_cases"]
        self.review_claim_cases.append(claim_cases)
        if self.review_result is not None:
            body = (
                self.review_result(task)
                if callable(self.review_result)
                else self.review_result
            )
            return {
                "text": json.dumps(body),
                "usage": {"input_tokens": 10, "output_tokens": 10},
                "cost_usd": "0.001",
                "call_class": call_class,
            }
        judgments = []
        for case in claim_cases:
            local_ids = [str(item["evidence_id"]) for item in case["evidence"]]
            if str(case["claim_type"]) == "MODEL_EXPLANATION":
                verdict = "GENERIC_EXPLANATION"
                evidence_ids: list[str] = []
            else:
                verdict = "ENTAILED"
                evidence_ids = local_ids
            judgments.append(
                {
                    "claim_id": str(case["claim_id"]),
                    "verdict": verdict,
                    "evidence_ids": evidence_ids,
                }
            )
        return {
            "text": json.dumps(
                {
                    "schema_version": "m26-claim-entailment-review/v1",
                    "claim_judgments": judgments,
                    "visible_coverage": {
                        "verdict": "COVERED",
                        "uncovered_assertions": [],
                    },
                }
            ),
            "usage": {"input_tokens": 10, "output_tokens": 10},
            "cost_usd": "0.001",
            "call_class": call_class,
        }


class _LiveGateFailureProvider:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls: list[tuple[dict[str, Any], str]] = []
        self.cost = 0

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append((payload, call_class))
        raise LiveGateError(self.message)


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


def test_provider_order_prefers_anchor_aware_role_evidence_over_scattered_overlap() -> None:
    question = "What kind of skill does a Product Manager need?"
    harness = _rich_passage(
        "ev_harness",
        (
            "The AI harness defines a Skill Library, Plugin Manager, and Tool Registry "
            "for products in an internal capability system."
        ),
        "capability-system",
    )
    pm_research = _rich_passage(
        "ev_pm_research",
        (
            "PMs need user research judgment. Analytics should help recover meaning, "
            "context, and decision logic."
        ),
        "role-research",
    )

    ordered = closure_runtime._provider_evidence_order(
        [harness, pm_research],
        [],
        question,
    )

    assert ordered[0]["evidence_id"] == "ev_pm_research"
    assert ordered[1]["evidence_id"] == "ev_harness"


def test_provider_snippet_projects_contiguous_anchor_window_with_answer_prose() -> None:
    question = "What kind of skill does a Product Manager need?"
    text = (
        "A PM should not read dashboards as isolated truth. Analytics should help "
        "notice anomalies and tradeoffs. Research should help you recover meaning, "
        "context, and decision logic. Feed the findings back into roadmap choices."
    )
    item = _rich_passage("ev_pm_user_research", text, "role-research")

    snippet = closure_runtime._provider_snippet(item, question, [])

    assert snippet in text
    assert "A PM should" in snippet
    assert "Research should help you recover meaning, context, and decision logic" in snippet
    assert len(snippet) <= closure_runtime.MAX_PROVIDER_SNIPPET_CHARS


def test_provider_projection_preserves_agent_architecture_and_user_research_controls() -> None:
    q2 = "What is a skill in an AI agent architecture?"
    q2_item = _rich_passage(
        "ev_agent_architecture",
        "In an agent architecture, a skill is task methodology above lower-level tools.",
        "agent-method",
    )
    q3 = "What is the role of user research in product management?"
    q3_item = _rich_passage(
        "ev_user_research",
        (
            "User research helps product management recover context behind metrics "
            "and turn customer evidence into better decisions."
        ),
        "research-method",
    )

    assert legacy._contextual_definition_query_parts(q2) is not None
    assert legacy._contextual_definition_query_parts(q3) is None
    assert closure_runtime._provider_evidence_order([q2_item], [], q2)[0] == q2_item
    assert "agent architecture" in closure_runtime._provider_snippet(q2_item, q2, [])
    assert closure_runtime._provider_evidence_order([q3_item], [], q3)[0] == q3_item
    assert "User research helps product management" in closure_runtime._provider_snippet(
        q3_item,
        q3,
        [],
    )


def test_compact_provider_prompt_allows_bounded_partial_without_inventing_taxonomy() -> None:
    payload, _label_map, _snippet_map = _compact_provider_payload(
        question="What operating skills matter for running a trustworthy system?",
        intent_class="direct_grounded_knowledge",
        evidence=[
            _rich_passage(
                "ev_ops",
                "Incident response practice supports reliable system operation.",
                "ops-note",
            )
        ],
        requirements=[],
        repair=False,
        previous_failures=[],
    )

    system = payload["system"]
    assert "bounded subset" in system
    assert "prefer status partial" in system
    assert "Abstain when no responsive material claim can be grounded" in system
    assert "Never invent missing categories" in system
    assert "Product Manager" not in system


def _graph_edge(
    evidence_id: str,
    source: str,
    target: str,
    relation_type: str,
) -> dict[str, Any]:
    text = f"{source} {relation_type} {target}."
    return {
        "evidence_id": evidence_id,
        "locator_id": f"loc_{evidence_id}",
        "evidence_type": "graph_edge",
        "source_id": "production-graph",
        "source_identity": "production-graph",
        "concept_id": source,
        "title": "production graph",
        "section_title": "graph edges",
        "passage_text": text,
        "release_id": "release-test",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "section_id": f"section_{evidence_id}",
        "channels": ["graph"],
        "passage_text_sha256": sha256_bytes(text.encode("utf-8")),
        "provenance_record_sha256": "b" * 64,
        "retrieved_at": "",
        "retrieval_metadata": {"query_overlap_score": 1.0},
        "edge_id": evidence_id,
        "edge_source": source,
        "edge_target": target,
        "relation_type": relation_type,
    }


def _minimal_answer_bundle(
    *,
    documents: list[dict[str, Any]],
) -> ProductionAnswerBundle:
    artifact_sha256 = {
        "graph": "1" * 64,
        "graph_v2": "2" * 64,
        "lexical_index": "3" * 64,
        "provenance": "4" * 64,
    }
    artifact_keys = {
        "graph": "graph.json",
        "graph_v2": "graph-v2.json",
        "lexical_index": "lexical-index.json",
        "provenance": "provenance.json",
    }
    return ProductionAnswerBundle(
        manifest={"release_id": "release-test"},
        graph={},
        graph_v2={"nodes": [], "edges": []},
        lexical_index={"documents": documents},
        provenance={"records": []},
        manifest_sha256="5" * 64,
        artifact_sha256=artifact_sha256,
        artifact_keys=artifact_keys,
        loaded_at="2026-08-13T00:00:00Z",
    )


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


def test_graph_edge_evidence_unit_includes_endpoint_display_labels() -> None:
    bundle = _minimal_answer_bundle(
        documents=[
            {
                "concept_id": "article_1",
                "title": "Harness Theory Part 1",
                "section_id": "article_1",
            },
            {
                "concept_id": "article_2",
                "title": "Harness Theory Part 2",
                "section_id": "article_2",
            },
        ]
    )

    item = legacy._graph_edge_evidence_item(
        bundle=bundle,
        edge={
            "edge_id": "edge_precedes",
            "source": "article_1",
            "target": "article_2",
            "relation_type": "precedes",
            "confidence": 0.9,
            "review_status": "approved",
        },
        trace_id="trace-graph-edge-labels",
        ordinal=1,
    )

    assert item["evidence_type"] == "graph_edge"
    assert item["edge_source_label"] == "Harness Theory Part 1"
    assert item["edge_target_label"] == "Harness Theory Part 2"
    assert (
        "Harness Theory Part 1 (article_1) precedes Harness Theory Part 2 (article_2)"
        in item["passage_text"]
    )
    assert "graph-artifact fact" not in item["passage_text"]
    assert "does not prove dependency" not in item["passage_text"]
    assert item["relation_metadata"] == {
        "schema_version": "m26-graph-relation-metadata/v1",
        "relation_type": "precedes",
        "provenance": "graph_artifact_fact",
        "directed": True,
        "structural_relation": True,
        "relation_family": "ordering",
        "retrieval_semantics": ["ordering", "sequence", "navigation"],
        "non_asserted_semantics": [
            "dependency",
            "causality",
            "implementation",
            "requirement",
        ],
    }
    graph_rule = legacy._minimum_evidence_rule("graph_relationship")
    assert graph_rule["minimum_evidence"] == 1
    assert graph_rule["requires_graph_edge"] is True
    assert graph_rule["requires_complete_graph_edge_fact"] is True
    assert "requires_both_endpoint_evidence" not in graph_rule


def test_compound_graph_edge_unit_covers_endpoint_facets_without_passages() -> None:
    bundle = _minimal_answer_bundle(
        documents=[
            {
                "concept_id": "article_1",
                "title": "Harness Theory Part 1",
                "section_id": "article_1",
            },
            {
                "concept_id": "article_2",
                "title": "Harness Theory Part 2",
                "section_id": "article_2",
            },
        ]
    )
    edge = legacy._graph_edge_evidence_item(
        bundle=bundle,
        edge={
            "edge_id": "edge_precedes",
            "source": "article_1",
            "target": "article_2",
            "relation_type": "precedes",
            "confidence": 1.0,
            "review_status": "approved",
        },
        trace_id="trace-compound-edge-facets",
        ordinal=1,
    )
    question = (
        "The production graph says Harness Theory Part 1 precedes Part 2. "
        "What can we safely infer from that edge, and what can't we infer?"
    )
    surface = (
        "The relation graph records Harness Theory Part 1 as preceding Harness "
        "Theory Part 2, so the safe inference is ordering or sequence/navigation "
        "only. That precedes edge does not by itself prove dependency, causality, "
        "implementation, or requirement."
    )
    candidate = {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": "precedes",
        "selected_evidence_ids": [edge["evidence_id"]],
        "answer_text": f"{surface} [[claim_1]].",
        "claims": [
            {
                "claim_id": "claim_1",
                "claim_role": "direct",
                "surface_text": surface,
                "facet_ids": legacy._required_facet_ids(
                    question=question,
                    intent_class="graph_relationship",
                ),
                "support_mode": "graph_edge_compound_fact",
                "support_refs": [
                    {
                        "evidence_id": edge["evidence_id"],
                        "locator_id": edge["locator_id"],
                        "exact_quote": edge["passage_text"],
                        "uncertainty": "low",
                    }
                ],
            }
        ],
        "missing_facets": [],
        "abstention_reason": None,
    }

    verified = legacy._verify_multi_evidence_provider_output(
        trace_id="trace-compound-edge-facets",
        question=question,
        intent_class="graph_relationship",
        evidence=[edge],
        provider_text=json.dumps(candidate),
    )

    assert set(verified["covered_facets"]) >= {
        "graph_edge",
        "source_endpoint",
        "target_endpoint",
        "relation_semantics",
    }
    assert verified["material_claims"][0]["support_verdict"] == (
        "supported_exact_multi_evidence_bundle"
    )


def test_semantic_review_graph_fact_uses_formal_relation_metadata() -> None:
    edge = _graph_edge("ev_edge", "Harness Theory Part 1", "Harness Theory Part 2", "precedes")
    edge["relation_metadata"] = legacy._graph_relation_metadata("precedes")
    surface = (
        "Harness Theory Part 1 precedes Harness Theory Part 2 in graph order, "
        "and the graph edge does not by itself prove dependency."
    )
    candidate = {
        "claims": [
            {
                "claim_id": "claim_1",
                "surface_text": surface,
                "support_refs": [
                    {
                        "evidence_id": "ev_edge",
                        "locator_id": "loc_ev_edge",
                        "exact_quote": edge["passage_text"],
                    }
                ],
            }
        ]
    }

    payload = _semantic_review_payload(
        question="Does a precedes edge prove dependency?",
        intent_class="graph_relationship",
        candidate=candidate,
        evidence=[edge],
    )
    claim_case = json.loads(payload["messages"][0]["content"])["claim_cases"][0]
    graph_fact = claim_case["evidence"][0]["graph_fact"]

    assert graph_fact["provenance"] == "graph_artifact_fact"
    assert graph_fact["relation_metadata"]["relation_type"] == "precedes"
    assert graph_fact["relation_metadata"]["retrieval_semantics"] == [
        "ordering",
        "sequence",
        "navigation",
    ]
    assert graph_fact["relation_metadata"]["non_asserted_semantics"] == [
        "dependency",
        "causality",
        "implementation",
        "requirement",
    ]
    assert "semantic_boundary" not in graph_fact


def test_precedes_boundary_recovery_has_no_canonical_publication_authority() -> None:
    edge = _graph_edge("ev_edge", "Harness Theory Part 1", "Harness Theory Part 2", "precedes")
    edge["relation_metadata"] = legacy._graph_relation_metadata("precedes")
    question = (
        "The production graph says Harness Theory Part 1 precedes Part 2. "
        "What can we safely infer from that edge, and what can't we infer?"
    )
    requirements = _semantic_requirements(question, "graph_relationship")

    candidate = _supported_semantic_recovery_candidate(
        question=question,
        intent_class="graph_relationship",
        evidence=[edge],
        requirements=requirements,
        endpoint_proof={
            "required": True,
            "matched": True,
            "edge_id": "ev_edge",
            "edge_source": "Harness Theory Part 1",
            "edge_target": "Harness Theory Part 2",
            "relation_type": "precedes",
        },
    )

    assert candidate is None


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
        json.dumps(
            {
                "schema_version": SEGMENT_SCHEMA_VERSION,
                "status": "answer",
                "segments": [
                    {
                        "segment_id": "s1",
                        "semantic_role": "material_claim",
                        "claim_id": "claim_1",
                        "claim_type": "EVIDENCE_FACT",
                        "text": "A short grounded answer.",
                        "evidence_labels": ["e1"],
                        "covers": [],
                    }
                ],
                "unanswered_dimensions": [],
                "abstention_reason": None,
            }
        )
    )
    assert parsed["status"] == "answer"
    assert parsed["segments"][0]["text"] == "A short grounded answer."


def test_legacy_claim_surface_contract_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown keys"):
        _parse_compact_provider_result(
            json.dumps(
                {
                    "schema_version": "m26-fas-synthesis/v1",
                    "status": "answer",
                    "answer_text": "A short grounded answer.",
                    "claims": [
                        {
                            "claim_id": "claim_1",
                            "claim_type": "EVIDENCE_FACT",
                            "surface_text": "A short grounded answer.",
                            "evidence_labels": ["e1"],
                            "covers": [],
                        }
                    ],
                }
            )
        )


def test_segment_contract_rejects_inline_claim_anchors() -> None:
    with pytest.raises(ValueError, match="inline claim anchor"):
        _parse_compact_provider_result(
            json.dumps(
                {
                    "schema_version": SEGMENT_SCHEMA_VERSION,
                    "status": "answer",
                    "segments": [
                        {
                            "segment_id": "s1",
                            "semantic_role": "material_claim",
                            "claim_id": "claim_1",
                            "claim_type": "EVIDENCE_FACT",
                            "text": "The router keeps snapshots [[claim_1]].",
                            "evidence_labels": ["e1"],
                            "covers": [],
                        }
                    ],
                    "unanswered_dimensions": [],
                    "abstention_reason": None,
                }
            )
        )


def test_segment_contract_rejects_duplicate_visible_prose() -> None:
    with pytest.raises(ValueError, match="text duplicated"):
        _parse_compact_provider_result(
            json.dumps(
                {
                    "schema_version": SEGMENT_SCHEMA_VERSION,
                    "status": "answer",
                    "segments": [
                        {
                            "segment_id": "s1",
                            "semantic_role": "material_claim",
                            "claim_id": "claim_1",
                            "claim_type": "EVIDENCE_FACT",
                            "text": "The router keeps snapshots.",
                            "evidence_labels": ["e1"],
                            "covers": [],
                        },
                        {
                            "segment_id": "s2",
                            "semantic_role": "material_claim",
                            "claim_id": "claim_2",
                            "claim_type": "EVIDENCE_FACT",
                            "text": "The router keeps snapshots.",
                            "evidence_labels": ["e1"],
                            "covers": [],
                        },
                    ],
                    "unanswered_dimensions": [],
                    "abstention_reason": None,
                }
            )
        )


def test_compact_provider_contract_rejects_extra_keys() -> None:
    try:
        _parse_compact_provider_result(
            json.dumps(
                {
                    "schema_version": SEGMENT_SCHEMA_VERSION,
                    "status": "answer",
                    "segments": [],
                    "extra": "bad",
                }
            )
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


def test_candidate2_legacy_helpers_have_no_canonical_publication_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("legacy semantic helper regained publication authority")

    for helper_name in (
        "_visible_semantic_failures",
        "_hard_visible_semantic_failures",
        "_requirement_support_failures",
        "_infer_used_items",
        "_force_required_support_items",
        "_partial_answer_has_substantial_value",
    ):
        monkeypatch.setattr(closure_runtime, helper_name, fail_if_called)

    evidence = [
        _rich_passage(
            "router",
            "The router stores graph snapshots for controlled execution.",
            "router-note",
        )
    ]

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        router_label = next(
            str(item["id"]) for item in task["evidence"] if "router" in item["text"]
        )
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": "The router keeps graph snapshots.",
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The router keeps graph snapshots.",
                    "evidence_labels": [router_label],
                    "covers": ["router_snapshots"],
                }
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    provider = _ScriptedSemanticClosureProvider([synthesis])
    answer, closure = _synthesize_and_verify(
        question="Explain router graph snapshots.",
        trace_id="trace-candidate2-no-legacy-helper-authority",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[
            SemanticRequirement(
                requirement_id="router_snapshots",
                instruction="Explain router graph snapshots.",
                evidence_terms=("router", "graph", "snapshots"),
                visible_patterns=(r"\brouter.{0,80}snapshots",),
            )
        ],
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        "aq_claim_semantic_entailment",
    ]
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert closure["failures"] == []


def test_candidate2r1_module_name_cannot_change_semantics() -> None:
    evidence = [
        _rich_passage(
            "router",
            "The router stores graph snapshots for controlled execution.",
            "router-note",
        )
    ]

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        router_label = next(
            str(item["id"]) for item in task["evidence"] if "router" in item["text"]
        )
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": "The router keeps graph snapshots.",
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The router keeps graph snapshots.",
                    "evidence_labels": [router_label],
                    "covers": ["router_snapshots"],
                }
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    test_module_provider = type(
        "TestModuleProvider",
        (_ScriptedSemanticClosureProvider,),
        {"__module__": "tests.fake_provider"},
    )
    provider = test_module_provider([synthesis])

    answer, closure = _synthesize_and_verify(
        question="Explain router graph snapshots.",
        trace_id="trace-candidate2r1-module-name-no-bypass",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        "aq_claim_semantic_entailment",
    ]
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert closure["failures"] == []


def test_candidate2r1_wrong_review_schema_test_module_fails_closed() -> None:
    evidence = [
        _rich_passage(
            "router",
            "The router stores graph snapshots for controlled execution.",
            "router-note",
        )
    ]

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        router_label = next(
            str(item["id"]) for item in task["evidence"] if "router" in item["text"]
        )
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": "The router keeps graph snapshots.",
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The router keeps graph snapshots.",
                    "evidence_labels": [router_label],
                    "covers": ["router_snapshots"],
                }
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    test_module_provider = type(
        "WrongReviewSchemaProvider",
        (_ScriptedSemanticClosureProvider,),
        {"__module__": "tests.fake_provider"},
    )
    provider = test_module_provider(
        [synthesis, synthesis],
        review_result={
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": "old synthesis schema is not a review",
            "claims": [],
        },
    )

    answer, closure = _synthesize_and_verify(
        question="Explain router graph snapshots.",
        trace_id="trace-candidate2r1-wrong-review-schema",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        "aq_claim_semantic_entailment",
        "aq_semantic_closure_repair",
        "aq_claim_semantic_entailment",
    ]
    assert answer["answer_source"] == "safe_abstention"
    assert "ValueError" in closure["failures"]
    assert "SEMANTIC_CLOSURE_FAILED" in closure["failures"]


def test_candidate2r1_support_refs_do_not_imply_entailment() -> None:
    evidence = [
        _rich_passage(
            "router",
            "The router stores graph snapshots.",
            "router-note",
        )
    ]

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        router_label = next(
            str(item["id"]) for item in task["evidence"] if "router" in item["text"]
        )
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": "The router deletes graph snapshots.",
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The router deletes graph snapshots.",
                    "evidence_labels": [router_label],
                    "covers": ["router_snapshots"],
                }
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    def contradicted_review(task: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "m26-claim-entailment-review/v1",
            "claim_judgments": [
                {
                    "claim_id": str(case["claim_id"]),
                    "verdict": "CONTRADICTED",
                    "evidence_ids": [
                        str(item["evidence_id"]) for item in case["evidence"]
                    ],
                }
                for case in task["claim_cases"]
            ],
            "visible_coverage": {
                "verdict": "COVERED",
                "uncovered_assertions": [],
            },
        }

    provider = _ScriptedSemanticClosureProvider(
        [synthesis, synthesis],
        review_result=contradicted_review,
    )

    answer, closure = _synthesize_and_verify(
        question="Explain router graph snapshots.",
        trace_id="trace-candidate2r1-support-ref-not-entailment",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert answer["answer_source"] == "safe_abstention"
    assert "SEMANTIC_REVIEW_BLOCKED:claim_1:CONTRADICTED" in closure["failures"]
    assert provider.review_claim_cases


def test_candidate2r1_second_attempt_requires_real_reviewer() -> None:
    evidence = [
        _rich_passage(
            "router",
            "The router stores graph snapshots.",
            "router-note",
        )
    ]

    def valid_synthesis(task: dict[str, Any]) -> dict[str, Any]:
        router_label = next(
            str(item["id"]) for item in task["evidence"] if "router" in item["text"]
        )
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": "The router keeps graph snapshots.",
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The router keeps graph snapshots.",
                    "evidence_labels": [router_label],
                    "covers": ["router_snapshots"],
                }
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    class ParseFailThenValidProvider(_ScriptedSemanticClosureProvider):
        def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
            if call_class == "aq_semantic_closure":
                self.calls.append((payload, call_class))
                return {
                    "text": "{not valid json",
                    "usage": {"input_tokens": 10, "output_tokens": 10},
                    "cost_usd": "0.001",
                    "call_class": call_class,
                }
            return super().call(payload, call_class)

    provider = ParseFailThenValidProvider([valid_synthesis])

    answer, closure = _synthesize_and_verify(
        question="Explain router graph snapshots.",
        trace_id="trace-candidate2r1-second-attempt-review",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        "aq_semantic_closure_repair",
        "aq_claim_semantic_entailment",
    ]
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert answer["repair_attempted"] is True
    assert closure["failures"] == []


def test_candidate2_unseen_precedes_paraphrase_reaches_semantic_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("legacy visible parser vetoed paraphrase before review")

    for helper_name in (
        "_visible_semantic_failures",
        "_hard_visible_semantic_failures",
        "_requirement_support_failures",
        "_partial_answer_has_substantial_value",
    ):
        monkeypatch.setattr(closure_runtime, helper_name, fail_if_called)

    question = (
        "Does the precedes edge between Harness Theory Part 1 and Harness Theory Part 2 "
        "prove that Part 1 depends on Part 2?"
    )
    edge = _graph_edge(
        "edge_precedes",
        "Harness Theory Part 1",
        "Harness Theory Part 2",
        "precedes",
    )
    source = _rich_passage(
        "part_1",
        "Harness Theory Part 1 is the first endpoint in the relation graph.",
        "part-1-note",
    )
    source["concept_id"] = "Harness Theory Part 1"
    target = _rich_passage(
        "part_2",
        "Harness Theory Part 2 is the second endpoint in the relation graph.",
        "part-2-note",
    )
    target["concept_id"] = "Harness Theory Part 2"

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        edge_label = next(
            str(item["id"])
            for item in task["evidence"]
            if item["type"] == "graph_edge"
        )
        graph_labels = [edge_label]
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": (
                "Harness Theory Part 1 precedes Harness Theory Part 2, and the "
                "precedes edge does not prove dependency."
            ),
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": (
                        "Harness Theory Part 1 precedes Harness Theory Part 2, and "
                        "the precedes edge does not prove dependency."
                    ),
                    "evidence_labels": graph_labels,
                    "covers": [
                        "entity_harness_theory_part_1",
                        "entity_harness_theory_part_2",
                        "ordering_semantics",
                        "non_entailment",
                    ],
                },
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    provider = _ScriptedSemanticClosureProvider([synthesis])
    answer, closure = _synthesize_and_verify(
        question=question,
        trace_id="trace-candidate2-precedes-paraphrase",
        intent_class="graph_relationship",
        evidence=[edge, source, target],
        provider_client=provider,
        requirements=_semantic_requirements(question, "graph_relationship"),
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        "aq_claim_semantic_entailment",
    ]
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert closure["semantic_review"]["visible_coverage"]["verdict"] == "COVERED"
    assert {
        str(item["evidence_id"])
        for case in provider.review_claim_cases[0]
        for item in case["evidence"]
    } == {"edge_precedes"}


def test_candidate2_missing_claims_fail_closed_without_review() -> None:
    evidence = [
        _rich_passage(
            "router",
            "The router stores graph snapshots for controlled execution.",
            "router-note",
        )
    ]
    provider = _ScriptedSemanticClosureProvider(
        [
            {
                "schema_version": "m26-fas-synthesis/v1",
                "status": "answer",
                "answer_text": "The router stores graph snapshots.",
                "used": ["e1"],
                "unanswered_dimensions": [],
                "abstention_reason": None,
            },
            {
                "schema_version": "m26-fas-synthesis/v1",
                "status": "answer",
                "answer_text": "The router stores graph snapshots.",
                "used": ["e1"],
                "unanswered_dimensions": [],
                "abstention_reason": None,
            },
        ]
    )

    answer, closure = _synthesize_and_verify(
        question="Explain router graph snapshots.",
        trace_id="trace-candidate2-missing-claims",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        "aq_semantic_closure_repair",
    ]
    assert provider.review_claim_cases == []
    assert answer["answer_source"] == "safe_abstention"
    assert answer["unsupported_accepted_claims"] == 0
    assert "SEMANTIC_CLOSURE_FAILED" in closure["failures"]


def test_candidate2_top_level_used_cannot_rescue_missing_claim_binding() -> None:
    evidence = [
        _rich_passage(
            "router",
            "The router stores graph snapshots for controlled execution.",
            "router-note",
        )
    ]
    provider = _ScriptedSemanticClosureProvider(
        [
            {
                "schema_version": "m26-fas-synthesis/v1",
                "status": "answer",
                "answer_text": "The router stores graph snapshots.",
                "used": ["e1"],
                "claims": [
                    {
                        "claim_id": "claim_1",
                        "claim_type": "EVIDENCE_FACT",
                        "surface_text": "The router stores graph snapshots.",
                        "evidence_labels": [],
                        "covers": ["router_snapshots"],
                    }
                ],
                "unanswered_dimensions": [],
                "abstention_reason": None,
            },
            {
                "schema_version": "m26-fas-synthesis/v1",
                "status": "answer",
                "answer_text": "The router stores graph snapshots.",
                "used": ["e1"],
                "claims": [
                    {
                        "claim_id": "claim_1",
                        "claim_type": "EVIDENCE_FACT",
                        "surface_text": "The router stores graph snapshots.",
                        "covers": ["router_snapshots"],
                    }
                ],
                "unanswered_dimensions": [],
                "abstention_reason": None,
            },
        ]
    )

    answer, _closure = _synthesize_and_verify(
        question="Explain router graph snapshots.",
        trace_id="trace-candidate2-missing-local-labels",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        "aq_semantic_closure_repair",
    ]
    assert provider.review_claim_cases == []
    assert answer["answer_source"] == "safe_abstention"


def test_candidate2_unknown_claim_label_fails_closed_without_review() -> None:
    evidence = [
        _rich_passage(
            "router",
            "The router stores graph snapshots for controlled execution.",
            "router-note",
        )
    ]
    bad_claim = {
        "schema_version": "m26-fas-synthesis/v1",
        "status": "answer",
        "answer_text": "The router stores graph snapshots.",
        "claims": [
            {
                "claim_id": "claim_1",
                "claim_type": "EVIDENCE_FACT",
                "surface_text": "The router stores graph snapshots.",
                "evidence_labels": ["e999"],
                "covers": ["router_snapshots"],
            }
        ],
        "unanswered_dimensions": [],
        "abstention_reason": None,
    }
    provider = _ScriptedSemanticClosureProvider([bad_claim, bad_claim])

    answer, _closure = _synthesize_and_verify(
        question="Explain router graph snapshots.",
        trace_id="trace-candidate2-unknown-label",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        "aq_semantic_closure_repair",
    ]
    assert provider.review_claim_cases == []
    assert answer["answer_source"] == "safe_abstention"


def test_candidate2_claim_local_review_isolation() -> None:
    evidence = [
        _rich_passage("router", "The router stores graph snapshots.", "router-note"),
        _rich_passage("monitor", "The monitor accepts events.", "monitor-note"),
    ]

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        labels = {
            str(item["id"]): str(item["text"]).casefold()
            for item in task["evidence"]
        }
        router_label = next(label for label, text in labels.items() if "router" in text)
        monitor_label = next(label for label, text in labels.items() if "monitor" in text)
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": (
                "The router stores graph snapshots. The monitor accepts events."
            ),
            "claims": [
                {
                    "claim_id": "claim_router",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The router stores graph snapshots.",
                    "evidence_labels": [router_label],
                    "covers": ["router_snapshots"],
                },
                {
                    "claim_id": "claim_monitor",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The monitor accepts events.",
                    "evidence_labels": [monitor_label],
                    "covers": ["monitor_events"],
                },
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    provider = _ScriptedSemanticClosureProvider([synthesis])
    answer, _closure = _synthesize_and_verify(
        question="Explain router snapshots and monitor events.",
        trace_id="trace-candidate2-claim-local-isolation",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert {
        str(case["claim_id"]): {str(item["evidence_id"]) for item in case["evidence"]}
        for case in provider.review_claim_cases[0]
    } == {
        "claim_router": {"router"},
        "claim_monitor": {"monitor"},
    }


def test_candidate2r1_static_no_test_awareness_guard() -> None:
    source = inspect.getsource(closure_runtime)
    forbidden = [
        "_local_test_double_without_review",
        "_legacy_compact_review_adapter",
        "_local_claim_semantic_review",
        "_candidate_selects_all_evidence",
        "type(provider_client).__module__",
    ]
    for needle in forbidden:
        assert needle not in source


def test_provider_abstain_with_available_evidence_safely_abstains_without_quote_collage() -> None:
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
    assert answer["status"] == "owner_only_safe_abstention"
    assert answer["answer_source"] == "safe_abstention"
    assert answer["safe_abstention"] is True
    verification = answer["multi_evidence_verification"]
    assert verification["provider_contract"] == "compact_runtime_bound_semantic_closure/v1"
    assert closure["broad_deterministic_fallback_used"] is False
    assert "PROVIDER_ABSTAINED_WITH_AVAILABLE_EVIDENCE" in closure["failures"]
    assert "SEMANTIC_CLOSURE_FAILED" in closure["failures"]


def test_semantic_review_one_repair_preserves_supported_partial() -> None:
    question = "Explain router snapshots and monitor events."
    evidence = [
        _rich_passage(
            "ev_router",
            "The router stores graph snapshots.",
            "router-note",
        ),
        _rich_passage(
            "ev_monitor",
            "The monitor accepts events.",
            "monitor-note",
        ),
    ]
    requirements = [
        SemanticRequirement(
            requirement_id="router_snapshots",
            instruction="Explain router graph snapshots.",
            evidence_terms=("router", "graph", "snapshots"),
            visible_patterns=(r"\brouter.{0,80}(?:stores|keeps).{0,80}snapshots",),
        ),
        SemanticRequirement(
            requirement_id="monitor_events",
            instruction="Explain monitor events.",
            evidence_terms=("monitor", "events"),
            visible_patterns=(r"\bmonitor.{0,80}(?:accepts|rejects).{0,80}events",),
        ),
    ]
    provider = _SemanticReviewRepairProvider()

    answer, closure = _synthesize_and_verify(
        question=question,
        trace_id="trace-semantic-review-repair",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=requirements,
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        "aq_claim_semantic_entailment",
        "aq_semantic_closure_repair",
        "aq_claim_semantic_entailment",
    ]
    assert answer["answer_source"] == "provider_verified_runtime_bound_partial_semantic_closure"
    assert answer["repair_attempted"] is True
    assert "router keeps graph snapshots" in answer["answer_text"].casefold()
    assert "unsupported boundary" not in answer["answer_text"].casefold()
    assert closure["partial_answer"] is True
    first_review_cases = {
        str(case["claim_id"]): {
            str(item["evidence_id"]) for item in case["evidence"]
        }
        for case in provider.review_claim_cases[0]
    }
    assert first_review_cases == {
        "claim_1": {"ev_router"},
        "claim_2": {"ev_monitor"},
    }


def test_semantic_review_final_rejection_publishes_entailed_claims_as_partial() -> None:
    question = "Explain router snapshots and monitor events."
    evidence = [
        _rich_passage(
            "ev_router",
            "The router stores graph snapshots.",
            "router-note",
        ),
        _rich_passage(
            "ev_monitor",
            "The monitor accepts events.",
            "monitor-note",
        ),
    ]

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        labels = {
            "router": next(
                str(item["id"]) for item in task["evidence"] if "router" in item["text"]
            ),
            "monitor": next(
                str(item["id"]) for item in task["evidence"] if "monitor" in item["text"]
            ),
        }
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": "The router keeps graph snapshots. The monitor rejects events.",
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The router keeps graph snapshots.",
                    "evidence_labels": [labels["router"]],
                    "covers": ["router_snapshots"],
                },
                {
                    "claim_id": "claim_2",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The monitor rejects events.",
                    "evidence_labels": [labels["monitor"]],
                    "covers": ["monitor_events"],
                },
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    def review(task: dict[str, Any]) -> dict[str, Any]:
        judgments = []
        for case in task["claim_cases"]:
            local_ids = [str(item["evidence_id"]) for item in case["evidence"]]
            if str(case["claim_id"]) == "claim_1":
                judgments.append(
                    {
                        "claim_id": "claim_1",
                        "verdict": "ENTAILED",
                        "evidence_ids": local_ids,
                    }
                )
            else:
                judgments.append(
                    {
                        "claim_id": "claim_2",
                        "verdict": "INSUFFICIENT",
                        "evidence_ids": local_ids,
                    }
                )
        return {
            "schema_version": "m26-claim-entailment-review/v1",
            "claim_judgments": judgments,
            "visible_coverage": {
                "verdict": "UNCOVERED",
                "uncovered_assertions": ["The monitor rejects events."],
            },
        }

    provider = _ScriptedSemanticClosureProvider(
        [synthesis, synthesis],
        review_result=review,
    )

    answer, closure = _synthesize_and_verify(
        question=question,
        trace_id="trace-semantic-review-supported-partial",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        "aq_claim_semantic_entailment",
        "aq_semantic_closure_repair",
        "aq_claim_semantic_entailment",
    ]
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_source"] == "provider_verified_runtime_bound_partial_semantic_closure"
    assert answer["unsupported_accepted_claims"] == 0
    assert "router keeps graph snapshots" in answer["answer_text"].casefold()
    assert "monitor rejects events" not in answer["answer_text"].casefold()
    assert answer["multi_evidence_verification"]["dropped_claim_ids"] == ["claim_2"]
    assert closure["partial_answer"] is True
    assert closure["failures"] == []


def test_semantic_review_429_falls_back_to_cloudflare_in_real_synthesize_flow() -> None:
    question = "Explain router snapshots and monitor events."
    evidence = [
        _rich_passage(
            "ev_router",
            "The router stores graph snapshots.",
            "router-note",
        ),
        _rich_passage(
            "ev_monitor",
            "The monitor accepts events.",
            "monitor-note",
        ),
    ]
    requirements = [
        SemanticRequirement(
            requirement_id="router_snapshots",
            instruction="Explain router graph snapshots.",
            evidence_terms=("router", "graph", "snapshots"),
            visible_patterns=(r"\brouter.{0,80}(?:stores|keeps).{0,80}snapshots",),
        ),
        SemanticRequirement(
            requirement_id="monitor_events",
            instruction="Explain monitor events.",
            evidence_terms=("monitor", "events"),
            visible_patterns=(r"\bmonitor.{0,80}(?:accepts|rejects).{0,80}events",),
        ),
    ]

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        labels = {
            "router": next(
                str(item["id"]) for item in task["evidence"] if "router" in item["text"]
            ),
            "monitor": next(
                str(item["id"]) for item in task["evidence"] if "monitor" in item["text"]
            ),
        }
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": "The router keeps graph snapshots. The monitor accepts events.",
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The router keeps graph snapshots.",
                    "evidence_labels": [labels["router"]],
                    "covers": ["router_snapshots"],
                },
                {
                    "claim_id": "claim_2",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The monitor accepts events.",
                    "evidence_labels": [labels["monitor"]],
                    "covers": ["monitor_events"],
                },
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    def review(task: dict[str, Any]) -> dict[str, Any]:
        judgments = []
        for case in task["claim_cases"]:
            judgments.append(
                {
                    "claim_id": str(case["claim_id"]),
                    "verdict": "ENTAILED",
                    "evidence_ids": [str(item["evidence_id"]) for item in case["evidence"]],
                }
            )
        return {
            "schema_version": "m26-claim-entailment-review/v1",
            "claim_judgments": judgments,
            "visible_coverage": {
                "verdict": "COVERED",
                "uncovered_assertions": [],
            },
        }

    cloudflare = _ScriptedSemanticClosureProvider([synthesis], review_result=review)
    reviewer = _LiveGateFailureProvider("provider HTTP 429")
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=_AbstainingProvider(),  # type: ignore[arg-type]
        reviewer=reviewer,  # type: ignore[arg-type]
        state=CloudflareRouterState(),
    )

    answer, closure = _synthesize_and_verify(
        question=question,
        trace_id="trace-semantic-review-failover",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=router,
        requirements=requirements,
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in cloudflare.calls] == [
        "aq_semantic_closure",
        SEMANTIC_REVIEW_CALL_CLASS,
    ]
    assert [call_class for _, call_class in reviewer.calls] == [
        SEMANTIC_REVIEW_CALL_CLASS,
    ]
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert "router keeps graph snapshots" in answer["answer_text"].casefold()
    assert "monitor accepts events" in answer["answer_text"].casefold()
    assert closure["failures"] == []
    telemetry = router.telemetry()
    assert telemetry["semantic_reviewer_primary"] == MINIMAX_PROVIDER
    assert telemetry["semantic_reviewer_fallback_used"] is True
    assert telemetry["semantic_reviewer_fallback_reason"] == MINIMAX_REVIEWER_RATE_LIMIT_429
    assert telemetry["semantic_reviewer_final"] == CLOUDFLARE_PROVIDER
    assert telemetry["reviewer_provider_diversity"] is False
    assert telemetry["fallback_used"] is False
    assert telemetry["closure_provider_final"] == CLOUDFLARE_PROVIDER


def test_semantic_review_invalid_cloudflare_fallback_fails_closed_without_second_fallback() -> None:
    question = "Explain router snapshots and monitor events."
    evidence = [
        _rich_passage(
            "ev_router",
            "The router stores graph snapshots.",
            "router-note",
        ),
        _rich_passage(
            "ev_monitor",
            "The monitor accepts events.",
            "monitor-note",
        ),
    ]
    requirements = [
        SemanticRequirement(
            requirement_id="router_snapshots",
            instruction="Explain router graph snapshots.",
            evidence_terms=("router", "graph", "snapshots"),
            visible_patterns=(r"\brouter.{0,80}(?:stores|keeps).{0,80}snapshots",),
        ),
        SemanticRequirement(
            requirement_id="monitor_events",
            instruction="Explain monitor events.",
            evidence_terms=("monitor", "events"),
            visible_patterns=(r"\bmonitor.{0,80}(?:accepts|rejects).{0,80}events",),
        ),
    ]

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        labels = {
            "router": next(
                str(item["id"]) for item in task["evidence"] if "router" in item["text"]
            ),
            "monitor": next(
                str(item["id"]) for item in task["evidence"] if "monitor" in item["text"]
            ),
        }
        body = {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": "The router keeps graph snapshots. The monitor accepts events.",
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The router keeps graph snapshots.",
                    "evidence_labels": [labels["router"]],
                    "covers": ["router_snapshots"],
                },
                {
                    "claim_id": "claim_2",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The monitor accepts events.",
                    "evidence_labels": [labels["monitor"]],
                    "covers": ["monitor_events"],
                },
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }
        return body

    def abstain(task: dict[str, Any]) -> dict[str, Any]:
        del task
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "abstain",
            "answer_text": "",
            "claims": [],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    cloudflare = _ScriptedSemanticClosureProvider(
        [synthesis, abstain],
        review_result={
            "schema_version": "m26-claim-entailment-review/v1",
            "claim_judgments": [
                {
                    "claim_id": "claim_1",
                    "verdict": "INSUFFICIENT",
                    "evidence_ids": [],
                }
            ],
            "visible_coverage": {
                "verdict": "UNCOVERED",
                "uncovered_assertions": ["monitor events"],
            },
        },
    )
    reviewer = _LiveGateFailureProvider("provider HTTP 429")
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=_AbstainingProvider(),  # type: ignore[arg-type]
        reviewer=reviewer,  # type: ignore[arg-type]
        state=CloudflareRouterState(),
    )

    answer, closure = _synthesize_and_verify(
        question=question,
        trace_id="trace-semantic-review-invalid-failover",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=router,
        requirements=requirements,
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in reviewer.calls] == [
        SEMANTIC_REVIEW_CALL_CLASS,
    ]
    assert [call_class for _, call_class in cloudflare.calls] == [
        "aq_semantic_closure",
        SEMANTIC_REVIEW_CALL_CLASS,
        "aq_semantic_closure_repair",
    ]
    assert answer["status"] == "owner_only_safe_abstention"
    assert answer["answer_source"] == "safe_abstention"
    assert answer["safe_abstention"] is True
    assert closure["broad_deterministic_fallback_used"] is False
    telemetry = router.telemetry()
    assert telemetry["semantic_reviewer_primary"] == MINIMAX_PROVIDER
    assert telemetry["semantic_reviewer_fallback_used"] is True
    assert telemetry["semantic_reviewer_fallback_reason"] == MINIMAX_REVIEWER_RATE_LIMIT_429
    assert telemetry["semantic_reviewer_final"] == CLOUDFLARE_PROVIDER
    assert telemetry["semantic_reviewer_fallback_blocked_reason"] == ""


def test_contextual_definition_query_derives_head_and_context_requirements() -> None:
    question = "What is a skill in an AI agent architecture?"

    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    ids = [item.requirement_id for item in requirements]

    assert {"definition_head", "context_modifier"}.issubset(ids)
    assert ids[0] == "definition_head"
    assert ids[1] == "context_modifier"


def test_contextual_definition_query_prioritizes_head_definition_in_compact_projection() -> None:
    question = "What is a skill in an AI agent architecture?"
    requirements = derive_semantic_requirements(question, "direct_grounded_knowledge")
    evidence = [
        _passage(
            "context",
            "An AI agent architecture keeps the skill layer separate from routing.",
            "context-note",
        ),
        _passage(
            "skill",
            (
                "Skill | What method should the agent follow for this class of task? "
                "SOP, tool order, decision rules, acceptance criteria."
            ),
            "skill-note",
        ),
    ]
    payload, label_map, snippet_map = _compact_provider_payload(
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=requirements,
        repair=False,
        previous_failures=[],
    )
    task = json.loads(payload["messages"][0]["content"])
    first_item = task["evidence"][0]

    assert "skill" in first_item["text"].casefold()
    assert "method" in first_item["text"].casefold()
    assert label_map[first_item["id"]]["passage_text"].casefold().startswith("skill")
    assert snippet_map[label_map[first_item["id"]]["evidence_id"]]


def test_contextual_definition_query_rejects_unbacked_category_mutation_even_with_review() -> None:
    question = "What is a skill in an AI agent architecture?"
    evidence = [
        _passage(
            "ev_skill",
            (
                "Skill | What method should the agent follow for this class of task? "
                "SOP, tool order, decision rules, acceptance criteria."
            ),
            "skill-note",
        ),
        _passage(
            "ev_context",
            "An AI agent architecture keeps the skill layer separate from routing.",
            "context-note",
        ),
    ]
    support_refs = [
        {
            "evidence_id": item["evidence_id"],
            "locator_id": item["locator_id"],
            "exact_quote": item["passage_text"],
        }
        for item in evidence
    ]
    provider_text = json.dumps(
        {
            "schema_version": "aq3-provider-candidate/v3",
            "status": "answer_candidate",
            "relation": None,
            "selected_evidence_ids": [item["evidence_id"] for item in evidence],
            "answer_text": (
                "A skill is a mechanism or module in an AI agent architecture [[claim_1]]."
            ),
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_role": "direct",
                    "facet_ids": [
                        "definition_head",
                        "context_modifier",
                    ],
                    "support_mode": "exact_quote",
                    "support_refs": support_refs,
                }
            ],
            "missing_facets": [],
            "abstention_reason": None,
        }
    )

    with pytest.raises(legacy.VerifiedAnswerGateError) as exc:
        legacy._verify_multi_evidence_provider_output(
            trace_id="definition_negative",
            question=question,
            intent_class="direct_grounded_knowledge",
            evidence=evidence,
            provider_text=provider_text,
            semantic_review={
                "schema_version": "m26-claim-entailment-review/v1",
                "claim_judgments": [
                    {
                        "claim_id": "claim_1",
                        "verdict": "ENTAILED",
                        "evidence_ids": ["ev_skill", "ev_context"],
                    }
                ],
                "visible_coverage": {
                    "verdict": "COVERED",
                    "uncovered_assertions": [],
                },
            },
        )

    assert exc.value.code == "M26-PA7-ME-071"


def test_semantic_review_protocol_exposes_allowed_local_evidence_ids() -> None:
    question = "Explain router snapshots."
    evidence = [
        _rich_passage(
            "ev_router",
            "The router stores graph snapshots.",
            "router-note",
        ),
    ]
    candidate = _runtime_bound_candidate(
        answer="The router keeps graph snapshots.",
        question=question,
        intent_class="direct_grounded_knowledge",
        used_items=(),
        claims=[
            {
                "claim_id": "claim_1",
                "claim_type": "EVIDENCE_FACT",
                "surface_text": "The router keeps graph snapshots.",
                "evidence_labels": ["e1"],
                "covers": ["router_snapshots"],
            }
        ],
        label_map={"e1": evidence[0]},
        snippet_map={"ev_router": evidence[0]["passage_text"]},
    )

    payload = _semantic_review_payload(
        question=question,
        intent_class="direct_grounded_knowledge",
        candidate=candidate,
        evidence=evidence,
    )
    task = json.loads(payload["messages"][0]["content"])
    claim_case = task["claim_cases"][0]

    assert claim_case["allowed_evidence_ids"] == ["ev_router"]
    assert claim_case["allowed_evidence_labels"] == ["local_1"]
    assert claim_case["evidence_id_by_label"] == {"local_1": "ev_router"}
    assert claim_case["evidence"][0]["evidence_label"] == "local_1"
    assert "ev1" not in payload["system"]
    assert "ev1" not in payload["messages"][0]["content"]


def test_segment_binding_supplies_exact_provider_text_to_frozen_reviewer() -> None:
    question = "Explain router snapshots."
    evidence = [
        _rich_passage(
            "ev_router",
            "The router stores graph snapshots.",
            "router-note",
        ),
    ]
    segment_text = "The router keeps graph snapshots."
    candidate = _runtime_bound_candidate(
        answer=segment_text,
        question=question,
        intent_class="direct_grounded_knowledge",
        used_items=(),
        claims=None,
        segments=[
            {
                "segment_id": "s1",
                "semantic_role": "material_claim",
                "claim_id": "claim_1",
                "claim_type": "EVIDENCE_FACT",
                "text": segment_text,
                "evidence_labels": ["e1"],
                "covers": ["router_snapshots"],
            }
        ],
        label_map={"e1": evidence[0]},
        snippet_map={"ev_router": evidence[0]["passage_text"]},
    )

    payload = _semantic_review_payload(
        question=question,
        intent_class="direct_grounded_knowledge",
        candidate=candidate,
        evidence=evidence,
    )
    task = json.loads(payload["messages"][0]["content"])

    assert candidate["answer_text"] == segment_text
    assert candidate["claims"][0]["surface_text"] == segment_text
    assert task["claim_cases"][0]["surface_text"] == segment_text
    assert "claims" not in json.loads(_compact_provider_payload(
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        requirements=[],
        repair=False,
        previous_failures=[],
    )[0]["messages"][0]["content"])["output"]


def test_semantic_review_protocol_defines_model_explanation_verdict() -> None:
    candidate = {
        "answer_text": "The router chooses the path, and the DAG runs the steps.",
        "claims": [
            {
                "claim_id": "claim_1",
                "claim_type": "MODEL_EXPLANATION",
                "surface_text": "The router selection and DAG execution compose.",
                "support_refs": [],
            }
        ],
    }

    payload = _semantic_review_payload(
        question="How can a query router and a DAG work together?",
        intent_class="direct_grounded_knowledge",
        candidate=candidate,
        evidence=[],
    )
    task = json.loads(payload["messages"][0]["content"])
    claim_case = task["claim_cases"][0]

    assert claim_case["claim_type"] == "MODEL_EXPLANATION"
    assert claim_case["allowed_evidence_ids"] == []
    assert "GENERIC_EXPLANATION" in task["review_protocol"]["model_explanation_rule"]
    assert "return verdict GENERIC_EXPLANATION with evidence_ids []" in payload["system"]
    assert "MODEL_EXPLANATION glue claim" in payload["system"]


def test_semantic_review_claim_local_labels_are_canonicalized() -> None:
    question = "Explain router snapshots."
    evidence = [
        _rich_passage(
            "ev_router",
            "The router stores graph snapshots.",
            "router-note",
        ),
    ]

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        router_label = str(task["evidence"][0]["id"])
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": "The router keeps graph snapshots.",
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The router keeps graph snapshots.",
                    "evidence_labels": [router_label],
                    "covers": ["router_snapshots"],
                }
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    def review(task: dict[str, Any]) -> dict[str, Any]:
        claim_case = task["claim_cases"][0]
        assert claim_case["allowed_evidence_labels"] == ["local_1"]
        return {
            "schema_version": "m26-claim-entailment-review/v1",
            "claim_judgments": [
                {
                    "claim_id": str(claim_case["claim_id"]),
                    "verdict": "ENTAILED",
                    "evidence_ids": ["local_1"],
                }
            ],
            "visible_coverage": {
                "verdict": "COVERED",
                "uncovered_assertions": [],
            },
        }

    provider = _ScriptedSemanticClosureProvider([synthesis], review_result=review)

    answer, closure = _synthesize_and_verify(
        question=question,
        trace_id="trace-claim-local-review-label",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    semantic_review = answer["multi_evidence_verification"]["semantic_review"]
    assert answer["status"] == "owner_only_cited_answer"
    assert semantic_review["claim_judgments"][0]["evidence_ids"] == ["ev_router"]
    assert closure["failures"] == []


def test_semantic_review_out_of_local_evidence_ids_fail_closed() -> None:
    question = "Explain router snapshots and monitor events."
    evidence = [
        _rich_passage(
            "ev_router",
            "The router stores graph snapshots.",
            "router-note",
        ),
        _rich_passage(
            "ev_monitor",
            "The monitor accepts events.",
            "monitor-note",
        ),
    ]

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        labels = {
            "router": next(
                str(item["id"]) for item in task["evidence"] if "router" in item["text"]
            ),
            "monitor": next(
                str(item["id"]) for item in task["evidence"] if "monitor" in item["text"]
            ),
        }
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": (
                "The router keeps graph snapshots. The monitor accepts events."
            ),
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The router keeps graph snapshots.",
                    "evidence_labels": [labels["router"]],
                    "covers": ["router_snapshots"],
                },
                {
                    "claim_id": "claim_2",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": "The monitor accepts events.",
                    "evidence_labels": [labels["monitor"]],
                    "covers": ["monitor_events"],
                },
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    def review(task: dict[str, Any]) -> dict[str, Any]:
        judgments = []
        for case in task["claim_cases"]:
            local_ids = [str(item["evidence_id"]) for item in case["evidence"]]
            if str(case["claim_id"]) == "claim_1":
                evidence_ids = [local_ids[0], "not-local-to-this-claim"]
            else:
                evidence_ids = ["not-local-to-this-claim"]
            judgments.append(
                {
                    "claim_id": str(case["claim_id"]),
                    "verdict": "ENTAILED",
                    "evidence_ids": evidence_ids,
                }
            )
        return {
            "schema_version": "m26-claim-entailment-review/v1",
            "claim_judgments": judgments,
            "visible_coverage": {
                "verdict": "UNCOVERED",
                "uncovered_assertions": ["diagnostic only"],
            },
        }

    provider = _ScriptedSemanticClosureProvider(
        [synthesis, synthesis],
        review_result=review,
    )

    answer, closure = _synthesize_and_verify(
        question=question,
        trace_id="trace-claim-local-review-partial",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert answer["status"] == "owner_only_safe_abstention"
    assert answer["answer_source"] == "safe_abstention"
    assert answer["answer_text"] == ""
    assert "M26-PA7-ME-065" in closure["failures"]
    assert "M26-PA7-ME-065" in answer["reason_codes"]


def test_runtime_bound_structured_candidate_compacts_before_legacy_verification() -> None:
    question = "Explain how several supplied notes fit together."
    intent_class = "direct_grounded_knowledge"
    required_facets = legacy._required_facet_ids(
        question=question,
        intent_class=intent_class,
    )
    long_sentence = (
        "This supplied note describes a grounded production behavior with enough "
        "specific words to serve as an exact support quote for verification. "
    )
    evidence = [
        _rich_passage(
            f"ev_{index}",
            long_sentence * 8,
            f"note-{index}",
        )
        for index in range(10)
    ]

    def synthesis(task: dict[str, Any]) -> dict[str, Any]:
        labels = [str(item["id"]) for item in task["evidence"]]
        surfaces = [
            "Several supplied notes jointly describe grounded production behavior.",
            "The supplied notes include specific words for verification.",
            "The supplied notes serve as exact support quotes for verification.",
        ]
        claims = [
            {
                "claim_id": f"claim_{index}",
                "claim_type": "EVIDENCE_SYNTHESIS",
                "surface_text": surface_text,
                "evidence_labels": labels,
                "covers": required_facets,
            }
            for index, surface_text in enumerate(surfaces, start=1)
        ]
        return {
            "schema_version": "m26-fas-synthesis/v1",
            "status": "answer",
            "answer_text": " ".join(claim["surface_text"] for claim in claims),
            "claims": claims,
            "unanswered_dimensions": [],
            "abstention_reason": None,
        }

    def review(task: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "m26-claim-entailment-review/v1",
            "claim_judgments": [
                {
                    "claim_id": str(case["claim_id"]),
                    "verdict": "ENTAILED",
                    "evidence_ids": [
                        str(item["evidence_id"]) for item in case["evidence"]
                    ],
                }
                for case in task["claim_cases"]
            ],
            "visible_coverage": {
                "verdict": "COVERED",
                "uncovered_assertions": [],
            },
        }

    provider = _ScriptedSemanticClosureProvider(
        [synthesis],
        review_result=review,
    )

    answer, closure = _synthesize_and_verify(
        question=question,
        trace_id="trace-compact-verification-candidate",
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert answer["reason_codes"] == []
    assert "M26-PA7-ME-001" not in answer["multi_evidence_verification"][
        "verification_failure_codes_by_attempt"
    ]
    assert closure["failures"] == []


def test_verification_candidate_publishes_minimal_bounded_schema() -> None:
    question = "Explain how several supplied notes fit together."
    intent_class = "direct_grounded_knowledge"
    required_facets = legacy._required_facet_ids(
        question=question,
        intent_class=intent_class,
    )
    evidence = [
        _rich_passage(
            f"ev_{index}",
            (
                "This supplied note describes a grounded production behavior with enough "
                "specific words to serve as an exact support quote for verification. "
            )
            * 8,
            f"note-{index}",
        )
        for index in range(10)
    ]
    label_map = {f"e{index + 1}": item for index, item in enumerate(evidence)}
    snippet_map = {
        str(item["evidence_id"]): str(item["passage_text"]) for item in evidence
    }
    claims = [
        {
            "claim_id": f"claim_{index}",
            "claim_type": "EVIDENCE_SYNTHESIS",
            "surface_text": (
                "Several supplied notes jointly describe grounded production "
                f"behavior {index} with enough visible specificity to stress the "
                "legacy verification publication bound."
            ),
            "evidence_labels": list(label_map),
            "covers": required_facets,
        }
        for index in range(1, 13)
    ]
    candidate = _runtime_bound_candidate(
        answer=" ".join(str(claim["surface_text"]) for claim in claims),
        question=question,
        intent_class=intent_class,
        used_items=(),
        claims=claims,
        label_map=label_map,
        snippet_map=snippet_map,
    )

    bounded, support_ref_limit = _bounded_publication_candidate(candidate)
    published = _verification_candidate(bounded)
    provider_text = json.dumps(published, ensure_ascii=False, separators=(",", ":"))

    assert len(provider_text) < 12_000
    assert support_ref_limit is not None
    assert set(published) == {
        "schema_version",
        "status",
        "relation",
        "selected_evidence_ids",
        "answer_text",
        "claims",
        "missing_facets",
        "abstention_reason",
        "unanswered_dimensions",
    }
    assert all("evidence_labels" not in claim for claim in published["claims"])
    assert all("covers" not in claim for claim in published["claims"])
    assert all(
        len(claim["support_refs"]) == support_ref_limit
        for claim in published["claims"]
    )
    assert all(
        len(ref["exact_quote"]) <= 120
        for claim in published["claims"]
        for ref in claim["support_refs"]
    )


def test_runtime_bound_graph_claim_preserves_provider_selected_edge_only_support() -> None:
    edge = _graph_edge("ev_edge", "part_1", "part_2", "precedes")
    part_1 = {
        **_rich_passage("ev_part_1", "Part 1 appears first in the series.", "part-1"),
        "concept_id": "part_1",
    }
    part_2 = {
        **_rich_passage("ev_part_2", "Part 2 appears second in the series.", "part-2"),
        "concept_id": "part_2",
    }

    candidate = _runtime_bound_candidate(
        answer=(
            "Part 1 precedes Part 2 in graph order, and that edge does not by "
            "itself prove dependency."
        ),
        question="Does a precedes edge prove Part 1 depends on Part 2?",
        intent_class="graph_relationship",
        used_items=(),
        claims=[
            {
                "claim_id": "claim_1",
                "claim_type": "EVIDENCE_SYNTHESIS",
                "surface_text": (
                    "Part 1 precedes Part 2 in graph order, and that edge does "
                    "not by itself prove dependency."
                ),
                "evidence_labels": ["e1"],
                "covers": ["graph_edge", "ordering_boundary"],
            }
        ],
        label_map={"e1": edge, "e2": part_1, "e3": part_2},
        snippet_map={
            "ev_edge": edge["passage_text"],
            "ev_part_1": part_1["passage_text"],
            "ev_part_2": part_2["passage_text"],
        },
    )

    support_ids = {
        ref["evidence_id"]
        for ref in candidate["claims"][0]["support_refs"]
    }
    assert support_ids == {"ev_edge"}
    assert set(candidate["selected_evidence_ids"]) == support_ids


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
    assert "Unsupported boundary" not in candidate["answer_text"]
    assert "observability" in candidate["unanswered_dimensions"]
    assert all(
        "observability status" not in str(claim.get("surface_text", "")).casefold()
        for claim in candidate["claims"]
        if claim.get("claim_type") != "MODEL_EXPLANATION"
    )
