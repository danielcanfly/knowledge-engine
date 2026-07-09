from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    ROOT / "src/knowledge_engine/m13_coordination_common.py",
    ROOT / "src/knowledge_engine/m13_candidate_coordinator.py",
    ROOT / "src/knowledge_engine/m13_production_lease.py",
    ROOT / "src/knowledge_engine/m13_production_permit.py",
    ROOT / "src/knowledge_engine/m13_production_commit.py",
    ROOT / "src/knowledge_engine/m13_production_mutation.py",
    ROOT / "src/knowledge_engine/m13_coordinator_v2.py",
)


def test_all_coordinator_modules_exclude_network_and_direct_release_mutation() -> None:
    forbidden_imports = {"boto3", "httpx", "requests", "socket", "subprocess"}
    forbidden_calls = {
        "create_release",
        "promote_release",
        "rollback_release",
        "delete",
        "delete_object",
        "put_object",
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
