from __future__ import annotations

import subprocess
import sys
from pathlib import Path


EXPECTED_ENTRYPOINT = (
    "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
)


def _assert_import_order(code: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_docker_has_one_canonical_production_app() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "knowledge_engine.m26_production_api:app" in dockerfile
    assert dockerfile.count("knowledge_engine.m26_production_api:app") == 1


def test_production_runtime_identity_survives_core_api_preimport() -> None:
    _assert_import_order(
        "import knowledge_engine.api as core; "
        "import knowledge_engine.m26_production_api as prod; "
        "import knowledge_engine.m26_ask_api as ask; "
        "import knowledge_engine.m26_pa7_semantic_closure_runtime as semantic; "
        f"assert ask.RUNTIME_ENTRYPOINT == {EXPECTED_ENTRYPOINT!r}; "
        "assert ask.run_owner_arbitrary_query is semantic.run_owner_arbitrary_query; "
        "assert prod.app is core.app"
    )


def test_production_runtime_identity_survives_wrapper_first_import() -> None:
    _assert_import_order(
        "import knowledge_engine.m26_production_api as prod; "
        "import knowledge_engine.api as core; "
        "import knowledge_engine.m26_ask_api as ask; "
        "import knowledge_engine.m26_pa7_semantic_closure_runtime as semantic; "
        f"assert ask.RUNTIME_ENTRYPOINT == {EXPECTED_ENTRYPOINT!r}; "
        "assert ask.run_owner_arbitrary_query is semantic.run_owner_arbitrary_query; "
        "assert prod.app is core.app"
    )


def test_production_wrapper_declares_bounded_compatibility_layer() -> None:
    source = Path("src/knowledge_engine/m26_production_api.py").read_text(encoding="utf-8")
    assert "classify_with_semantic_compat" in source
    assert "run_owner_arbitrary_query" in source
    assert "m26_ask_api.RUNTIME_ENTRYPOINT" in source
    assert "from .api import app" in source
