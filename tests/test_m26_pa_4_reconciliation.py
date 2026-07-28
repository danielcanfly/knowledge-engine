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
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-4-reconciliation.yml"


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


def test_pa4_acceptance_schema_and_self_digest() -> None:
    acceptance = load(PILOT / "m26-pa-4-acceptance.json")
    schema = load(SCHEMAS / "m26-pa-4-acceptance-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    errors = sorted(
        Draft202012Validator(schema).iter_errors(acceptance),
        key=lambda error: list(error.absolute_path),
    )
    assert errors == []
    assert_self_digest(acceptance)
    assert acceptance["schema_version"] == "knowledge-engine-m26-pa-4-acceptance/v1"
    assert acceptance["stage_id"] == "M26.PA.4"
    assert acceptance["status"] == "m26_pa_4_verified_answer_citation_gate_accepted"
    assert acceptance["effective_only_on_reconciliation_merge"] is True


def test_pa4_acceptance_binds_implementation_and_authorization() -> None:
    acceptance = load(PILOT / "m26-pa-4-acceptance.json")
    assert acceptance["issue"] == {
        "number": 1210,
        "repository": "danielcanfly/knowledge-engine",
        "state_before_reconciliation_pr": "open",
        "title": "M26.PA.4 attempt-2 independent reconciliation",
    }
    assert acceptance["predecessor"] == {
        "pa3_acceptance_self_sha256": (
            "a895104a04724fe64a85380d8a83f7382d332fde707eb06e335cd1c2c8067e83"
        ),
        "pa3_reconciliation_merge_sha": "ae130666813ec30f082020c89c02a75384d5068e",
        "pa3_reconciliation_pull_request": 1204,
        "pa3_status": "m26_pa_3_live_provider_execution_accepted",
    }
    assert acceptance["implementation"] == {
        "base_sha": "7a3399d0b1033dbe982a966fa1c4d693f27cda37",
        "expected_head_merge": True,
        "head_sha": "0ee8c75e87434a33c64b37bd5a2837c2dad10ef8",
        "issue_number": 1208,
        "merge_sha": "96a5497f65aee27f8b13a017484be67824ea4160",
        "pull_request": 1209,
        "trigger_marker": "[m26.pa4-real-verified-answer-authorized-attempt-2]",
    }
    assert acceptance["owner_authorization"] == {
        "credential_name": "MINIMAX_API_KEY",
        "environment": "m23-r3-diagnostic",
        "exact_head_sha": "0ee8c75e87434a33c64b37bd5a2837c2dad10ef8",
        "exact_pr": 1209,
        "frozen_benchmark_population_digest": (
            "f0a2bc69ea76fba5387050d0a2a25309ec4db86d94203d6f6eb21da9e305fe5b"
        ),
        "logical_attempt": 2,
        "maximum_provider_calls_per_item_including_repair": 2,
        "maximum_repair_attempts": 1,
        "maximum_total_spend_usd": 1.0,
        "model_id": "MiniMax-M3",
        "policy_digest": (
            "56d7743ded108309fefbbeede2ed2eb6e5ae295540c41f458ab5ec5a2fad6069"
        ),
        "provider_id": "minimax",
        "unique_artifact_name": "m26-pa-4-live-verified-answer-evidence-attempt-2",
    }


def test_pa4_acceptance_binds_live_evidence_and_thresholds() -> None:
    acceptance = load(PILOT / "m26-pa-4-acceptance.json")
    assert acceptance["live_evidence"] == {
        "artifact_archive_digest": (
            "sha256:aafafd31c617b705e002591717b1dfbbb7a70a3a96e20d52cbcd52bae9766df9"
        ),
        "artifact_entry_names": [
            "m26-pa-4-benchmark-population.json",
            "m26-pa-4-contract-registry.json",
            "m26-pa-4-live-verified-answer-receipt.json",
            "m26-pa-4-live-verified-answer-receipt.sha256",
            "m26-pa-4-owner-decision.json",
            "m26-pa-4-verified-answer-policy.json",
            "status.txt",
        ],
        "artifact_expires_at": "2026-08-27T18:11:21Z",
        "artifact_id": 8699066827,
        "artifact_name": "m26-pa-4-live-verified-answer-evidence-attempt-2",
        "artifact_size_in_bytes": 224359,
        "live_job_conclusion": "success",
        "live_job_id": 90366074535,
        "receipt_file_sha256": (
            "e48fb52fc048f5fc875ca3d265acd4af05f4c5ec2f16f61f586c4c53c2c15565"
        ),
        "receipt_schema_version": "knowledge-engine-m26-pa-4-verified-answer-receipt/v2",
        "receipt_self_sha256": (
            "7eec05e7d18b1c3c521379c6bb341f0827ef54dbc2df49337d0a24fe3678fd6a"
        ),
        "receipt_sha256_file_value": (
            "e48fb52fc048f5fc875ca3d265acd4af05f4c5ec2f16f61f586c4c53c2c15565"
        ),
        "receipt_status": "real_verified_answer_citation_gate_verified",
        "run_attempt": 1,
        "run_event": "push",
        "run_id": 30386218699,
        "status_file_value": "success",
        "workflow_head_sha": "96a5497f65aee27f8b13a017484be67824ea4160",
        "workflow_name": "M26.PA.4 Real Verified Answer and Citation Gate",
    }
    assert acceptance["thresholds"] == {
        "candidate_eligible_count": 10,
        "mandatory_abstention_count": 2,
        "maximum_unsupported_accepted_material_claims": 0,
        "minimum_abstention_items": 2,
        "minimum_ready_candidate_items": 8,
        "population_count": 12,
        "support_threshold": 1.0,
    }
    assert acceptance["receipt_summary"] == {
        "abstention_count": 4,
        "all_non_abstained_material_claims_supported": True,
        "benchmark_population_count": 12,
        "citation_precision": 1.0,
        "material_claim_count": 8,
        "ready_candidate_count": 8,
        "supported_material_claim_count": 8,
        "unsupported_material_claim_count": 0,
    }


def test_pa4_acceptance_preserves_diagnostics_and_failed_attempt() -> None:
    acceptance = load(PILOT / "m26-pa-4-acceptance.json")
    assert acceptance["aggregate_diagnostics"] == {
        "reason_code_counts": {
            "CASE_POLICY_REQUIRES_ABSTENTION": 2,
            "EXACT_SPAN_MATCH": 8,
            "INSUFFICIENT_SUPPORT": 3,
            "INSUFFICIENT_TEMPORAL_FRESHNESS": 1,
            "TEMPORAL_FRESHNESS_UNVERIFIED": 1,
        },
        "result_class_counts": {
            "abstention": 4,
            "ready_candidate": 8,
        },
        "terminal_status_counts": {
            "abstention_required": 4,
            "verified_answer_ready_candidate": 8,
        },
    }
    assert acceptance["attempt_1_failed_closed_evidence"] == {
        "abstention_count": 12,
        "failure_code": "M26-PA4-068",
        "immutable_failed_evidence": True,
        "ready_candidate_count": 0,
        "receipt_file_sha256": (
            "71b2056961a50063f21a30ac4dabe8317650e564d895d027565f9734a67e57f7"
        ),
        "rerun_forbidden": True,
        "run_attempt": 1,
        "run_id": 30373895685,
        "workflow_head_sha": "7a3399d0b1033dbe982a966fa1c4d693f27cda37",
    }
    assert acceptance["superseded_pr"] == {
        "head_sha": "74aaa938e973dd76e1215cb026e51d5882678a27",
        "minimum_ready_candidate_items_zero_adopted": False,
        "pull_request": 1207,
        "reason": "superseded_zero_ready_threshold_patch_not_merged",
        "state": "closed",
    }


def test_pa4_acceptance_keeps_downstream_authority_closed() -> None:
    acceptance = load(PILOT / "m26-pa-4-acceptance.json")
    assert not any(acceptance["authority_boundary"].values())
    assert acceptance["operation_counts"] == {
        "canonical_writes": 0,
        "production_pointer_mutations": 0,
        "provider_calls": 12,
        "public_shadow_canary_traffic_operations": 0,
        "qdrant_count_operations": 1,
        "qdrant_scroll_operations": 17,
        "qdrant_write_operations": 0,
        "r2_read_operations": 3,
        "r2_write_operations": 0,
        "source_foundation_release_mutations": 0,
    }
    assert acceptance["reconciliation"] == {
        "artifact_archive_digest_verified": True,
        "dedicated_issue_number": 1210,
        "no_new_provider_call": True,
        "no_runtime_or_workflow_changes": True,
        "receipt_file_digest_verified": True,
        "receipt_schema_verified": True,
        "receipt_self_digest_verified": True,
        "remote_run_and_artifact_verified": True,
        "separate_reconciliation_pr_required": True,
        "thresholds_verified": True,
    }
    assert acceptance["next_stage"] == {
        "authorized_after_reconciliation_merge": True,
        "daniel_pa5_gate_required": True,
        "m26_closed": False,
        "name": "Real Controlled Internal Shadow Pilot",
        "predecessor_status_required": (
            "m26_pa_4_verified_answer_citation_gate_accepted"
        ),
        "production_answer_serving_permitted": False,
        "public_shadow_canary_traffic_permitted": False,
        "stage_id": "M26.PA.5",
    }


def test_pa4_reconciliation_doc_and_workflow_are_bounded() -> None:
    doc = (DOCS / "m26-pa-4-reconciliation.md").read_text(encoding="utf-8")
    assert "m26_pa_4_verified_answer_citation_gate_accepted" in doc
    assert "30386218699" in doc
    assert "8699066827" in doc
    assert "0ee8c75e87434a33c64b37bd5a2837c2dad10ef8" in doc
    assert "7eec05e7d18b1c3c521379c6bb341f0827ef54dbc2df49337d0a24fe3678fd6a" in doc
    assert "does not authorize another live provider call" in doc
    assert "Daniel's explicit PA.5 hard-gate approval" in doc
    assert "m26_closed" in doc

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "actions: read" in workflow
    assert "issues: read" in workflow
    assert "pull-requests: read" in workflow
    assert "contents: write" not in workflow
    assert "m26-pa-4-live-verified-answer-evidence-attempt-2" in workflow
    assert "MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}" not in workflow
    assert "Execute bounded MiniMax M3 verified-answer gate" not in workflow
