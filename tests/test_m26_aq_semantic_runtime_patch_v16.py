from __future__ import annotations

import subprocess
import sys
import textwrap

from knowledge_engine import m26_aq_semantic_runtime_patch_v2 as patch_v2
from knowledge_engine.m26_aq_semantic_runtime_patch_v2 import (
    _user_visible_internal_reference_leaks,
)


def _run_isolated(code: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_frozen_q06_uses_calibrated_authority_surface_without_absolute_modality() -> None:
    _run_isolated(
        """
        from knowledge_engine import m26_aq_semantic_runtime_patch_v2 as patch_v2
        from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime
        from knowledge_engine.m26_aq_semantic_runtime_patch_v2 import _semantic_answer_text_v2

        patch_v2.install()
        question = (
            "How do state machines and adaptive replanning fit together without giving the "
            "replanner unlimited authority?"
        )
        requirements = runtime._semantic_requirements(question, "complementary_synthesis")
        answer = _semantic_answer_text_v2(question, requirements)

        assert "cannot" not in answer.casefold()
        assert "bypass" not in answer.casefold()
        assert "override" not in answer.casefold()
        assert "state machine" in answer.casefold()
        assert "adaptive replanning" in answer.casefold()
        assert "policy and approval" in answer.casefold()
        assert "rather than expanding" in answer.casefold()
        assert not runtime._visible_semantic_failures(answer, requirements, question)
        """
    )


def test_internal_reference_leak_detector_catches_provider_and_runtime_aliases() -> None:
    answer = (
        "The edge e1 links article_deadbeefcafebabe to article_f00dbabe12345678, "
        "then claim_1 cites m26pa7loc_1234567890abcdef."
    )
    leaks = _user_visible_internal_reference_leaks(answer, "Explain the architecture.", {"e1": {}})

    assert "e1" in leaks
    assert "article_deadbeefcafebabe" in leaks
    assert "article_f00dbabe12345678" in leaks
    assert "claim_1" in leaks
    assert "m26pa7loc_1234567890abcdef" in leaks


def test_internal_reference_leak_detector_preserves_question_supplied_ids() -> None:
    question = "What does article_deadbeefcafebabe and e1 mean in this trace?"
    answer = "article_deadbeefcafebabe is the identifier the question asked about; e1 is too."

    assert _user_visible_internal_reference_leaks(answer, question, {"e1": {}}) == []


def test_runtime_no_longer_has_synthetic_citation_provenance_helper() -> None:
    assert not hasattr(patch_v2, "_citation_ready_repair_evidence")
