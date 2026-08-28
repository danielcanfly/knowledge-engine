from __future__ import annotations

import json
from typing import Any

from knowledge_engine.m26_pa7_semantic_closure_runtime import (
    _add_provider_call_observability,
    _attach_runtime_observability,
    _new_runtime_observability,
    _parse_compact_provider_result,
    _requirement_support_failures,
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


def _passage(evidence_id: str, text: str) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "passage",
        "locator_id": f"loc-{evidence_id}",
        "release_id": "release-test",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "concept_id": f"concept-{evidence_id}",
        "section_id": f"section-{evidence_id}",
        "source_id": f"source-{evidence_id}",
        "source_identity": f"source-{evidence_id}",
        "title": "Runtime Evidence",
        "section_title": "Overview",
        "channels": ["dense"],
        "passage_text": text,
        "passage_text_sha256": sha256_bytes(text.encode("utf-8")),
        "provenance_record_sha256": "b" * 64,
        "retrieved_at": "",
        "retrieval_metadata": {"query_overlap_score": 1.0},
    }


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


def test_provider_abstain_with_available_evidence_uses_verified_deterministic_fallback() -> None:
    question = (
        "If a client disconnects, how does the admission policy, durable state authority, "
        "continued execution, completion verification, and observability reattachment keep "
        "the run trustworthy from admission to completion?"
    )
    evidence = [
        _passage(
            "ev1",
            (
                "An admitted task remains trustworthy through admission policy, durable "
                "persisted state authority, continued execution after disconnect, completion "
                "verification, and observability for reattachment status."
            ),
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
    assert (
        verification["provider_contract"]
        == "compact_runtime_bound_semantic_closure/v1"
    )
    assert closure["failures"] == []
    assert closure["broad_deterministic_fallback_used"] is True
    assert "PROVIDER_ABSTAINED_WITH_AVAILABLE_EVIDENCE" in closure[
        "pre_recovery_failures"
    ]


def test_runtime_observability_keeps_only_sanitized_timing_and_counts() -> None:
    observability = _new_runtime_observability()
    verification = {
        "multi_evidence_verification": {
            "provider_attempt_telemetry": [
                {
                    "provider_text": "",
                    "provider_text_char_count": 321,
                    "call_class": "aq_semantic_closure",
                    "latency_ms": 1234,
                    "usage": {
                        "input_tokens": 55,
                        "output_tokens": 13,
                        "total_tokens": 68,
                    },
                    "parse_telemetry": {
                        "parse_ok": True,
                        "parse_subtype": "compact_semantic_closure_json",
                    },
                }
            ]
        }
    }

    _add_provider_call_observability(observability, verification)
    response = _attach_runtime_observability({"status": "ok"}, observability)

    runtime_observability = response["runtime_observability"]
    assert runtime_observability["schema_version"] == "m26-pa7-runtime-observability/v1"
    assert runtime_observability["provider_call_timings"] == [
        {
            "attempt": 1,
            "call_class": "aq_semantic_closure",
            "latency_ms": 1234,
            "provider_text_char_count": 321,
            "input_tokens": 55,
            "output_tokens": 13,
            "total_tokens": 68,
            "parse_ok": True,
            "parse_subtype": "compact_semantic_closure_json",
        }
    ]
    assert runtime_observability["totals"]["provider_latency_ms_sum"] == 1234
    assert runtime_observability["totals"]["provider_wall_elapsed_ms_sum"] == 0
    encoded = json.dumps(runtime_observability, ensure_ascii=False)
    assert '"provider_text":' not in encoded
    assert "question" not in encoded


def test_router_vs_replanner_implicit_wording_gets_both_roles() -> None:
    question = (
        "One mechanism decides where a request should go; another changes the remaining work "
        "when reality invalidates the plan. How are their jobs different?"
    )
    requirements = _semantic_requirements(question, "cross_document_comparison")
    ids = {item.requirement_id for item in requirements}
    assert {"initial_routing_role", "replanning_role", "role_contrast"}.issubset(ids)
