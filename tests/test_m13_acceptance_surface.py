from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/knowledge_engine/m13_acceptance.py"
SCRIPT = ROOT / "scripts/m13_three_batch_acceptance.py"


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_acceptance_has_no_network_shell_or_github_surface() -> None:
    forbidden_roots = {
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    for path in (MODULE, SCRIPT):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", 1)[0] for alias in node.names}
                assert not roots & forbidden_roots
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".", 1)[0]
                assert root not in forbidden_roots
                assert "github" not in (node.module or "").lower()


def test_acceptance_never_deletes_rolls_back_or_appends_ledger() -> None:
    forbidden_calls = {
        "append_ledger",
        "delete",
        "rollback_release",
    }
    for node in ast.walk(_tree(MODULE)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "delete":
                assert isinstance(node.func.value, ast.Name)
                assert node.func.value.id == "isolated"
            else:
                assert node.func.attr not in forbidden_calls
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden_calls


def test_acceptance_core_is_isolated_and_governance_is_explicit() -> None:
    source = MODULE.read_text(encoding="utf-8")
    assert "M13_ACCEPTANCE_ISOLATION_REQUIRED" in source
    assert "isinstance(store, IsolatedObjectStore)" in source
    assert '"real_production_write_performed": False' in source
    assert '"canonical_source_write_performed": False' in source
    assert '"permanent_ledger_append_performed": False' in source
    assert '"rollback_performed": False' in source
    assert '"physical_delete_performed": False' in source
    assert "run_three_batch_acceptance" not in {
        node.name
        for node in ast.walk(_tree(MODULE))
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
