from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    ROOT / "src/knowledge_engine/m13_retention.py",
    ROOT / "src/knowledge_engine/m13_lifecycle_common.py",
    ROOT / "src/knowledge_engine/m13_abandonment.py",
    ROOT / "src/knowledge_engine/m13_supersession.py",
    ROOT / "src/knowledge_engine/m13_rebuild.py",
    ROOT / "src/knowledge_engine/m13_lifecycle_rules.py",
)


def test_m13_4_modules_have_no_destructive_or_network_surface() -> None:
    forbidden_imports = {"boto3", "httpx", "requests", "socket", "subprocess"}
    forbidden_calls = {
        "delete",
        "delete_object",
        "put_object",
        "create_release",
        "promote_release",
        "rollback_release",
    }
    for module in MODULES:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert imported.isdisjoint(forbidden_imports), module
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert calls.isdisjoint(forbidden_calls), module


def test_retention_code_never_sets_physical_delete_permission_true() -> None:
    for module in MODULES:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword):
                continue
            if node.arg != "physical_delete_permitted":
                continue
            assert isinstance(node.value, ast.Constant), module
            assert node.value.value is False, module
