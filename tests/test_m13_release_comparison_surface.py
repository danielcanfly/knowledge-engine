from __future__ import annotations

import ast
from pathlib import Path

SOURCE_FILES = (
    Path("src/knowledge_engine/m13_release_inventory.py"),
    Path("src/knowledge_engine/m13_release_comparison.py"),
)


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_m13_5_has_no_network_or_mutation_imports() -> None:
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
        "m13_production_commit",
        "m13_production_mutation",
        "m13_production_permit",
        "m13_production_lease",
        "m13_coordinator_v2",
    }
    for path in SOURCE_FILES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", 1)[0] for alias in node.names}
                assert not roots & forbidden_roots
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module.split(".", 1)[0] not in forbidden_roots
                assert not any(name in module for name in forbidden_internal)


def test_m13_5_never_calls_delete_or_production_mutation_surfaces() -> None:
    forbidden_attributes = {
        "delete",
        "acquire_production_lease",
        "issue_production_permit",
        "commit_production",
        "mutate_production",
        "rollback",
        "append_ledger",
    }
    for path in SOURCE_FILES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_attributes


def test_m13_5_exposes_only_read_only_governance() -> None:
    source = Path("src/knowledge_engine/m13_release_comparison.py").read_text(
        encoding="utf-8"
    )
    assert "GOVERNANCE_NO_WRITE" in source
    assert 'kind="release_comparison"' in source
    assert "requires_production_slot=False" in source
    assert 'artifact_class="evidence"' in source
    assert "release_write_permitted\": True" not in source
    assert "production_write_permitted\": True" not in source
