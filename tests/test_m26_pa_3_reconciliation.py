from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-3-reconciliation.yml"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_value(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def assert_self_digest(value: dict[str, Any]) -> None:
    expected = value["self_sha256"]
    candidate = dict(value)
    candidate["self_sha256"] = ""
    assert sha256_value(candidate) == expected


def test_pa3_acceptance_schema_and_self_digest() -> None:
    acceptance = load(PILOT / "m26-pa-3-acceptance.json")
    schema = load(SCHEMAS / "m26-pa-3-acceptance-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    errors = sorted(
        Draft202012Validator(schema).iter_errors(acceptance),
        key=lambda error: list(error.absolute_path),
    )
    assert errors == []
    assert_self_digest(acceptance)
    assert acceptance["schema_version"] == "knowledge-engine-m26-pa-3-acceptance/v1"
    assert acceptance["stage_id"] == "M26.PA.3"
    assert acceptance["status"] == "m26_pa_3_live_provider_execution_accepted"
    assert acceptance["effective_only_on_reconciliation_merge"] is True


def test_pa3_acceptance_binds_predecessor_and_authorization() -> None:
    acceptance = load(PILOT / "m26-pa-3-acceptance.json")
    authorization = load(PILOT / "m26-pa-3-live-provider-authorization.json")
    assert_self_digest(authorization)
    assert authorization["self_sha256"] == acceptance["live_authorization"][
        "authorization_self_sha256"
    ]
    assert acceptance["issue"] == {
        "number": 1203,
        "repository": "danielcanfly/knowledge-engine",
        "state_before_reconciliation_pr": "open",
        "title": "M26.PA.3 independent live-provider reconciliation",
    }
    assert acceptance["predecessor"] == {
        "pa2_acceptance_self_sha256": (
            "f6f597699390135b0bf7a8e31417c2e8e6f48af2dc2af4168eca1fd1e7f24f67"
        ),
        "pa2_issue_number": 1186,
        "pa2_reconciliation_merge_sha": "8ed2da47d04f6410e55d5855d78f734341aecf2e",
        "pa2_reconciliation_pull_request": 1196,
        "pa2_status": "m26_pa_2_real_corpus_retrieval_binding_accepted",
    }
    assert acceptance["live_authorization"] == {
        "authorization_head_sha": "32cf010cda1c588a757b554ddab103674c5a492b",
        "authorization_merge_sha": "3bac0c44e62341322901e8fa7d2503a68ca04b6e",
        "authorization_pull_request": 1201,
        "authorization_self_sha256": (
            "81053fe45f14eb76bd908770f79a9d01fe6750614d05723d71ed1f0358edd6e6"
        ),
        "credential_name": "MINIMAX_API_KEY",
        "expected_head_merge": True,
        "logical_attempt": 4,
        "model_id": "MiniMax-M3",
        "provider_id": "minimax",
        "source_issue_number": 1197,
        "trigger_marker": "[m26.pa3-provider-authorized-attempt-4]",
        "workflow_name": "M26.PA.3 Live Provider Execution Gate",
    }


def test_pa3_acceptance_binds_remote_live_artifact_identity() -> None:
    acceptance = load(PILOT / "m26-pa-3-acceptance.json")
    assert acceptance["live_evidence"] == {
        "artifact_archive_digest": (
            "sha256:09c685bdd1a4ad59d98b1f95eaa6d1c137a57ce873ccc9a184e130056051533d"
        ),
        "artifact_entry_names": [
            "m26-pa-3-live-provider-receipt.json",
            "m26-pa-3-live-provider-receipt.sha256",
            "status.txt",
        ],
        "artifact_expires_at": "2026-08-26T18:47:54Z",
        "artifact_id": 8664397892,
        "artifact_name": "m26-pa-3-live-provider-evidence-attempt-4",
        "artifact_size_in_bytes": 1514,
        "created_at": "2026-07-27T18:47:55Z",
        "live_provider_job_conclusion": "success",
        "live_provider_job_id": 90074887677,
        "receipt_file_sha256": (
            "9fc30e5d4cb79aadfa7cd3ab03083197931e2d7cc5481d6104b86a40d2ed7352"
        ),
        "receipt_schema_version": "knowledge-engine-m26-pa-3-live-provider-receipt/v1",
        "receipt_self_sha256": (
            "eca49a290d587449b9c3d0dc369ac7893890bc83767a983abd097bce7adecec2"
        ),
        "receipt_sha256_file_value": (
            "9fc30e5d4cb79aadfa7cd3ab03083197931e2d7cc5481d6104b86a40d2ed7352"
        ),
        "receipt_status": "live_provider_execution_verified",
        "run_attempt": 1,
        "run_event": "push",
        "run_id": 30295355209,
        "run_number": 9,
        "status_file_value": "success",
        "workflow_head_sha": "3bac0c44e62341322901e8fa7d2503a68ca04b6e",
        "workflow_name": "M26.PA.3 Live Provider Execution Gate",
    }


def test_pa3_acceptance_keeps_all_downstream_authority_closed() -> None:
    acceptance = load(PILOT / "m26-pa-3-acceptance.json")
    assert acceptance["receipt_authority"] == {
        "credential_names": ["MINIMAX_API_KEY"],
        "provider_calls": 1,
        "public_shadow_canary_traffic_operations": 0,
        "qdrant_write_operations": 0,
        "r2_write_operations": 0,
        "raw_text_persisted": False,
        "secret_values_persisted": False,
        "source_foundation_release_mutations": 0,
        "vectors_requested": False,
        "vectors_returned": False,
    }
    assert not any(acceptance["authority_boundary"].values())
    assert acceptance["request_privacy"] == {
        "max_output_tokens": 256,
        "payload_sha256": "4e6fecd7f8cb8ad92c8cd925c85e68d7c218eb51ac2a1fe6390a285a5c6eb949",
        "prompt_bytes": 1511,
        "raw_corpus_text_sent": False,
        "stream": False,
        "user_query_sent": False,
        "vectors_sent": False,
    }
    assert acceptance["usage"] == {
        "input_tokens": 652,
        "output_tokens": 104,
        "total_tokens": 756,
    }
    assert acceptance["next_stage"] == {
        "authorized": True,
        "daniel_pa4_gate_required": True,
        "name": "Real Verified Answer and Citation Gate",
        "predecessor_status_required": "m26_pa_3_live_provider_execution_accepted",
        "production_answer_serving_permitted": False,
        "public_shadow_canary_traffic_permitted": False,
        "stage_id": "M26.PA.4",
    }


def test_pa3_reconciliation_doc_and_workflow_are_bounded() -> None:
    doc = (DOCS / "m26-pa-3-reconciliation.md").read_text(encoding="utf-8")
    assert "m26_pa_3_live_provider_execution_accepted" in doc
    assert "30295355209" in doc
    assert "8664397892" in doc
    assert "MiniMax-M3" in doc
    assert "does not authorize another provider call" in doc
    assert "Daniel's exact quality threshold" in doc

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "actions: read" in workflow
    assert "pull-requests: read" in workflow
    assert "issues: read" in workflow
    assert "contents: write" not in workflow
    assert "m26-pa-3-live-provider-evidence-attempt-4" in workflow
    assert "MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}" not in workflow
    assert "Execute exact bounded MiniMax M3 provider call" not in workflow
