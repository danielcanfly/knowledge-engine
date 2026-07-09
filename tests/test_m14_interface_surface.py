from __future__ import annotations

import ast
from pathlib import Path

from knowledge_engine import api

ROOT = Path(__file__).resolve().parents[1]
INTERFACE_MODULE = ROOT / "src/knowledge_engine/m14_interfaces.py"
SECURITY_MODULE = ROOT / "src/knowledge_engine/m14_security.py"
API_MODULE = ROOT / "src/knowledge_engine/api.py"


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_interface_and_security_modules_have_no_remote_clients() -> None:
    forbidden = {
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib.request",
    }
    for path in (INTERFACE_MODULE, SECURITY_MODULE):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
                assert not names & forbidden
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") not in forbidden


def test_served_widget_has_no_persistent_or_unsafe_rendering_surface() -> None:
    script = api.ask_widget_script().body.decode("utf-8")
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
    assert 'endpoint.origin === window.location.origin' in script
    assert '? "same-origin"' in script
    assert ': "omit"' in script
    assert "cross-origin endpoint is disabled" not in script


def test_json_and_stream_routes_share_one_execution_function() -> None:
    source = API_MODULE.read_text(encoding="utf-8")
    assert "def _execute_public_ask(" in source
    assert "lambda: ask(request, identity.principal)" in source
    assert "lambda: ask_stream(request, identity.principal)" in source
    assert "conversation_id" not in source
    assert "session_store" not in source
    assert "chat_history" not in source


def test_interface_assets_do_not_embed_third_party_hosts() -> None:
    source = INTERFACE_MODULE.read_text(encoding="utf-8")
    assert "cdn." not in source
    assert "fonts.googleapis" not in source
    assert "unpkg" not in source
    assert "jsdelivr" not in source
