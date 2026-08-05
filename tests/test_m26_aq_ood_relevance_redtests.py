from __future__ import annotations

import json
from typing import Any

import pytest

from knowledge_engine import m26_pa7_arbitrary_query_runtime as runtime
from knowledge_engine.m26_verified_answer_citation_gate import VerifiedAnswerGateError


EXPECTED_OOD_RELEVANCE_CODE = "M26-PA7-ME-047"


def _evidence(evidence_id: str, text: str, *, source: str = "source-a") -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "passage",
        "locator_id": f"loc-{evidence_id}",
        "source_id": source,
        "source_identity": source,
        "section_id": f"section-{evidence_id}",
        "concept_id": f"concept-{evidence_id}",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "release_id": "release-test",
        "passage_text": text,
        "passage_text_sha256": "b" * 64,
        "channels": ["query_coverage"],
        "retrieval_metadata": {"coverage_terms": sorted(runtime._coverage_terms(text))},
    }


def _candidate(
    *,
    answer_text: str,
    surface_text: str,
    evidence_id: str,
    locator_id: str,
    exact_quote: str,
    facet_ids: list[str] | None = None,
) -> str:
    claim_id = "claim_1"
    return json.dumps(
        {
            "schema_version": "aq3-provider-candidate/v3",
            "status": "answer_candidate",
            "relation": None,
            "selected_evidence_ids": [evidence_id],
            "answer_text": answer_text or f"{surface_text} [[{claim_id}]].",
            "claims": [
                {
                    "claim_id": claim_id,
                    "claim_role": "direct",
                    "surface_text": surface_text,
                    "facet_ids": facet_ids or ["direct_answer"],
                    "support_mode": "exact_quote",
                    "support_refs": [
                        {
                            "evidence_id": evidence_id,
                            "locator_id": locator_id,
                            "exact_quote": exact_quote,
                            "exact_support_snippet": exact_quote,
                            "uncertainty": "low",
                        }
                    ],
                }
            ],
            "missing_facets": [],
            "abstention_reason": None,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def test_bb18_nonexistent_protocol_provider_answer_is_rejected_as_ood_relevance() -> None:
    """BB18 red line: exact citation support is not enough when the subject is OOD."""
    question = (
        "What launch date was announced for the nonexistent cobalt-orchid "
        "moon-ferry ticketing protocol?"
    )
    quote = "The team is delighted and calls the launch a win."
    evidence = [_evidence("ev-bb18", quote, source="pm-product-data-and-experimentation")]

    with pytest.raises(VerifiedAnswerGateError) as exc_info:
        runtime._verify_multi_evidence_provider_output(
            trace_id="GPT-E-BB18-redtest",
            question=question,
            intent_class="direct_grounded_knowledge",
            evidence=evidence,
            provider_text=_candidate(
                answer_text="direct answer: The team is delighted and calls the launch a win [[claim_1]].",
                surface_text=quote,
                evidence_id="ev-bb18",
                locator_id="loc-ev-bb18",
                exact_quote=quote,
            ),
        )

    assert exc_info.value.code == EXPECTED_OOD_RELEVANCE_CODE
    assert "cobalt-orchid moon-ferry ticketing protocol" in str(exc_info.value)


def test_nonexistent_compound_entity_not_answered_from_individual_common_terms() -> None:
    """A fabricated compound entity must not be satisfied by scattered word overlap."""
    question = (
        "Which integration date did the nonexistent cobalt-orchid moon-ferry "
        "ticketing protocol announce?"
    )
    quote = (
        "The protocol launch date moved after the team tested the ferry booking module."
    )
    evidence = [_evidence("ev-compound", quote, source="release-notes")]

    with pytest.raises(VerifiedAnswerGateError) as exc_info:
        runtime._verify_multi_evidence_provider_output(
            trace_id="compound-ood-redtest",
            question=question,
            intent_class="direct_grounded_knowledge",
            evidence=evidence,
            provider_text=_candidate(
                answer_text="The protocol launch date moved after the team tested the ferry booking module [[claim_1]].",
                surface_text=quote,
                evidence_id="ev-compound",
                locator_id="loc-ev-compound",
                exact_quote=quote,
            ),
        )

    assert exc_info.value.code == EXPECTED_OOD_RELEVANCE_CODE
    assert "compound" in str(exc_info.value).casefold()


def test_positive_real_in_corpus_direct_answer_remains_verifiable() -> None:
    """Negative control: relevant in-corpus evidence should remain answerable."""
    question = "What is Knowledge Engine used for?"
    quote = (
        "Knowledge Engine is an owner-only system for turning accepted source records "
        "into cited answers."
    )
    evidence = [_evidence("ev-ke", quote, source="knowledge-engine-overview")]

    verified = runtime._verify_multi_evidence_provider_output(
        trace_id="positive-real-entity",
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_text=_candidate(
            answer_text="Knowledge Engine turns accepted source records into cited answers [[claim_1]].",
            surface_text=quote,
            evidence_id="ev-ke",
            locator_id="loc-ev-ke",
            exact_quote=quote,
        ),
    )

    assert verified["terminal_status"] == "verified_answer_ready_candidate"
    assert verified["missing_facets"] == []
    assert verified["used_evidence_ids"] == ["ev-ke"]


@pytest.mark.parametrize("part", ["Part 1", "Part 10"])
def test_frozen_like_part_questions_remain_answerable_when_entity_supported(part: str) -> None:
    """Negative control: supported Part-N entities must not be over-blocked as OOD."""
    question = f"What does Harness Theory {part} say about harnesses?"
    quote = f"Harness Theory {part} says a harness is a constraint system for repeatable work."
    evidence = [
        _evidence(f"ev-{part.lower().replace(' ', '-')}", quote, source="harness-theory")
    ]

    verified = runtime._verify_multi_evidence_provider_output(
        trace_id=f"frozen-like-{part.lower().replace(' ', '-')}",
        question=question,
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_text=_candidate(
            answer_text=(
                f"Harness Theory {part} frames harnesses as constraint systems "
                "for repeatable work [[claim_1]]."
            ),
            surface_text=quote,
            evidence_id=f"ev-{part.lower().replace(' ', '-')}",
            locator_id=f"loc-ev-{part.lower().replace(' ', '-')}",
            exact_quote=quote,
            facet_ids=[f"entity_harness_theory_{part.lower().replace(' ', '_')}"],
        ),
    )

    assert verified["terminal_status"] == "verified_answer_ready_candidate"
    assert verified["missing_facets"] == []
