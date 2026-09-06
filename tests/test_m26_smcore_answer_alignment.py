from __future__ import annotations

import pytest

from knowledge_engine.m26_aq_semantic_contract import (
    _question_answer_alignment_failures,
)


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        (
            "What product rhythms need to change in the age of AI?",
            "need relation: True proximity to the opportunity.",
        ),
        (
            "When should a team run a field study instead of a usability test?",
            "So if you run a public server, restrict write tools.",
        ),
        (
            "Why should production RAG keep raw storage separate from metadata?",
            "Production agentic mode needs max_steps and allowed_tools.",
        ),
    ],
)
def test_alignment_gate_rejects_wrong_topic_or_internal_surface(
    question: str, answer: str
) -> None:
    evidence = [{"passage_text": answer, "source_identity": "test"}]
    assert _question_answer_alignment_failures(
        question=question, answer_text=answer, evidence=evidence
    )


def test_alignment_gate_accepts_evidence_grounded_direct_answer() -> None:
    question = "Why should production RAG keep raw storage separate from metadata?"
    answer = (
        "Production RAG should keep raw storage separate from metadata because raw "
        "documents can be reprocessed while metadata remains queryable and governed."
    )
    evidence = [{"passage_text": answer, "source_identity": "rag-guide"}]
    assert not _question_answer_alignment_failures(
        question=question, answer_text=answer, evidence=evidence
    )

