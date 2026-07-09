from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_MODULES = (
    ROOT / "src/knowledge_engine/m14_public_contracts.py",
    ROOT / "src/knowledge_engine/m14_source_cards.py",
)
CITATION_MODULES = PUBLIC_MODULES + (
    ROOT / "src/knowledge_engine/m14_citation_evidence.py",
    ROOT / "src/knowledge_engine/m14_citation_runtime.py",
)


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_citation_modules_have_no_network_process_or_storage_clients() -> None:
    forbidden = {
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib.request",
    }
    for path in CITATION_MODULES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
                assert not names & forbidden
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") not in forbidden


def test_public_modules_do_not_expose_snapshot_keys_or_raw_source_content() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in PUBLIC_MODULES)
    forbidden_literals = {
        "snapshot_key",
        "raw_source_body",
        "object_key",
        "cache_path",
        "signed_url",
    }
    for literal in forbidden_literals:
        assert literal not in source


def test_public_response_models_do_not_expose_internal_provenance_records() -> None:
    tree = _tree(ROOT / "src/knowledge_engine/m14_public_contracts.py")
    response_class = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "PublicAskResponse"
    )
    annotations = {
        node.target.id
        for node in response_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert "source_cards" in annotations
    assert "provenance" not in annotations
    assert "retrieval" not in annotations
    assert "evaluation" not in annotations
    assert "manifest_sha256" not in annotations
