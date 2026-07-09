from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_MODULES = (
    ROOT / "src/knowledge_engine/m14_feedback.py",
    ROOT / "src/knowledge_engine/m14_feedback_contracts.py",
    ROOT / "src/knowledge_engine/m14_feedback_edge.py",
    ROOT / "src/knowledge_engine/m14_feedback_widget.py",
)


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_feedback_modules_have_no_network_process_or_source_clients() -> None:
    forbidden = {
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib.request",
    }
    for path in FEEDBACK_MODULES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
                assert not names & forbidden
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") not in forbidden
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {
                    "delete",
                    "delete_object",
                    "create_pull_request",
                    "merge_pull_request",
                }


def test_feedback_contract_does_not_collect_raw_answer_or_contact_identity() -> None:
    source = (
        ROOT / "src/knowledge_engine/m14_feedback_contracts.py"
    ).read_text(encoding="utf-8")
    request_class = next(
        node
        for node in ast.walk(_tree(FEEDBACK_MODULES[1]))
        if isinstance(node, ast.ClassDef) and node.name == "PublicFeedbackRequest"
    )
    annotations = {
        node.target.id
        for node in request_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert "request_id" in annotations
    assert "release_id" in annotations
    assert "feedback_type" in annotations
    for forbidden in (
        "query",
        "answer",
        "email",
        "name",
        "phone",
        "contact",
        "metadata",
        "attachment",
    ):
        assert forbidden not in annotations
    assert 'extra="forbid"' in source


def test_feedback_records_cannot_authorize_source_or_production_writes() -> None:
    source = (ROOT / "src/knowledge_engine/m14_feedback.py").read_text(
        encoding="utf-8"
    )
    assert '"source_write_allowed": False' in source
    assert '"candidate_dispatch_allowed": False' in source
    assert '"production_write_allowed": False' in source
    assert '"ledger_append_allowed": False' in source
    assert '"pending_review"' in source
    assert 'only_if_absent=True' in source
    assert "Source package" not in source


def test_feedback_receipt_exposes_no_object_or_submitter_identity() -> None:
    source = (
        ROOT / "src/knowledge_engine/m14_feedback_contracts.py"
    ).read_text(encoding="utf-8")
    receipt_class = next(
        node
        for node in ast.walk(_tree(FEEDBACK_MODULES[1]))
        if isinstance(node, ast.ClassDef) and node.name == "PublicFeedbackReceipt"
    )
    annotations = {
        node.target.id
        for node in receipt_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert "feedback_id" in annotations
    assert "curation_status" in annotations
    for forbidden in (
        "intake_key",
        "queue_key",
        "submitter_scope_sha256",
        "identity_sha256",
        "client_key",
    ):
        assert forbidden not in annotations
    assert "source_write_performed: bool = False" in source
    assert "production_write_performed: bool = False" in source


def test_widget_feedback_payload_excludes_query_and_answer() -> None:
    source = (
        ROOT / "src/knowledge_engine/m14_feedback_widget.py"
    ).read_text(encoding="utf-8")
    assert "feedback_type: type" in source
    assert "request_id: state.meta.request_id" in source
    assert "release_id: state.meta.release_id" in source
    assert "body.query" not in source
    assert "body.answer" not in source
    assert 'credentials: endpoint.origin === window.location.origin' in source
    assert '? "same-origin"' in source
    assert ': "omit"' in source
