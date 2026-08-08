from __future__ import annotations

import json
from typing import Any

from knowledge_engine.m26_pa7_semantic_closure_runtime import (
    _parse_compact_provider_result,
    _semantic_requirements,
    _synthesize_and_verify,
)
from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes


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


class _TypedProvider:
    def __init__(self, *, claim_type: str, answer_text: str, claims: list[dict[str, Any]]) -> None:
        self.claim_type = claim_type
        self.answer_text = answer_text
        self.claims = claims
        self.calls: list[dict[str, Any]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append({"payload": payload, "call_class": call_class})
        return {
            "text": json.dumps(
                {
                    "schema_version": "m26-fas-synthesis/v1",
                    "status": "answer",
                    "answer_text": self.answer_text,
                    "claims": self.claims,
                    "unanswered_dimensions": [],
                    "abstention_reason": None,
                }
            ),
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

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append({"payload": payload, "call_class": call_class})
        index = min(len(self.calls), len(self.responses)) - 1
        return {
            "text": json.dumps(self.responses[index]),
            "usage": {"input_tokens": 128, "output_tokens": 48},
            "cost_usd": "0.00001",
            "latency_ms": 4,
            "response_id": f"typed-provider-{len(self.calls)}",
            "call_class": call_class,
        }


def test_typed_compact_provider_contract_is_accepted() -> None:
    parsed = _parse_compact_provider_result(
        json.dumps(
            {
                "schema_version": "m26-fas-synthesis/v1",
                "status": "answer",
                "answer_text": "Durable state and verification solve different problems.",
                "claims": [
                    {
                        "claim_id": "claim_1",
                        "claim_type": "EVIDENCE_SYNTHESIS",
                        "surface_text": "Durable state and verification solve different problems.",
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
    assert parsed["answer_text"].startswith("Durable state")
    assert parsed["claims"][0]["claim_type"] == "EVIDENCE_SYNTHESIS"
    assert parsed["claims"][0]["evidence_labels"] == ["e1", "e2"]


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
    question = "Why is an explanation different from a direct factual claim?"
    evidence = [
        _passage(
            "e1",
            "A model explanation can provide generic framing without inventing facts.",
            "explanation-note",
        )
    ]
    answer_text = (
        "A model explanation gives generic framing instead of pretending to be a "
        "corpus fact."
    )
    provider = _TypedProvider(
        claim_type="MODEL_EXPLANATION",
        answer_text=answer_text,
        claims=[
            {
                "claim_id": "claim_1",
                "claim_type": "MODEL_EXPLANATION",
                "surface_text": answer_text,
                "evidence_labels": ["e1"],
                "covers": ["explanation_boundary"],
            }
        ],
    )

    answer, closure = _run_typed_synthesis(question, evidence, provider)

    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_claims"][0]["claim_type"] == "MODEL_EXPLANATION"
    assert answer["answer_text"] == answer_text
    assert "[claim_" not in answer["answer_text"]
    assert closure["failures"] == []


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
    assert task["output"]["schema_version"] == "m26-fas-synthesis/v1"
    assert task["output"]["claims"][0]["claim_type"] == (
        "EVIDENCE_FACT|EVIDENCE_SYNTHESIS|MODEL_EXPLANATION"
    )
    assert task["output"]["claims"][0]["evidence_labels"] == ["e1"]
    assert task["output"]["claims"][0]["covers"] == []


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

    assert len(provider.calls) == 2
    assert provider.calls[1]["call_class"] == "aq_semantic_closure_repair"
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

    assert len(provider.calls) == 2


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

    assert len(provider.calls) == 2
    assert answer["status"] == "owner_only_cited_answer"
    assert "Unsupported boundary" in answer["answer_text"]
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
    return {
        "schema_version": "m26-fas-synthesis/v1",
        "status": status,
        "answer_text": answer_text,
        "claims": claims,
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
