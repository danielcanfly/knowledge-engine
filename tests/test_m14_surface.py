from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    ROOT / "src/knowledge_engine/m14_public_contracts.py",
    ROOT / "src/knowledge_engine/m14_retrieval.py",
    ROOT / "src/knowledge_engine/m14_section_index.py",
)


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_m14_query_modules_have_no_network_or_process_surface() -> None:
    forbidden = {
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib.request",
    }
    for path in MODULES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
                assert not names & forbidden
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") not in forbidden


def test_retrieval_cannot_enable_raw_fallback() -> None:
    source = (
        ROOT / "src/knowledge_engine/m14_retrieval.py"
    ).read_text(encoding="utf-8")
    assert '"raw_fallback_allowed": False' in source
    assert '"raw_fallback_used": False' in source
    assert '"disabled_by_governance"' in source
    assert "raw_fallback_allowed=True" not in source
    assert "raw_fallback_used=True" not in source


def test_public_contract_does_not_expose_internal_runtime_payloads() -> None:
    source = (
        ROOT / "src/knowledge_engine/m14_public_contracts.py"
    ).read_text(encoding="utf-8")
    public_fields = {
        "answer",
        "status",
        "citations",
        "concept_ids",
        "release_id",
        "request_id",
        "audience",
        "confidence",
        "not_found_reason",
    }
    for field in public_fields:
        assert field in source
    response_class = next(
        node
        for node in ast.walk(_tree(MODULES[0]))
        if isinstance(node, ast.ClassDef) and node.name == "PublicAskResponse"
    )
    annotations = {
        node.target.id
        for node in response_class.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
    }
    assert "retrieval" not in annotations
    assert "evaluation" not in annotations
    assert "manifest_sha256" not in annotations
