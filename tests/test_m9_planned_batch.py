from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.batch_lifecycle import next_action
from knowledge_engine.batch_registry import load_batch_registry, validate_batch_registry
from knowledge_engine.batch_spec import load_batch_spec

ROOT = Path("governed_batches/evidence")
SPEC = Path("governed_batches/m9-001-agent-planning-strategies.json")
REGISTRY = Path("governed_batches/registry-v2.json")
ORIGIN = ROOT / "m9-001-origin-attestation.json"
REVIEW = ROOT / "m9-001-approved-review-decision.json"
CANDIDATE_AUTH = ROOT / "m9-001-candidate-build-authorization.json"
RUNTIME = ROOT / "m9-001-runtime-acceptance-observation.json"
PROMOTION_APPROVAL = ROOT / "m9-001-production-promotion-approval.json"
PROMOTION = ROOT / "m9-001-production-promotion-observation.json"
REPLAY_APPROVAL = ROOT / "m9-001-idempotent-replay-approval.json"
REPLAY = ROOT / "m9-001-idempotent-replay-observation.json"
LIFECYCLE = ROOT / "m9-001-lifecycle-history.json"

SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
RELEASE = "20260708T040116Z-69a9f445699a"
MANIFEST = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m9_closed_state_is_exact() -> None:
    spec = load_batch_spec(SPEC)
    registry_raw = load(REGISTRY)
    registry = validate_batch_registry(load_batch_registry(REGISTRY))
    origin, review = load(ORIGIN), load(REVIEW)
    candidate_auth, runtime = load(CANDIDATE_AUTH), load(RUNTIME)
    promotion_approval, promotion = load(PROMOTION_APPROVAL), load(PROMOTION)
    replay_approval, replay, lifecycle = (
        load(REPLAY_APPROVAL),
        load(REPLAY),
        load(LIFECYCLE),
    )

    assert spec.batch_id == "m9-001-agent-planning-strategies"
    assert spec.lifecycle_state == "closed"
    assert next_action(spec.lifecycle_state) == "start_next_batch"
    assert spec.raw["source"]["sha"] == SOURCE_SHA
    assert spec.raw["candidate"] == {
        "channel": f"candidate-source-{SOURCE_SHA}",
        "release_id": RELEASE,
        "manifest_sha256": MANIFEST,
    }
    assert spec.raw["acceptance"]["raw_fallback_allowed"] is False

    assert registry["status"] == "valid"
    assert registry["batch_count"] == 2
    assert registry["batches"][-1]["lifecycle_state"] == "closed"
    assert registry_raw["batches"][-1]["operation_id"] == (
        "m9-001-agent-planning-strategies-001"
    )

    assert origin["approved_scope_option"] == "A"
    assert review["status"] == "approved"
    assert review["canonical_write_authorized"] is True
    assert candidate_auth["production_promotion_authorized"] is False
    assert runtime["status"] == "passed"
    assert runtime["production_mutated"] is False

    assert promotion_approval["decision"] == "approve"
    assert promotion_approval["authorization_scope"]["rollback_authorized"] is False
    assert promotion["status"] == "passed"
    assert promotion["promotion"]["run_id"] == 28919098263
    assert promotion["promotion"]["status"] == "promoted"
    assert promotion["promotion"]["idempotent"] is False
    assert promotion["production_target"]["pointer_sha256"] == POINTER
    assert promotion["ledger"]["comment_id"] == 4911573318

    assert replay_approval["decision"] == "approve"
    scope = replay_approval["authorization_scope"]
    assert scope["single_idempotent_replay_dispatch_authorized"] is True
    assert scope["closure_reconciliation_after_success_authorized"] is True
    assert scope["rollback_authorized"] is False
    assert scope["additional_replays_authorized"] is False

    assert replay["status"] == "passed"
    assert replay["replay"]["run_id"] == 28922045241
    assert replay["replay"]["status"] == "already_promoted"
    assert replay["replay"]["idempotent"] is True
    target = replay["production_target"]
    assert target["pointer_sha256_before"] == POINTER
    assert target["pointer_sha256_after"] == POINTER
    assert target["pointer_byte_exact_unchanged"] is True
    acceptance = replay["runtime_acceptance"]
    assert acceptance["public_status"] == "answered"
    assert acceptance["expected_citation_present"] is True
    assert acceptance["acl_status"] == "not_found"
    assert acceptance["acl_filtered_count"] == 1
    assert acceptance["public_raw_fallback_used"] is False
    assert acceptance["acl_raw_fallback_used"] is False
    assert replay["ledger"]["comment_id"] == 4911941452
    records = replay["authoritative_operation_records"]
    assert records["intent_sha256"] == (
        "4a7775b5bf715ad4b7ebae79aa38048f9282871a99608a1b55d1b558d8bfaefa"
    )
    assert records["receipt_sha256"] == (
        "1e38ed04d1e89af70e5ed4ace9dc82876128c074f04250e9747f1a69738d2602"
    )
    assert records["rollback_receipt_present"] is False
    assert records["mutations_performed"] == []
    assert replay["production_mutated"] is False

    transitions = [(item["from"], item["to"]) for item in lifecycle["transitions"]]
    assert transitions[-2:] == [
        ("request_spec_committed", "production_promoted"),
        ("production_promoted", "closed"),
    ]
    assert lifecycle["final_state"] == "closed"
    assert lifecycle["production_target"]["pointer_sha256"] == POINTER
    assert lifecycle["production_mutated"] is True
    assert lifecycle["replay_mutated_production"] is False
    assert lifecycle["next_framework_action"] == "start_next_batch"
    assert lifecycle["next_legal_action"] == "start_next_batch"
