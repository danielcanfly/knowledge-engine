from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    ROOT / "src/knowledge_engine/m13_operator.py",
    ROOT / "src/knowledge_engine/m13_closeout.py",
    ROOT / "src/knowledge_engine/m13_cli.py",
)


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_m13_6_has_no_network_or_external_process_surface() -> None:
    forbidden_roots = {
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    forbidden_internal = {
        "promotion",
        "m13_production_commit",
        "m13_production_mutation",
        "m13_production_permit",
        "m13_production_lease",
    }
    for path in MODULES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", 1)[0] for alias in node.names}
                assert not roots & forbidden_roots
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module.split(".", 1)[0] not in forbidden_roots
                assert not any(name in module for name in forbidden_internal)


def test_m13_6_never_calls_delete_rollback_or_production_mutation() -> None:
    forbidden_attributes = {
        "delete",
        "promote_release",
        "rollback_release",
        "acquire_production_lease",
        "issue_production_mutation_permit",
        "authorize_production_commit",
        "complete_production_mutation",
        "append_ledger",
    }
    for path in MODULES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_attributes
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_attributes


def test_m13_6_declares_no_write_and_no_ledger_append() -> None:
    operator_source = (ROOT / "src/knowledge_engine/m13_operator.py").read_text(
        encoding="utf-8"
    )
    closeout_source = (ROOT / "src/knowledge_engine/m13_closeout.py").read_text(
        encoding="utf-8"
    )
    assert "GOVERNANCE_NO_WRITE" in operator_source
    assert "GOVERNANCE_NO_WRITE" in closeout_source
    assert '"ledger_append_performed": False' in closeout_source
    assert '"production_write_performed": False' in closeout_source
    assert '"source_write_performed": False' in closeout_source
    assert "permanent_ledger_append_permitted\": True" not in operator_source
    assert "permanent_ledger_append_permitted\": True" not in closeout_source
