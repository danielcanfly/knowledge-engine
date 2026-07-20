from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURITY_MODULE = ROOT / "src/knowledge_engine/m14_security.py"
CONTRACTS_MODULE = ROOT / "src/knowledge_engine/m14_security_contracts.py"
API_MODULE = ROOT / "src/knowledge_engine/api.py"


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_security_modules_have_no_storage_connector_or_process_surface() -> None:
    forbidden_imports = {
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib.request",
    }
    for path in (SECURITY_MODULE, CONTRACTS_MODULE):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
                assert not names & forbidden_imports
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") not in forbidden_imports
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "exec", "eval"}


def test_security_telemetry_has_no_sensitive_request_fields() -> None:
    source = SECURITY_MODULE.read_text(encoding="utf-8")
    telemetry = source.split("def public_rejection_telemetry", 1)[1].split(
        "def _headers",
        1,
    )[0]
    for forbidden in (
        "authorization",
        "bearer",
        "query_text",
        "request_body",
        "client_host",
        "client_key",
        "claims",
    ):
        assert forbidden not in telemetry.lower()


def test_public_edge_paths_do_not_include_internal_control_routes() -> None:
    source = SECURITY_MODULE.read_text(encoding="utf-8")
    public_constants = source.split("PUBLIC_API_PATHS", 1)[1].split(
        "PUBLIC_ASSET_PATHS",
        1,
    )[0]
    assert "/v1/ask" in public_constants
    assert "/v1/search" in public_constants
    assert "/v1/query" not in public_constants
    assert "/v1/releases" not in public_constants


def test_internal_and_release_routes_keep_strong_principal_dependency() -> None:
    source = API_MODULE.read_text(encoding="utf-8")
    current_release = source.split('def current_release(', 1)[1].split(
        'def refresh_release(',
        1,
    )[0]
    refresh = source.split('def refresh_release(', 1)[1].split(
        'def query(',
        1,
    )[0]
    internal_query = source.split('def query(', 1)[1].split(
        'def _execute_public_ask(',
        1,
    )[0]
    assert "Depends(get_principal)" in current_release
    assert "Depends(get_principal)" in refresh
    assert "Depends(get_principal)" in internal_query
    assert "get_public_principal" not in current_release
    assert "get_public_principal" not in refresh
    assert "get_public_principal" not in internal_query


def test_no_wildcard_cors_or_cross_origin_credentials_are_advertised() -> None:
    security_source = SECURITY_MODULE.read_text(encoding="utf-8")
    contracts_source = CONTRACTS_MODULE.read_text(encoding="utf-8")
    assert 'allow-origin", b"*"' not in security_source
    assert "wildcard_origins_allowed: bool = False" in contracts_source
    assert "cross_origin_credentials: bool = False" in contracts_source
    assert 'credentials: "include"' not in contracts_source
