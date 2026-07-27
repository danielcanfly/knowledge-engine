from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
DOCS = ROOT / "docs" / "architecture" / "m26"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-2-reconciliation.yml"
NON_LIVE_WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-2-real-corpus-binding.yml"
LIVE_READ_WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-2-live-read-evidence.yml"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_pa2_acceptance_status_and_self_digest() -> None:
    acceptance = load(PILOT / "m26-pa-2-acceptance.json")
    expected = acceptance["self_sha256"]
    candidate = dict(acceptance)
    candidate["self_sha256"] = ""
    assert hashlib.sha256(canonical_bytes(candidate)).hexdigest() == expected
    assert expected == "f6f597699390135b0bf7a8e31417c2e8e6f48af2dc2af4168eca1fd1e7f24f67"
    assert acceptance["schema_version"] == "knowledge-engine-m26-pa-2-acceptance/v1"
    assert acceptance["status"] == "m26_pa_2_real_corpus_retrieval_binding_accepted"
    assert acceptance["stage_id"] == "M26.PA.2"
    assert acceptance["effective_only_on_reconciliation_merge"] is True


def test_pa2_acceptance_binds_predecessors_and_implementation() -> None:
    acceptance = load(PILOT / "m26-pa-2-acceptance.json")
    assert acceptance["predecessors"] == {
        "g0_main_seal_sha": "728df7da4e6b9320c25abb904a65a32b15e62bb1",
        "g0_status": "m26_g0_milestone_reconciliation_accepted",
        "m25_final_reconciliation_merge_sha": "4d7e661a21397ba5c88ba7160f3d0be3bd45cee3",
        "m25_final_reconciliation_self_sha256": (
            "e1f12ca7159dbcfbe4236108055f0582d951a76f16be9c9d6f35392dc74c5d3d"
        ),
        "m25_status": "m25_closed",
        "pa1_status": "m26_pa_1_production_activation_authority_freeze_accepted",
    }
    assert acceptance["implementation"] == {
        "additions": 3417,
        "base_sha": "728df7da4e6b9320c25abb904a65a32b15e62bb1",
        "changed_file_count": 12,
        "deletions": 1,
        "expected_head_merge": True,
        "final_head_sha": "11db7672f0a24c4531ac0203ca89e2c4d0a6e975",
        "issue_number": 1186,
        "merge_sha": "ecad7b2bfb2e6d472bf0ed76d2e0adc818124dd9",
        "pull_request_number": 1187,
        "unresolved_review_thread_count": 0,
    }
    assert acceptance["issue"] == {
        "number": 1186,
        "repository": "danielcanfly/knowledge-engine",
        "state_after_reconciliation_merge": "closed",
        "state_before_reconciliation_pr": "open",
        "state_reason_after_reconciliation_merge": "completed",
    }


def test_pa2_acceptance_binds_live_authorization_and_evidence() -> None:
    acceptance = load(PILOT / "m26-pa-2-acceptance.json")
    assert acceptance["live_authorization"] == {
        "authorization_self_sha256": (
            "1db8a863205228c29d1f93a33b6344c5f7ef157c54ac64b09589c13b48a860bd"
        ),
        "changed_file_count": 6,
        "final_head_sha": "72e6dd2de3b78383195a4c861b244b12134e2cb4",
        "logical_attempt": 6,
        "merge_sha": "4d6e5ec166ee98276f494efb7d522b444aad87b8",
        "pull_request_number": 1195,
        "trigger_marker": "[m26.pa2-live-authorized-attempt-6]",
    }
    assert acceptance["live_evidence"] == {
        "artifact_archive_digest": (
            "sha256:dc32791ff15764f0c014af453c16be539c116f3bd13de7d82fca7ef403010520"
        ),
        "artifact_expires_at": "2026-10-25T10:55:49Z",
        "artifact_id": 8650470968,
        "artifact_name": "m26-pa-2-live-read-only-evidence-attempt-6",
        "artifact_retention_days": 90,
        "artifact_size_in_bytes": 4634,
        "generated_at": "2026-07-27T10:56:12Z",
        "head_sha": "4d6e5ec166ee98276f494efb7d522b444aad87b8",
        "job_id": 89957254566,
        "receipt_self_sha256": "389e31e91c265f29bafe0fa54274228d5fa5b7e842ea3bccb60de625d91936e9",
        "receipt_sha256": "65320ad967faccc5ca38d55db5f16744b9071580fa19128ea06c4cd8941bf8d0",
        "run_attempt": 1,
        "run_id": 30259956089,
        "run_number": 18,
        "status": "real_corpus_retrieval_binding_verified",
        "workflow_name": "M26.PA.2 Exact Live Read-Only Evidence",
    }


def test_pa2_receipt_summary_and_authority_boundary() -> None:
    acceptance = load(PILOT / "m26-pa-2-acceptance.json")
    authority = acceptance["receipt"]["authority"]
    assert authority["r2_read_operations"] == 2
    assert authority["qdrant_count_operations"] == 1
    assert authority["qdrant_scroll_operations"] == 17
    assert authority["qdrant_transport_attempts"] == 18
    assert authority["read_only_credentials_verified"] is True
    forbidden_counts = (
        "r2_write_operations",
        "qdrant_write_operations",
        "production_pointer_mutations",
        "provider_calls",
        "answer_generation_operations",
        "public_shadow_canary_traffic_operations",
    )
    assert all(authority[key] == 0 for key in forbidden_counts)
    assert authority["raw_text_persisted"] is False
    assert authority["secrets_persisted"] is False
    assert authority["vectors_requested"] is False
    assert authority["vectors_returned"] is False

    boundary = acceptance["authority_boundary"]
    assert boundary["real_corpus_retrieval_binding"] is True
    assert boundary["r2_read_only_get"] is True
    assert boundary["qdrant_read_only_count_scroll"] is True
    forbidden_true = {
        key: value
        for key, value in boundary.items()
        if key
        not in {
            "real_corpus_retrieval_binding",
            "r2_read_only_get",
            "qdrant_read_only_count_scroll",
        }
    }
    assert not any(forbidden_true.values())


def test_pa2_production_qdrant_and_sample_identities() -> None:
    receipt = load(PILOT / "m26-pa-2-acceptance.json")["receipt"]
    assert receipt["release"] == {
        "admission_sha256": "f5f01d82c7a1a38cf15fc54c890b904c4c015f608e2d25e294f9469f9b1927f2",
        "artifact_count": 8,
        "artifact_inventory_sha256": (
            "3ca8800576c6a3282667eb2e2276c210ffe4a773d235cb72a8eaa1bb2fade8a0"
        ),
        "engine_sha": "fe499db2e043209bfa4c2390d513c5dc579727a2",
        "foundation_sha": "e53af5833193a644a4d7397b7d466ababb5e1373",
        "manifest_key": (
            "releases/m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043/"
            "promotion/m25-10-production-manifest.json"
        ),
        "manifest_sha256": "72bb03e3fa22e453735719ab43898adfd4c7f186f818ed71685efb4fcd87de2b",
        "pointer_key": "channels/production.json",
        "pointer_sha256": "4a2cf8cc16d598cc2c6928491cf2c3b926e57e571297c61a8c3ff7a4ae396ff9",
        "release_id": "m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043",
        "source_sha": "5250f8422f4fa08c1f3dc84840dc756850817635",
    }
    qdrant = receipt["qdrant"]
    assert qdrant["collection"] == (
        "m25_blog_m25blog_5250f8422f4f_f5f01d82c7a1_fe499db2e043_fe499db2e043"
    )
    assert qdrant["expected_point_count"] == 4197
    assert qdrant["observed_point_count"] == 4197
    assert qdrant["page_count"] == 17
    assert qdrant["sample_size"] == 5
    assert qdrant["sample_sha256"] == (
        "c0c505c1bcaf3e37a9cd58a1e5ad33fdb6b357b4a00a5c1903a7512e76fdaf21"
    )
    assert qdrant["with_vector"] is False


def test_pa2_reconciliation_unlocks_pa3_without_provider_authority() -> None:
    acceptance = load(PILOT / "m26-pa-2-acceptance.json")
    assert all(acceptance["reconciliation"].values())
    assert acceptance["prior_attempts"]["all_failed_or_skipped_runs_forbidden_to_rerun"] is True
    assert acceptance["prior_attempts"]["successful_logical_attempt"] == 6
    assert acceptance["next_stage"] == {
        "authorized": True,
        "daniel_provider_gate_required": True,
        "issue_and_branch_permitted_after_this_merge": True,
        "live_provider_calls_permitted_by_this_reconciliation": False,
        "name": "Live Provider Execution",
        "predecessor_status_required": "m26_pa_2_real_corpus_retrieval_binding_accepted",
        "production_answer_serving_permitted": False,
        "production_pointer_mutation_permitted": False,
        "public_shadow_canary_traffic_permitted": False,
        "stage_id": "M26.PA.3",
    }
    assert all(acceptance["residual_risks"].values())


def test_reconciliation_doc_and_workflow_are_bounded() -> None:
    doc = (DOCS / "m26-pa-2-reconciliation.md").read_text(encoding="utf-8")
    assert "m26_pa_2_real_corpus_retrieval_binding_accepted" in doc
    assert "30259956089" in doc
    assert "8650470968" in doc
    assert "M26.PA.3" in doc
    assert "does not authorize a provider call by itself" in doc

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "actions: read" in text
    assert "pull-requests: read" in text
    assert "issues: read" in text
    assert "contents: write" not in text
    assert "issues: write" not in text
    assert "secrets." not in text
    assert "environment: m23-r3-diagnostic" not in text
    non_live_text = NON_LIVE_WORKFLOW.read_text(encoding="utf-8")
    assert "expected-reconciliation.txt" in non_live_text
    assert ".github/workflows/m26-pa-2-reconciliation.yml" in non_live_text
    assert "tests/test_m26_pa_2_reconciliation.py" in non_live_text
    live_read_text = LIVE_READ_WORKFLOW.read_text(encoding="utf-8")
    assert "expected-reconciliation.txt" in live_read_text
    assert ".github/workflows/m26-pa-2-reconciliation.yml" in live_read_text
    assert "tests/test_m26_pa_2_reconciliation.py" in live_read_text
    for forbidden in (
        "QDRANT_READ_ONLY_" + "API_" + "KEY:",
        "R2_ACCESS_KEY_ID_READ:",
        "R2_SECRET_ACCESS_KEY_READ:",
        "workflow_dispatch",
        "put_object",
        "delete_object",
        "upsert",
        "curl -X",
    ):
        assert forbidden not in text
