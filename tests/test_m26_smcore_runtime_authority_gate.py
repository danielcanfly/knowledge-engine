from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "knowledge_engine.m26_aq_semantic_contract.run_owner_arbitrary_query"
LEGACY_MODULE = "m26_pa7_arbitrary_query_runtime"


def _python_files() -> list[Path]:
    return sorted(
        [* (ROOT / "src").rglob("*.py"), *(ROOT / "scripts").rglob("*.py")]
    )


def test_product_and_qualification_callers_use_single_runtime_authority() -> None:
    violations: list[str] = []
    for path in _python_files():
        if path.name == "m26_pa7_arbitrary_query_runtime.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.endswith(LEGACY_MODULE) and any(
                    alias.name == "run_owner_arbitrary_query" for alias in node.names
                ):
                    violations.append(f"{path}: legacy import")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr != "run_owner_arbitrary_query":
                    continue
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "legacy":
                    violations.append(f"{path}:{node.lineno}: legacy call")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "import_module" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and LEGACY_MODULE in str(arg.value):
                        violations.append(f"{path}:{node.lineno}: legacy dynamic import")
    assert not violations, f"stale arbitrary-query authority callers: {violations}"


def test_canonical_runtime_contract_is_provider_neutral() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        CANONICAL_RUNTIME_ENTRYPOINT,
        PROVIDER_NEUTRAL_DOWNSTREAM_STAGES,
        runtime_contract_identity,
    )

    identity = runtime_contract_identity()
    assert identity["entrypoint"] == CANONICAL_RUNTIME_ENTRYPOINT
    assert identity["runtime_contract_fingerprint"]
    assert tuple(identity["downstream_stage_identity"]) == PROVIDER_NEUTRAL_DOWNSTREAM_STAGES
    assert len(PROVIDER_NEUTRAL_DOWNSTREAM_STAGES) >= 8
