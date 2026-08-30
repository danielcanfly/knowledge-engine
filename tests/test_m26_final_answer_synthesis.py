from __future__ import annotations

import json
from typing import Any

from knowledge_engine.m26_pa7_semantic_closure_runtime import (
    _parse_compact_provider_result,
    _semantic_requirements,
    _synthesize_and_verify,
)
from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes

SEMANTIC_REVIEW_CALL_CLASS = "aq_claim_semantic_entailment"
SEGMENT_SCHEMA_VERSION = "m26-fas-synthesis/segments/v1"


def _passage(evidence_id: str, text: str, source: str) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "locator_id": f"loc_{evidence_id}",
        "evidence_type": "passage",
        "source_id": source,
        "source_identity": source,
        "concept_id": f"concept_{evidence_id}",
        "title": source,
        "section_title": source,
        "section_id": f"section_{evidence_id}",
        "release_id": "release-test",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "provenance_record_sha256": "b" * 64,
        "channels": ["dense"],
        "passage_text": text,
        "passage_text_sha256": sha256_bytes(text.encode("utf-8")),
    }


def _semantic_review_response(payload: dict[str, Any]) -> dict[str, Any]:
    task = json.loads(payload["messages"][0]["content"])
    answer = str(task["answer_text"]).casefold()
    question = str(task["question_context"]).casefold()
    judgments = []
    for case in task["claim_cases"]:
        local_ids = [str(item["evidence_id"]) for item in case["evidence"]]
        if str(case["claim_type"]) == "MODEL_EXPLANATION" and not local_ids:
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
    coverage_verdict = "COVERED"
    uncovered: list[str] = []
    if "verification" in question and "verification" not in answer:
        coverage_verdict = "UNCOVERED"
        uncovered = ["verification"]
    return {
        "schema_version": "m26-claim-entailment-review/v1",
        "claim_judgments": judgments,
        "visible_coverage": {
            "verdict": coverage_verdict,
            "uncovered_assertions": uncovered,
        },
    }


def _synthesis_calls(provider: Any) -> list[dict[str, Any]]:
    return [
        call
        for call in provider.calls
        if call["call_class"] != SEMANTIC_REVIEW_CALL_CLASS
    ]


class _TypedProvider:
    def __init__(self, *, claim_type: str, answer_text: str, claims: list[dict[str, Any]]) -> None:
        self.claim_type = claim_type
        self.answer_text = answer_text
        self.claims = claims
        self.calls: list[dict[str, Any]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append({"payload": payload, "call_class": call_class})
        if call_class == SEMANTIC_REVIEW_CALL_CLASS:
            return {
                "text": json.dumps(_semantic_review_response(payload)),
                "usage": {"input_tokens": 128, "output_tokens": 48},
                "cost_usd": "0.00001",
                "latency_ms": 4,
                "response_id": "typed-provider-review",
                "call_class": call_class,
            }
        return {
            "text": json.dumps(_typed_body(
                status="answer",
                answer_text=self.answer_text,
                claims=self.claims,
            )),
            "usage": {"input_tokens": 128, "output_tokens": 48},
            "cost_usd": "0.00001",
            "latency_ms": 4,
            "response_id": "typed-provider-1",
            "call_class": call_class,
        }


class _SequenceTypedProvider:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.synthesis_call_count = 0

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append({"payload": payload, "call_class": call_class})
        if call_class == SEMANTIC_REVIEW_CALL_CLASS:
            return {
                "text": json.dumps(_semantic_review_response(payload)),
                "usage": {"input_tokens": 128, "output_tokens": 48},
                "cost_usd": "0.00001",
                "latency_ms": 4,
                "response_id": f"typed-provider-review-{len(self.calls)}",
                "call_class": call_class,
            }
        self.synthesis_call_count += 1
        index = min(self.synthesis_call_count, len(self.responses)) - 1
        return {
            "text": json.dumps(self.responses[index]),
            "usage": {"input_tokens": 128, "output_tokens": 48},
            "cost_usd": "0.00001",
            "latency_ms": 4,
            "response_id": f"typed-provider-{len(self.calls)}",
            "call_class": call_class,
        }


class _TruncatingThenTypedProvider:
    def __init__(self, *, answer_text: str, claims: list[dict[str, Any]]) -> None:
        self.answer_text = answer_text
        self.claims = claims
        self.calls: list[dict[str, Any]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append({"payload": payload, "call_class": call_class})
        if call_class == SEMANTIC_REVIEW_CALL_CLASS:
            return {
                "text": json.dumps(_semantic_review_response(payload)),
                "usage": {"input_tokens": 128, "output_tokens": 48},
                "cost_usd": "0.00001",
                "latency_ms": 4,
                "response_id": "typed-provider-review",
                "call_class": call_class,
            }
        synthesis_call_count = len(_synthesis_calls(self))
        if synthesis_call_count == 1:
            return {
                "text": (
                    '{"schema_version":"m26-fas-synthesis/segments/v1","status":"answer",'
                    '"segments":[{"segment_id":"s1","semantic_role":"material_claim",'
                    '"claim_id":"claim_1","claim_type":"EVIDENCE_FACT","text":"truncated'
                ),
                "usage": {
                    "input_tokens": 128,
                    "output_tokens": int(payload["max_tokens"]),
                },
                "stop_reason": "max_tokens",
                "cost_usd": "0.00001",
                "latency_ms": 4,
                "response_id": "typed-provider-truncated",
                "call_class": call_class,
            }
        return {
            "text": json.dumps(_typed_body(
                status="answer",
                answer_text=self.answer_text,
                claims=self.claims,
            )),
            "usage": {"input_tokens": 128, "output_tokens": 96},
            "stop_reason": "stop",
            "cost_usd": "0.00001",
            "latency_ms": 4,
            "response_id": "typed-provider-repaired",
            "call_class": call_class,
        }


def test_typed_compact_provider_contract_is_accepted() -> None:
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
                        "claim_type": "EVIDENCE_SYNTHESIS",
                        "text": "Durable state and verification solve different problems.",
                        "evidence_labels": ["e1", "e2"],
                        "covers": ["durable_state", "verification_completion"],
                    }
                ],
                "unanswered_dimensions": [],
                "abstention_reason": None,
            }
        )
    )

    assert parsed["status"] == "answer"
    assert parsed["segments"][0]["text"].startswith("Durable state")
    assert parsed["segments"][0]["claim_type"] == "EVIDENCE_SYNTHESIS"
    assert parsed["segments"][0]["evidence_labels"] == ["e1", "e2"]


def test_typed_synthesis_preserves_plain_answer_and_supports_synthesis() -> None:
    question = "Why do durable state and verification solve different reliability problems?"
    evidence = [
        _passage(
            "e1",
            "Durable state preserves progress after a disconnect.",
            "durable-note",
        ),
        _passage(
            "e2",
            "Completion verification checks the final result before acceptance.",
            "verification-note",
        ),
    ]
    answer_text = (
        "Durable state preserves progress after a disconnect, while verification checks "
        "the final result before acceptance."
    )
    provider = _TypedProvider(
        claim_type="EVIDENCE_SYNTHESIS",
        answer_text=answer_text,
        claims=[
            {
                "claim_id": "claim_1",
                "claim_type": "EVIDENCE_SYNTHESIS",
                "surface_text": answer_text,
                "evidence_labels": ["e1", "e2"],
                "covers": ["durable_state", "verification_completion"],
            }
        ],
    )

    answer, closure = _run_typed_synthesis(question, evidence, provider)

    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_text"] == answer_text
    assert "[claim_" not in answer["answer_text"]
    assert answer["answer_claims"][0]["claim_type"] == "EVIDENCE_SYNTHESIS"
    assert len(answer["citations"]) == 2
    assert answer_text not in evidence[0]["passage_text"]
    assert answer_text not in evidence[1]["passage_text"]
    assert closure["failures"] == []


def test_model_explanation_claim_type_survives_verification() -> None:
    question = "Can we safely infer that an explanation proves a direct factual claim?"
    evidence = [
        _passage(
            "e1",
            "A model explanation can provide generic framing without inventing facts.",
            "explanation-note",
        )
    ]
    material_text = "A model explanation can provide generic framing without inventing facts."
    glue_text = (
        "A model explanation stays generic and does not prove a direct factual claim."
    )
    answer_text = f"{material_text} {glue_text}"
    provider = _TypedProvider(
        claim_type="EVIDENCE_SYNTHESIS",
        answer_text=answer_text,
        claims=[
                {
                    "claim_id": "claim_0",
                    "claim_type": "EVIDENCE_FACT",
                    "surface_text": material_text,
                    "evidence_labels": ["e1"],
                    "covers": ["direct_answer"],
                },
                {
                    "claim_id": "claim_1",
                    "claim_type": "MODEL_EXPLANATION",
                    "surface_text": glue_text,
                    "evidence_labels": [],
                    "covers": ["non_entailment_boundary"],
                }
            ],
        )

    answer, closure = _run_typed_synthesis(question, evidence, provider)

    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_text"] == answer_text
    assert "[claim_" not in answer["answer_text"]
    assert any(
        claim["claim_type"] == "MODEL_EXPLANATION"
        for claim in answer["answer_claims"]
    )
    assert closure["failures"] == []


def test_numbered_corpus_statement_miscast_as_model_explanation_still_fails_closed() -> None:
    question = "What does Part 2 establish?"
    evidence = [
        _passage(
            "e1",
            "Part 2 establishes the verification boundary.",
            "numbered-boundary-note",
        )
    ]
    provider = _TypedProvider(
        claim_type="MODEL_EXPLANATION",
        answer_text="Part 2 establishes the verification boundary.",
        claims=[
            {
                "claim_id": "claim_1",
                "claim_type": "MODEL_EXPLANATION",
                "surface_text": "Part 2 establishes the verification boundary.",
                "evidence_labels": [],
                "covers": [],
            }
        ],
    )

    answer, closure = _run_typed_synthesis(question, evidence, provider)

    assert answer["status"] == "owner_only_safe_abstention"
    assert answer["unsupported_accepted_claims"] == 0
    assert "M26-PA7-ME-033" in answer["reason_codes"]
    assert "M26-PA7-ME-033" in closure["failures"]


def test_canonical_path_uses_typed_compact_synthesis_payload() -> None:
    question = "Why do durable state and verification solve different reliability problems?"
    evidence = [
        _passage(
            "e1",
            "Durable state preserves progress after a disconnect.",
            "durable-note",
        ),
        _passage(
            "e2",
            "Completion verification checks the final result before acceptance.",
            "verification-note",
        ),
    ]
    provider = _TypedProvider(
        claim_type="EVIDENCE_SYNTHESIS",
        answer_text=(
            "Durable state preserves progress after a disconnect, while verification checks "
            "the final result before acceptance."
        ),
        claims=[
            {
                "claim_id": "claim_1",
                "claim_type": "EVIDENCE_SYNTHESIS",
                "surface_text": (
                    "Durable state preserves progress after a disconnect, while verification "
                    "checks the final result before acceptance."
                ),
                "evidence_labels": ["e1", "e2"],
                "covers": ["durable_state", "verification_completion"],
            }
        ],
    )

    _run_typed_synthesis(question, evidence, provider)
    assert provider.calls
    payload = provider.calls[0]["payload"]
    task = json.loads(payload["messages"][0]["content"])
    assert task["output"]["schema_version"] == SEGMENT_SCHEMA_VERSION
    assert "claims" not in task["output"]
    assert "answer_text" not in task["output"]
    assert task["output"]["segments"][0]["claim_type"] == (
        "EVIDENCE_FACT|EVIDENCE_SYNTHESIS"
    )
    assert task["output"]["segments"][0]["semantic_role"] == "material_claim"
    assert task["output"]["segments"][0]["evidence_labels"] == ["e1"]
    assert task["output"]["segments"][0]["covers"] == []
    assert payload["max_tokens"] > 512


def test_compact_segment_role_contract_keeps_evidence_boundaries_material() -> None:
    question = "What relation does the supplied evidence support and not support?"
    evidence = [
        _passage(
            "e1",
            "Part 1 defines ingestion. Part 2 defines verification. The graph links "
            "Part 2 to the verification boundary, not to the ingestion boundary.",
            "numbered-relation-note",
        ),
    ]
    provider = _TypedProvider(
        claim_type="EVIDENCE_SYNTHESIS",
        answer_text="Part 2 is tied to verification, not ingestion.",
        claims=[
            {
                "claim_id": "claim_1",
                "claim_type": "EVIDENCE_SYNTHESIS",
                "surface_text": "Part 2 is tied to verification, not ingestion.",
                "evidence_labels": ["e1"],
                "covers": ["relation_boundary"],
            }
        ],
    )

    _run_typed_synthesis(question, evidence, provider)
    payload = provider.calls[0]["payload"]
    task = json.loads(payload["messages"][0]["content"])
    system = payload["system"]

    assert task["output"]["segments"][0]["semantic_role"] == "material_claim"
    assert task["output"]["segments"][0]["claim_type"] == (
        "EVIDENCE_FACT|EVIDENCE_SYNTHESIS"
    )
    assert "numbered or versioned entities" in system
    assert "supplied graph relations" in system
    assert "what supplied evidence entails or does not entail" in system
    assert "supported negation, limitation, boundary, comparison, or non-inference" in system
    assert "If uncertain between material_claim and model_explanation" in system
    assert "choose material_claim and bind evidence" in system


def test_compact_segment_role_contract_allows_evidence_independent_glue() -> None:
    question = "How can the pieces fit together?"
    evidence = [
        _passage(
            "e1",
            "The router selects evidence. The verifier checks supported claims.",
            "glue-note",
        ),
    ]
    provider = _TypedProvider(
        claim_type="MODEL_EXPLANATION",
        answer_text="Together, those steps form a check-and-balance.",
        claims=[
            {
                "claim_id": "claim_1",
                "claim_type": "MODEL_EXPLANATION",
                "surface_text": "Together, those steps form a check-and-balance.",
                "evidence_labels": [],
                "covers": [],
            }
        ],
    )

    _run_typed_synthesis(question, evidence, provider)
    system = provider.calls[0]["payload"]["system"]

    assert "Use model_explanation only for genuinely generic connective" in system
    assert "truth does not depend on supplied KB evidence" in system
    assert "claim_type MODEL_EXPLANATION" in system
    assert "evidence_labels []" in system


def test_max_tokens_truncation_gets_larger_bounded_repair_budget() -> None:
    question = "Why do durable state and verification solve different reliability problems?"
    evidence = [
        _passage(
            "e1",
            "Durable state preserves progress after a disconnect.",
            "durable-note",
        ),
        _passage(
            "e2",
            "Completion verification checks the final result before acceptance.",
            "verification-note",
        ),
    ]
    answer_text = (
        "Durable state preserves progress after a disconnect, while verification checks "
        "the final result before acceptance."
    )
    provider = _TruncatingThenTypedProvider(
        answer_text=answer_text,
        claims=[
            {
                "claim_id": "claim_1",
                "claim_type": "EVIDENCE_SYNTHESIS",
                "surface_text": answer_text,
                "evidence_labels": ["e1", "e2"],
                "covers": ["explanatory_answer", "comparison_or_distinction"],
            }
        ],
    )

    answer, closure = _run_typed_synthesis(question, evidence, provider)

    synthesis_calls = _synthesis_calls(provider)
    assert len(synthesis_calls) == 2
    first_budget = synthesis_calls[0]["payload"]["max_tokens"]
    repair_budget = synthesis_calls[1]["payload"]["max_tokens"]
    assert first_budget > 512
    assert repair_budget > first_budget
    assert synthesis_calls[1]["call_class"] == "aq_semantic_closure_repair"
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert answer["answer_text"] == answer_text
    assert answer["repair_attempted"] is True
    telemetry = answer["multi_evidence_verification"]["provider_attempt_telemetry"]
    assert telemetry[0]["truncation_detected"] is True
    assert "COMPACT_PROVIDER_TRUNCATED" in answer["multi_evidence_verification"][
        "verification_failure_codes_by_attempt"
    ]
    assert closure["failures"] == []


def test_long_multi_dimension_answer_publishes_directly_without_512_ceiling() -> None:
    question = "Why do durable state and verification solve different reliability problems?"
    evidence = [
        _passage(
            "e1",
            "Durable state preserves progress after a disconnect.",
            "durable-note",
        ),
        _passage(
            "e2",
            "Completion verification checks the final result before acceptance.",
            "verification-note",
        ),
    ]
    sentence = (
        "Durable state preserves progress after a disconnect, while completion "
        "verification checks the final result before acceptance."
    )
    answer_text = " ".join([sentence] * 18)
    claim_surface = sentence
    assert 1800 < len(answer_text) < 4096
    provider = _TypedProvider(
        claim_type="EVIDENCE_SYNTHESIS",
        answer_text=answer_text,
        claims=[
                {
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_SYNTHESIS",
                    "surface_text": claim_surface,
                    "evidence_labels": ["e1", "e2"],
                    "covers": ["durable_state", "completion_verification"],
                }
        ],
    )

    answer, closure = _run_typed_synthesis(question, evidence, provider)

    assert _synthesis_calls(provider)[0]["payload"]["max_tokens"] > 512
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_text"] == answer_text
    assert answer["repair_attempted"] is False
    assert closure["failures"] == []


def test_incomplete_answer_gets_one_bounded_repair() -> None:
    question = "Why do durable state and verification solve different reliability problems?"
    evidence = [
        _passage(
            "e1",
            "Durable state preserves progress after a disconnect.",
            "durable-note",
        ),
        _passage(
            "e2",
            "Completion verification checks the final result before acceptance.",
            "verification-note",
        ),
    ]
    incomplete = "Durable state preserves progress after a disconnect."
    complete = (
        "Durable state preserves progress after a disconnect, while verification checks "
        "the final result before acceptance."
    )
    provider = _SequenceTypedProvider(
        [
            _typed_body(
                status="answer",
                answer_text=incomplete,
                claims=[
                    {
                        "claim_id": "claim_1",
                        "claim_type": "EVIDENCE_FACT",
                        "surface_text": incomplete,
                        "evidence_labels": ["e1"],
                        "covers": ["explanatory_answer"],
                    }
                ],
            ),
            _typed_body(
                status="answer",
                answer_text=complete,
                claims=[
                    {
                        "claim_id": "claim_1",
                        "claim_type": "EVIDENCE_SYNTHESIS",
                        "surface_text": complete,
                        "evidence_labels": ["e1", "e2"],
                        "covers": [
                            "explanatory_answer",
                            "comparison_or_distinction",
                        ],
                    }
                ],
            ),
        ]
    )

    answer, closure = _run_typed_synthesis(question, evidence, provider)

    synthesis_calls = _synthesis_calls(provider)
    assert len(synthesis_calls) == 2
    assert synthesis_calls[1]["call_class"] == "aq_semantic_closure_repair"
    assert answer["answer_text"] == complete
    assert answer["repair_attempted"] is True
    assert closure["failures"] == []


def test_repeated_incomplete_answer_does_not_recursive_repair() -> None:
    question = "Why do durable state and verification solve different reliability problems?"
    evidence = [
        _passage(
            "e1",
            "Durable state preserves progress after a disconnect.",
            "durable-note",
        ),
        _passage(
            "e2",
            "Completion verification checks the final result before acceptance.",
            "verification-note",
        ),
    ]
    incomplete = "Durable state preserves progress after a disconnect."
    provider = _SequenceTypedProvider(
        [
            _typed_body(
                status="answer",
                answer_text=incomplete,
                claims=[
                    {
                        "claim_id": "claim_1",
                        "claim_type": "EVIDENCE_FACT",
                        "surface_text": incomplete,
                        "evidence_labels": ["e1"],
                        "covers": ["explanatory_answer"],
                    }
                ],
            )
        ]
    )

    _run_typed_synthesis(question, evidence, provider)

    assert len(_synthesis_calls(provider)) == 2


def test_supported_partial_answer_states_unsupported_boundary() -> None:
    question = "Why do durable state and verification solve different reliability problems?"
    evidence = [
        _passage(
            "e1",
            "Durable state preserves progress after a disconnect.",
            "durable-note",
        )
    ]
    partial = "Durable state helps because it preserves progress after a disconnect."
    provider = _SequenceTypedProvider(
        [
            _typed_body(
                status="partial",
                answer_text=partial,
                claims=[
                    {
                        "claim_id": "claim_1",
                        "claim_type": "EVIDENCE_FACT",
                        "surface_text": partial,
                        "evidence_labels": ["e1"],
                        "covers": ["explanatory_answer"],
                        "unanswered_dimensions": ["verification side"],
                    }
                ],
                unanswered_dimensions=["verification side"],
            )
        ]
    )

    answer, closure = _run_typed_synthesis(question, evidence, provider)

    assert len(_synthesis_calls(provider)) == 2
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["repair_attempted"] is True
    assert "Unsupported boundary" not in answer["answer_text"]
    assert answer["multi_evidence_verification"]["partial_answer"] is True
    assert closure["partial_answer"] is True


def test_unsupported_core_query_fully_abstains() -> None:
    question = "Why do durable state and verification solve different reliability problems?"
    provider = _SequenceTypedProvider(
        [
            _typed_body(
                status="abstain",
                answer_text="",
                claims=[],
                unanswered_dimensions=["core answer"],
                abstention_reason="INSUFFICIENT_SUPPORT",
            )
        ]
    )

    answer, closure = _run_typed_synthesis(question, [], provider)

    assert answer["status"] == "owner_only_safe_abstention"
    assert answer["safe_abstention"] is True
    assert "SEMANTIC_CLOSURE_FAILED" in answer["reason_codes"]
    assert closure["failures"]


def test_paraphrased_completeness_behavior_is_equivalent() -> None:
    question = "How are durable state and completion verification different?"
    evidence = [
        _passage(
            "e1",
            "Durable state preserves progress after a disconnect.",
            "durable-note",
        ),
        _passage(
            "e2",
            "Completion verification checks the final result before acceptance.",
            "verification-note",
        ),
    ]
    answer_text = (
        "Durable state preserves progress after a disconnect, while completion "
        "verification checks the final result before acceptance."
    )
    provider = _TypedProvider(
        claim_type="EVIDENCE_SYNTHESIS",
        answer_text=answer_text,
        claims=[
            {
                "claim_id": "claim_1",
                "claim_type": "EVIDENCE_SYNTHESIS",
                "surface_text": answer_text,
                "evidence_labels": ["e1", "e2"],
                "covers": [
                    "explanatory_answer",
                    "comparison_or_distinction",
                ],
            }
        ],
    )

    answer, closure = _run_typed_synthesis(question, evidence, provider)

    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_text"] == answer_text
    assert closure["failures"] == []


def _typed_body(
    *,
    status: str,
    answer_text: str,
    claims: list[dict[str, Any]],
    unanswered_dimensions: list[str] | None = None,
    abstention_reason: str | None = None,
) -> dict[str, Any]:
    claim_surfaces = [
        str(claim.get("surface_text", "")).strip()
        for claim in claims
        if str(claim.get("surface_text", "")).strip()
    ]
    joined_claim_surfaces = " ".join(claim_surfaces)
    segments = []
    for index, claim in enumerate(claims, start=1):
        claim_type = str(claim.get("claim_type", "EVIDENCE_FACT"))
        segment_text = str(claim.get("surface_text", "")).strip()
        if len(claims) == 1 and answer_text.strip() != joined_claim_surfaces:
            segment_text = answer_text.strip()
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
                "text": segment_text,
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
        "status": status,
        "segments": segments,
        "unanswered_dimensions": unanswered_dimensions or [],
        "abstention_reason": abstention_reason,
    }


def _run_typed_synthesis(
    question: str,
    evidence: list[dict[str, Any]],
    provider: _TypedProvider,
) -> tuple[dict[str, Any], dict[str, Any]]:
    requirements = _semantic_requirements(question, "direct_grounded_knowledge")
    return _synthesize_and_verify(
        question=question,
        trace_id="trace-typed-fas",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=requirements,
        endpoint_proof={"required": False, "matched": False},
    )
