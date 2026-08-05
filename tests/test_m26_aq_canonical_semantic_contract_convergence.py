from __future__ import annotations

import subprocess
import sys
import textwrap


EXPECTED_ENTRYPOINT = "knowledge_engine.m26_aq_semantic_contract.run_owner_arbitrary_query"


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
