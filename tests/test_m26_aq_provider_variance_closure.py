from __future__ import annotations

import subprocess
import sys
import textwrap


def _run_isolated(code: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_production_wrapper_no_longer_exports_variance_patch_helpers() -> None:
    _run_isolated(
        """
        import knowledge_engine.m26_ask_api as ask_api
        import knowledge_engine.m26_pa7_semantic_closure_runtime as semantic_runtime
        import knowledge_engine.m26_production_api as production

        assert ask_api.RUNTIME_ENTRYPOINT == (
            "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
        )
        assert ask_api.run_owner_arbitrary_query is semantic_runtime.run_owner_arbitrary_query
        for name in (
            "_question_contract_without_progress_substring_false_positive",
            "_production_variance_semantic_requirements",
            "_production_variance_semantic_answer_text",
            "_production_variance_repair_guidance",
            "_synthesize_with_bounded_provider_variance_repair",
            "_production_semantic_synthesize",
        ):
            assert not hasattr(production, name), name
        """
    )


def test_explicit_semantic_patch_install_isolated_from_production_wrapper() -> None:
    _run_isolated(
        """
        from knowledge_engine import m26_aq_semantic_runtime_patch_v2 as patch_v2
        from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime
        import knowledge_engine.m26_production_api as production

        patch_v2.install()
        requirements = runtime._semantic_requirements(
            "How should a governed investigation handle source selection and verification?",
            "complementary_synthesis",
        )
        assert isinstance(requirements, list)
        assert not hasattr(production, "_production_semantic_synthesize")
        assert not hasattr(production, "_production_variance_semantic_requirements")
        """
    )


def test_patch_repair_verifier_shape_remains_hard_bound() -> None:
    _run_isolated(
        """
        from knowledge_engine.m26_aq_semantic_runtime_patch_v2 import (
            _repairable_verifier_failure,
            _runtime_bound_semantic_repair_v2,
        )

        assert _repairable_verifier_failure("M26-PA7-ME-029")
        assert _repairable_verifier_failure("M26-PA7-ME-030")
        assert _repairable_verifier_failure("M26-PA7-ME-034")
        assert not _repairable_verifier_failure("M26-PA7-ME-007")
        code = _runtime_bound_semantic_repair_v2.__code__
        assert "_verify_multi_evidence_provider_output" in code.co_names
        assert "_verified_multi_evidence_answer" in code.co_names
        assert "_verified_repair_support_items" in code.co_names
        """
    )
