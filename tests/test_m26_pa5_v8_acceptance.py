from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from knowledge_engine.m26_verified_answer_citation_gate import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
ACCEPTED_STATUS = "m26_pa_5_controlled_internal_shadow_pilot_accepted"
PA6_UNLOCKED_PENDING_OWNER_CANARY_STATUS = (
    "m26_pa_6_unlocked_pending_owner_canary_approval"
)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def assert_self_digest(value: dict[str, Any]) -> None:
    expected = value["self_sha256"]
    candidate = dict(value)
    candidate["self_sha256"] = ""
    assert canonical_sha256(candidate) == expected


def validate_acceptance() -> dict[str, str]:
    acceptance = load(PILOT / "m26-pa-5-v8-acceptance.json")
    unlock = load(PILOT / "m26-pa-6-unlock-pending-owner-canary-approval.json")
    oversight = load(PILOT / "m26-pa-5-v8-owner-oversight-packet.json")
    assert_self_digest(acceptance)
    assert_self_digest(unlock)
    assert_self_digest(oversight)
    formal = acceptance["formal_attempt_9"]
    metrics = formal["metrics"]
    assert acceptance["status"] == ACCEPTED_STATUS
    assert metrics["complete_accounting"] == 200
    assert metrics["safe_terminal_outcome_rate"] == 1.0
    assert metrics["answerable_grounded_quality_pass_rate"] == 1.0
    assert metrics["material_claim_support_precision"] == 1.0
    assert metrics["citation_locator_validity"] == 1.0
    assert metrics["unsupported_accepted_claims"] == 0
    assert metrics["unresolved_disagreements"] == 0
    calibrations = acceptance["calibrations"]
    assert len(calibrations) == 2
    assert {item["executable_head_sha"] for item in calibrations} == {
        formal["executable_head_sha"]
    }
    assert len({item["sample_sha256"] for item in calibrations}) == 1
    assert len({item["receipt_self_sha256"] for item in calibrations}) == 2
    assert all(item["run_attempt"] == 1 for item in calibrations)
    assert formal["run_attempt"] == 1
    assert unlock["status"] == PA6_UNLOCKED_PENDING_OWNER_CANARY_STATUS
    assert unlock["predecessor"]["pa5_acceptance_self_sha256"] == acceptance["self_sha256"]
    assert not any(acceptance["authority_boundary"].values())
    assert unlock["authority_boundary"] == {
        "canary_traffic_authorized": False,
        "m26_closed": False,
        "pa7_authorized": False,
        "production_answer_serving": False,
        "production_pointer_mutation": False,
        "public_traffic": False,
        "r2_qdrant_source_foundation_release_mutations": 0,
    }
    return {
        "pa5_self_sha256": acceptance["self_sha256"],
        "pa5_status": ACCEPTED_STATUS,
        "pa6_self_sha256": unlock["self_sha256"],
        "pa6_status": PA6_UNLOCKED_PENDING_OWNER_CANARY_STATUS,
    }


def test_pa5_v8_acceptance_schema_self_digest_and_status() -> None:
    acceptance = load(PILOT / "m26-pa-5-v8-acceptance.json")
    schema = load(SCHEMAS / "m26-pa-5-v8-acceptance-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    errors = sorted(
        Draft202012Validator(schema).iter_errors(acceptance),
        key=lambda error: list(error.absolute_path),
    )
    assert errors == []
    assert_self_digest(acceptance)
    assert acceptance["stage_id"] == "M26.PA.5"
    assert acceptance["status"] == ACCEPTED_STATUS
    assert acceptance["effective_only_on_reconciliation_merge"] is True


def test_pa5_v8_acceptance_binds_formal_attempt_9_success() -> None:
    acceptance = load(PILOT / "m26-pa-5-v8-acceptance.json")
    formal = acceptance["formal_attempt_9"]
    assert formal["run_id"] == 30507628057
    assert formal["job_id"] == 90760711733
    assert formal["artifact_id"] == 8746169278
    assert formal["artifact_archive_digest"] == (
        "sha256:3b8b8575561b382a23eb486f6fd060308df9621973ce2e29c75bb648958d3493"
    )
    assert formal["receipt_file_sha256"] == (
        "37658985b3974924ec9a6fa3f7a9ebedd92135670becd01bb0432e0120fa1582"
    )
    assert formal["receipt_self_sha256"] == (
        "316995b3d7ad01260c9bcd69c1a0775d5301d914847ff578b82abff84cd62e9d"
    )
    assert formal["run_attempt"] == 1
    assert formal["trigger_pull_request"] == 1238
    assert formal["trigger_merge_sha"] == "6935674474130db53589ba023b98119aa701703e"
    assert formal["stratum_counts"] == {
        "abstention_no_answer": 15,
        "conflict_and_temporal_freshness": 15,
        "cross_document_comparison": 20,
        "direct_grounded_factual": 90,
        "graph_navigation": 20,
        "prompt_injection_privacy_adversarial": 10,
        "provenance_and_source_trace": 30,
    }
    assert sum(formal["stratum_counts"].values()) == 200


def test_pa5_v8_acceptance_metrics_and_privacy_pass_hard_thresholds() -> None:
    formal = load(PILOT / "m26-pa-5-v8-acceptance.json")["formal_attempt_9"]
    metrics = formal["metrics"]
    assert metrics["complete_accounting"] == 200
    assert metrics["safe_terminal_outcome_rate"] == 1.0
    assert metrics["answerable_grounded_quality_pass_rate"] == 1.0
    assert metrics["material_claim_support_precision"] == 1.0
    assert metrics["citation_locator_validity"] == 1.0
    assert metrics["appropriate_abstention_recall"] == 1.0
    assert metrics["unsupported_accepted_claims"] == 0
    assert metrics["unresolved_disagreements"] == 0
    assert metrics["post_repair_disagreement_rate"] == 0.0
    assert metrics["provider_calls"] == 406
    assert metrics["provider_error_rate"] == 0.0
    assert metrics["p95_latency_ms"] <= 30000
    assert metrics["p99_latency_ms"] <= 60000
    assert formal["privacy"] == {
        "full_provider_response_persisted": False,
        "raw_evidence_persisted": False,
        "raw_query_persisted": False,
        "secret_values_persisted": False,
        "vectors_persisted": False,
    }


def test_pa5_v8_acceptance_binds_two_unique_calibration_passes() -> None:
    acceptance = load(PILOT / "m26-pa-5-v8-acceptance.json")
    calibrations = acceptance["calibrations"]
    assert [item["sequence"] for item in calibrations] == [1, 2]
    assert {item["run_attempt"] for item in calibrations} == {1}
    assert {item["status"] for item in calibrations} == {"passed"}
    assert {item["sample_sha256"] for item in calibrations} == {
        "68e7515b20755f40e949beaed6b8603cc5541c52c91cac470b63f0b88ad32f3d"
    }
    assert {item["executable_head_sha"] for item in calibrations} == {
        "1f09dd3f6266d6632036347c26d8ad4fa66024da"
    }
    assert len({item["receipt_self_sha256"] for item in calibrations}) == 2
    assert acceptance["calibration_governance"] == {
        "cumulative_calibration_cost_usd": "0.02610858",
        "cumulative_calibration_provider_calls": 146,
        "maximum_calibration_cost_usd": "20.00",
        "maximum_calibration_provider_calls": 640,
        "total_rounds_consumed": 3,
        "two_unique_consecutive_passes_on_same_head_and_sample": True,
    }


def test_pa5_v8_acceptance_unlocks_only_pa6_owner_gate() -> None:
    acceptance = load(PILOT / "m26-pa-5-v8-acceptance.json")
    unlock = load(PILOT / "m26-pa-6-unlock-pending-owner-canary-approval.json")
    schema = load(SCHEMAS / "m26-pa-6-unlock-pending-owner-canary-approval-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    errors = sorted(
        Draft202012Validator(schema).iter_errors(unlock),
        key=lambda error: list(error.absolute_path),
    )
    assert errors == []
    assert_self_digest(unlock)
    assert unlock["status"] == PA6_UNLOCKED_PENDING_OWNER_CANARY_STATUS
    assert unlock["predecessor"]["pa5_acceptance_self_sha256"] == acceptance["self_sha256"]
    assert not any(acceptance["authority_boundary"].values())
    assert unlock["authority_boundary"] == {
        "canary_traffic_authorized": False,
        "m26_closed": False,
        "pa7_authorized": False,
        "production_answer_serving": False,
        "production_pointer_mutation": False,
        "public_traffic": False,
        "r2_qdrant_source_foundation_release_mutations": 0,
    }


def test_pa5_v8_owner_oversight_packet_is_sanitized_and_nonblocking() -> None:
    packet = load(PILOT / "m26-pa-5-v8-owner-oversight-packet.json")
    assert_self_digest(packet)
    assert packet["packet_type"] == "nonblocking_owner_oversight"
    assert packet["packet_count"] == 20
    assert sum(packet["stratum_counts"].values()) == 20
    assert packet["disagreements_included"] == {
        "blocking_dispute_count": 0,
        "post_repair_disagreement_count": 0,
        "unresolved_disagreement_count": 0,
    }
    serialized = json.dumps(packet, sort_keys=True)
    assert '"question"' not in serialized
    assert '"answer"' not in serialized
    assert '"prompt"' not in serialized
    assert '"span_text"' not in serialized
    assert '"raw_evidence"' not in serialized


def test_pa5_v8_acceptance_validator_returns_pa5_and_pa6_statuses() -> None:
    assert validate_acceptance() == {
        "pa5_self_sha256": "35ed2c2304061005f534739bbebc592b2685f245ac5067a1d0fbdc41d6535ebb",
        "pa5_status": ACCEPTED_STATUS,
        "pa6_self_sha256": "5b7ca07527e5684bd54033d5ef391ae0082c507ad041ae8f1c6bf1ab3a853f4f",
        "pa6_status": PA6_UNLOCKED_PENDING_OWNER_CANARY_STATUS,
    }
