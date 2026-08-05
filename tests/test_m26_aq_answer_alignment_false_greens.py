from __future__ import annotations

from scripts.m26_aq_generalized_closure import _validate_question_answer_alignment


def _row(question: str, answer_text: str) -> dict[str, object]:
    return {
        "case_id": "alignment-case",
        "question": question,
        "answer_text": answer_text,
        "citations": [{"source_id": "source-a", "quote": answer_text}],
        "selected_evidence": [{"passage_text": answer_text}],
    }


def _failures(question: str, answer_text: str) -> set[str]:
    return set(_validate_question_answer_alignment(_row(question, answer_text)))


def test_comparison_question_rejects_role_table_scaffold_nonanswer() -> None:
    failures = _failures(
        "Compare the browser collector and final closure runner responsibilities.",
        "compare left: browser collector. compare right: final closure runner.",
    )

    assert "answer_alignment_debug_surface" in failures
    assert "answer_alignment_missing_comparison_distinction" in failures


def test_reliability_control_comparison_must_distinguish_controls() -> None:
    failures = _failures(
        "Compare the host lock and canonical tunnel controls for reliability.",
        "The closure path uses a control for reliability and records a cited result.",
    )

    assert "answer_alignment_missing_comparison_distinction" in failures


def test_provenance_question_must_state_authority_or_source() -> None:
    failures = _failures(
        "Which provenance authority decides whether the answer is trusted?",
        "The answer is trusted after the row passes cleanly.",
    )

    assert "answer_alignment_missing_authority_or_provenance" in failures


def test_persistence_state_question_must_not_imply_verification() -> None:
    failures = _failures(
        "Does persisted state mean the answer is verified and correct?",
        "Persisted state means the answer is verified and correct.",
    )

    assert "answer_alignment_persistence_implies_verification" in failures


def test_valid_citation_with_missing_required_question_facet_is_rejected() -> None:
    failures = _failures(
        "Compare adaptive planning with static retrieval, including replan responsibility.",
        "Static retrieval selects evidence from the index and cites the selected passage.",
    )

    assert "answer_alignment_missing_comparison_distinction" in failures
    assert "answer_alignment_missing_required_question_facets" in failures


def test_fragmentary_debug_surface_is_rejected_even_with_citation_text() -> None:
    failures = _failures(
        "Explain how Sigma.js and Obsidian differ for human versus AI navigation.",
        "sigma js: graph surface. multi source selection: obsidian note.",
    )

    assert "answer_alignment_debug_surface" in failures


def test_responsive_comparison_answer_passes_alignment_guard() -> None:
    failures = _failures(
        "Compare the host lock and canonical tunnel controls for reliability.",
        (
            "The host lock preserves the runtime identity, whereas the canonical tunnel "
            "keeps traffic routed through the approved production endpoint."
        ),
    )

    assert failures == set()
