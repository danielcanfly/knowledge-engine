from __future__ import annotations

import subprocess

EXPECTED_ENTRYPOINT = "knowledge_engine.m26_aq_semantic_contract.run_owner_arbitrary_query"


def _assert_import_order(code: str) -> None:
    result = subprocess.run(
        ["python", "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_docker_has_one_canonical_production_app() -> None:
    dockerfile = _read("Dockerfile")
    assert "knowledge_engine.m26_production_api:app" in dockerfile
    assert dockerfile.count("knowledge_engine.m26_production_api:app") == 1


def test_production_runtime_identity_survives_core_api_preimport() -> None:
    _assert_import_order(
        "import knowledge_engine.api as core; "
        "import knowledge_engine.m26_production_api as prod; "
        "import knowledge_engine.m26_ask_api as ask; "
        "import knowledge_engine.m26_aq_semantic_contract as semantic; "
        f"assert ask.RUNTIME_ENTRYPOINT == {EXPECTED_ENTRYPOINT!r}; "
        "assert ask.run_owner_arbitrary_query is semantic.run_owner_arbitrary_query; "
        "assert prod.app is core.app"
    )


def test_production_runtime_identity_survives_wrapper_first_import() -> None:
    _assert_import_order(
        "import knowledge_engine.m26_production_api as prod; "
        "import knowledge_engine.api as core; "
        "import knowledge_engine.m26_ask_api as ask; "
        "import knowledge_engine.m26_aq_semantic_contract as semantic; "
        f"assert ask.RUNTIME_ENTRYPOINT == {EXPECTED_ENTRYPOINT!r}; "
        "assert ask.run_owner_arbitrary_query is semantic.run_owner_arbitrary_query; "
        "assert prod.app is core.app"
    )


def test_production_wrapper_does_not_install_aq_patch_stack() -> None:
    _assert_import_order(
        "import knowledge_engine.m26_production_api; "
        "import knowledge_engine.m26_aq_final_universal_recovery_patch as final_patch; "
        "import knowledge_engine.m26_aq_semantic_runtime_patch_v3 as v3; "
        "import knowledge_engine.m26_pa7_arbitrary_query_runtime as legacy; "
        "assert not getattr(legacy._intent_class, final_patch._FINAL_MARKER, False); "
        "assert not getattr(legacy._direct_question_facets, final_patch._FINAL_MARKER, False); "
        "assert not getattr(v3._generalized_provider_synthesize, final_patch._FINAL_MARKER, False)"
    )


def test_production_wrapper_declares_canonical_runtime_binding() -> None:
    source = _read("src/knowledge_engine/m26_production_api.py")
    assert "CANONICAL_RUNTIME_ENTRYPOINT" in source
    assert "m26_ask_api.run_owner_arbitrary_query = run_owner_arbitrary_query" in source
    assert "m26_ask_api.RUNTIME_ENTRYPOINT = CANONICAL_RUNTIME_ENTRYPOINT" in source
    assert "from .api import app" in source
    assert "install_aq_lifecycle_runtime_patch()" not in source
    assert "install_aq_surface_runtime_patch()" not in source
    assert "install_aq_final_universal_recovery_patch" not in source
    assert "force_rebind" not in source
    assert "legacy_runtime._" not in source
    assert "semantic_runtime._" not in source
