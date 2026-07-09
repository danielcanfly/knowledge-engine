from __future__ import annotations

import ast
from pathlib import Path

from knowledge_engine.m14_interfaces import public_ask_widget_javascript

ROOT = Path(__file__).resolve().parents[1]
INTERFACE_MODULE = ROOT / "src/knowledge_engine/m14_interfaces.py"
API_MODULE = ROOT / "src/knowledge_engine/api.py"


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_interface_module_has_no_network_process_or_storage_client() -> None:
    forbidden = {
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib.request",
    }
    for node in ast.walk(_tree(INTERFACE_MODULE)):
        if isinstance(node, ast.Import):
            names = {alias.name for alias in node.names}
            assert not names & forbidden
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "") not in forbidden


def test_widget_has_no_persistent_or_unsafe_rendering_surface() -> None:
    script = public_ask_widget_javascript()
    forbidden = {
        "inner" + "HTML",
        "outer" + "HTML",
        "insertAdjacent" + "HTML",
        "local" + "Storage",
        "session" + "Storage",
        "indexed" + "DB",
        "document" + ".cookie",
        "WebSocket",
        "EventSource",
    }
    assert not {value for value in forbidden if value in script}
    assert "textContent" in script
    assert "credentials: \"same-origin\"" in script
    assert "endpoint.origin !== window.location.origin" in script


def test_json_and_stream_routes_share_one_execution_function() -> None:
    source = API_MODULE.read_text(encoding="utf-8")
    assert "def _execute_public_ask(" in source
    assert source.count("return _execute_public_ask(request, principal)") == 1
    assert source.count("response = _execute_public_ask(request, principal)") == 1
    assert "conversation_id" not in source
    assert "session_store" not in source
    assert "chat_history" not in source


def test_interface_assets_do_not_embed_third_party_hosts() -> None:
    source = INTERFACE_MODULE.read_text(encoding="utf-8")
    assert "cdn." not in source
    assert "fonts.googleapis" not in source
    assert "unpkg" not in source
    assert "jsdelivr" not in source
