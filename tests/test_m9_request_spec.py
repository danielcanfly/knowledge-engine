from __future__ import annotations

import hashlib
import json
from pathlib import Path

from knowledge_engine.batch_lifecycle import next_action
from knowledge_engine.batch_registry import load_batch_registry, validate_batch_registry
from knowledge_engine.batch_spec import load_batch_spec
from knowledge_engine.promotion_request import load_promotion_request_spec

REQUEST = Path("production_promotions/m9-001-agent-planning-strategies.json")
SPEC = Path("governed_batches/m9-001-agent-planning-strategies.json")
REGISTRY = Path("governed_batches/registry-v2.json")
BASELINE = Path("governed_batches/evidence/m9-001-production-baseline.json")
RUNTIME = Path("governed_batches/evidence/m9-001-runtime-acceptance-observation.json")
PROMOTION = Path(
    "governed_batches/evidence/m9-001-production-promotion-observation.json"
)
REPLAY = Path(
    "governed_batches/evidence/m9-001-idempotent-replay-observation.json"
)
LIFECYCLE = Path("governed_batches/evidence/m9-001-lifecycle-history.json")

OPERATION_ID = "m9-001-agent-planning-strategies-001"
REQUEST_SHA256 = "41564a42a3f207ea87bbc600935effbb9c3979c8366e16a4b1c7d1f35e172b5b"
PREVIOUS_RELEASE = "20260707T111252Z-aebf06593f89"
PREVIOUS_MANIFEST = (
    "1a2f2014073e9e97f9e1fdd5df4e43bf19cb2b2679532b6e52ea38480ec4d2ec"
)
PREVIOUS_POINTER = "2de63a9ff5963ea3f72f0051b25a084dda9e5e609fe79615e55e3f95a1351914"
TARGET_RELEASE = "20260708T040116Z-69a9f445699a"
TARGET_MANIFEST = (
    "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
)
TARGET_POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m9_request_spec_is_exact_and_consumed_by_closed_batch() -> None:
    request = load_promotion_request_spec(
        request_path=REQUEST,
        control_plane_sha="0" * 40,
    )
    spec = load_batch_spec(SPEC)
    raw_registry = _load(REGISTRY)
    registry = validate_batch_registry(load_batch_registry(REGISTRY))
    baseline = _load(BASELINE)
    runtime = _load(RUNTIME)
    promotion = _load(PROMOTION)
    replay = _load(REPLAY)
    lifecycle = _load(LIFECYCLE)
    normalized = request.normalized()

    assert hashlib.sha256(REQUEST.read_bytes()).hexdigest() == REQUEST_SHA256
    assert "control_plane_sha" not in request.raw
    assert normalized["control_plane_sha"] == "0" * 40

    assert spec.lifecycle_state == "closed"
    assert next_action(spec.lifecycle_state) == "start_next_batch"
    assert normalized["operation_id"] == OPERATION_ID
    assert spec.raw["production_request"] == {
        "operation_id": OPERATION_ID,
        "request_path": str(REQUEST),
    }

    assert normalized["candidate_channel"] == spec.raw["candidate"]["channel"]
    assert normalized["release_id"] == TARGET_RELEASE
    assert normalized["manifest_sha256"] == TARGET_MANIFEST
    assert normalized["source_repository"] == spec.raw["source"]["repository"]
    assert normalized["source_sha"] == spec.raw["source"]["sha"]
    assert normalized["builder_sha"] == spec.raw["builder_sha"]
    assert normalized["foundation_sha"] == spec.raw["foundation_sha"]
    assert normalized["expected_previous_release_id"] == PREVIOUS_RELEASE
    assert normalized["expected_previous_manifest_sha256"] == PREVIOUS_MANIFEST

    assert baseline["production_release_id"] == PREVIOUS_RELEASE
    assert baseline["production_manifest_sha256"] == PREVIOUS_MANIFEST
    assert baseline["production_pointer_sha256"] == PREVIOUS_POINTER
    assert baseline["mutations_performed"] == []

    acceptance = spec.raw["acceptance"]
    assert normalized["post_promote_public_query"] == acceptance["public_query"]
    assert normalized["expected_citation_url"] == acceptance["expected_citation_url"]
    assert normalized["post_promote_acl_query"] == acceptance["acl_query"]
    assert normalized["actor"] == "danielcanfly"

    assert registry["status"] == "valid"
    assert registry["batch_count"] == 2
    entry = raw_registry["batches"][-1]
    assert entry["lifecycle_state"] == "closed"
    assert entry["operation_id"] == OPERATION_ID
    assert entry["request_path"] == str(REQUEST)

    transitions = [(item["from"], item["to"]) for item in lifecycle["transitions"]]
    assert transitions[-3:] == [
        ("runtime_accepted", "request_spec_committed"),
        ("request_spec_committed", "production_promoted"),
        ("production_promoted", "closed"),
    ]
    request_evidence = lifecycle["transitions"][-3]["evidence"]
    assert request_evidence["request_sha256"] == REQUEST_SHA256
    assert request_evidence["control_plane_sha_committed"] is False
    promotion_evidence = lifecycle["transitions"][-2]["evidence"]
    assert promotion_evidence["promotion_status"] == "promoted"
    assert promotion_evidence["idempotent"] is False
    assert promotion_evidence["production_pointer_sha256"] == TARGET_POINTER
    replay_evidence = lifecycle["transitions"][-1]["evidence"]
    assert replay_evidence["precondition_state"] == "already_target"
    assert replay_evidence["promotion_status"] == "already_promoted"
    assert replay_evidence["idempotent"] is True
    assert replay_evidence["production_pointer_byte_exact_unchanged"] is True
    assert replay_evidence["intent_reused_as_authoritative_record"] is True
    assert replay_evidence["receipt_reused_as_authoritative_record"] is True
    assert replay_evidence["rollback_receipt_present"] is False
    assert lifecycle["final_state"] == "closed"
    assert lifecycle["production_mutated"] is True
    assert lifecycle["replay_mutated_production"] is False
    assert lifecycle["next_legal_action"] == "start_next_batch"

    assert runtime["status"] == "passed"
    assert runtime["production_pointer"]["before_sha256"] == PREVIOUS_POINTER
    assert runtime["production_pointer"]["after_sha256"] == PREVIOUS_POINTER
    assert runtime["production_mutated"] is False

    assert promotion["status"] == "passed"
    assert promotion["promotion"]["run_id"] == 28919098263
    assert promotion["promotion"]["artifact_id"] == 8158736427
    assert promotion["promotion"]["status"] == "promoted"
    assert promotion["promotion"]["idempotent"] is False
    assert promotion["previous_production"]["pointer_sha256"] == PREVIOUS_POINTER
    assert promotion["production_target"] == {
        "release_id": TARGET_RELEASE,
        "manifest_sha256": TARGET_MANIFEST,
        "pointer_sha256": TARGET_POINTER,
    }
    assert promotion["runtime_acceptance"]["public_status"] == "answered"
    assert promotion["runtime_acceptance"]["expected_citation_present"] is True
    assert promotion["runtime_acceptance"]["acl_status"] == "not_found"
    assert promotion["runtime_acceptance"]["acl_filtered_count"] == 1
    assert promotion["runtime_acceptance"]["public_raw_fallback_used"] is False
    assert promotion["runtime_acceptance"]["acl_raw_fallback_used"] is False
    assert promotion["ledger"]["comment_id"] == 4911573318
    assert promotion["ledger"]["appended"] is True
    assert promotion["security_notes"]["rollback_used"] is False
    assert promotion["security_notes"]["idempotent_replay_used"] is False
    assert promotion["production_mutated"] is True

    assert replay["status"] == "passed"
    assert replay["replay"]["run_id"] == 28922045241
    assert replay["replay"]["job_id"] == 85801208155
    assert replay["replay"]["artifact_id"] == 8159843482
    assert replay["replay"]["precondition_state"] == "already_target"
    assert replay["replay"]["status"] == "already_promoted"
    assert replay["replay"]["idempotent"] is True
    assert replay["production_target"]["pointer_sha256_before"] == TARGET_POINTER
    assert replay["production_target"]["pointer_sha256_after"] == TARGET_POINTER
    assert replay["production_target"]["pointer_byte_exact_unchanged"] is True
    assert replay["runtime_acceptance"]["public_status"] == "answered"
    assert replay["runtime_acceptance"]["expected_citation_present"] is True
    assert replay["runtime_acceptance"]["acl_status"] == "not_found"
    assert replay["runtime_acceptance"]["acl_filtered_count"] == 1
    assert replay["runtime_acceptance"]["public_raw_fallback_used"] is False
    assert replay["runtime_acceptance"]["acl_raw_fallback_used"] is False
    assert replay["ledger"]["comment_id"] == 4911941452
    assert replay["ledger"]["appended"] is True
    assert replay["authoritative_operation_records"]["intent_sha256"] == (
        "4a7775b5bf715ad4b7ebae79aa38048f9282871a99608a1b55d1b558d8bfaefa"
    )
    assert replay["authoritative_operation_records"]["receipt_sha256"] == (
        "1e38ed04d1e89af70e5ed4ace9dc82876128c074f04250e9747f1a69738d2602"
    )
    assert replay["authoritative_operation_records"][
        "rollback_receipt_present"
    ] is False
    assert replay["security_notes"]["additional_replay_used"] is False
    assert replay["security_notes"]["rollback_used"] is False
    assert replay["production_mutated"] is False
    assert replay["next_legal_action"] == "start_next_batch"
