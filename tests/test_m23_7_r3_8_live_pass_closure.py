from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

ROOT = Path(".github/evidence/m23-7-r3-8-live-pass")
SEAL_PATH = ROOT / "live-pass-evidence-seal-29715599032.json"
RECONCILIATION_PATH = ROOT / "live-pass-reconciliation-29715599032.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_self_digest(value: dict, key: str, expected: str) -> None:
    unsigned = dict(value)
    unsigned.pop(key)
    assert value[key] == expected
    assert canonical_sha256(unsigned) == expected


def test_live_pass_seal_binds_confirmation_artifact_and_gates() -> None:
    seal = _load(SEAL_PATH)
    _assert_self_digest(
        seal,
        "seal_sha256",
        "94dad021d947422933fab588b6f0396c249d73516ae27f3533329480edc7e2eb",
    )

    assert seal["schema_version"] == (
        "knowledge-engine-m23-7-r3-8-live-pass-evidence-seal/v1"
    )
    assert seal["engine_sha"] == "2a24ed38f4d9c5e370417453860314cd60c14ef9"
    assert seal["observation_run_id"] == "29715599032"
    assert seal["artifact"] == {
        "id": "8450463481",
        "name": "m23-7-r3-8-remote-29715599032",
        "size_bytes": 5470,
        "zip_sha256": (
            "7f025b28fad8f6574748f58f0de9042cf15c7b93a8fa8070c105a0ba0419311c"
        ),
    }
    assert seal["files"]["latency_receipt_file_sha256"] == (
        "f62e7bf061e18e2a49ab6978ad6a15e30363569518eb9f22f2ac554535ffb23c"
    )
    assert seal["files"]["latency_receipt_self_digest"] == (
        "497a6df59d66fdfb47f24aab0c858933ba796c603f613684776837a990149e59"
    )
    assert seal["metrics"] == {
        "mrr_at_10": 0.807291666667,
        "ndcg_at_10": 0.851933109598,
        "recall_at_5": 0.875,
    }
    assert all(seal["gates"].values())


def test_live_pass_seal_preserves_authority_boundaries_and_privacy() -> None:
    seal = _load(SEAL_PATH)

    assert seal["result"] == {
        "blocker_clearance_eligible_after_reconciliation": True,
        "latency_blocker_clearance_eligible": True,
        "production_retrieval": "lexical",
        "retrieval_quality_blocker_clearance_eligible": True,
        "semantic_answer_serving_enabled": False,
        "semantic_live_acceptance_complete": True,
        "semantic_promotion_enabled": False,
        "status": "pass_placed_worker_latency_repair",
    }
    assert seal["authority"] == {
        "blocker_clearance_authorized": False,
        "evidence_seal_only": True,
        "m23_7_closure_authorized": False,
        "parent_closure_authorized": False,
        "production_mutation_authorized": False,
        "promotion_authorized": False,
        "protected_mutations_dispatched": False,
        "qdrant_delete_dispatched": False,
        "qdrant_read_dispatched": True,
        "qdrant_reindex_dispatched": False,
        "qdrant_write_dispatched": False,
        "r2_mutation_authorized": False,
        "serving_authorized": False,
        "source_mutation_authorized": False,
    }
    assert seal["privacy"] == {
        "arbitrary_exception_text_persisted": False,
        "credentials_persisted": False,
        "placement_location_persisted": False,
        "raw_answers_persisted": False,
        "raw_queries_persisted": False,
        "service_hostname_persisted": False,
        "service_url_persisted": False,
    }


def test_live_pass_stable_worker_lifecycle_is_not_per_run_cleanup_debt() -> None:
    worker = _load(SEAL_PATH)["worker"]

    assert worker["name"] == "knowledge-engine-r3-8-diagnostic"
    assert worker["version_id"] == "d0f0048a-c716-44b9-a093-5d67b02f3489"
    assert worker["stable_diagnostic_service"] is True
    assert worker["atomic_secrets_uploaded_with_deploy"] is True
    assert worker["per_run_worker_created"] is False
    assert worker["per_run_deletion_authorization_required"] is False
    assert worker["placement_response_class"] == "absent"
    assert worker["placement_observation_verified"] is True
    assert worker["readiness"] == {
        "application_ready": True,
        "attempt_count": 2,
        "consecutive_successes": 2,
        "placement_classes": ["absent"],
        "required_consecutive_successes": 2,
        "service_available": True,
    }


def test_live_pass_reconciliation_clears_r3_blockers_without_promotion() -> None:
    seal = _load(SEAL_PATH)
    reconciliation = _load(RECONCILIATION_PATH)
    _assert_self_digest(
        reconciliation,
        "reconciliation_sha256",
        "cb6b7d1b7213da018dd8466c9c43538d616f24f65ece25ef1c28ec1ac4e3094a",
    )

    assert reconciliation["seal_sha256"] == seal["seal_sha256"]
    assert reconciliation["accepted_evidence"] == {
        "artifact_id": "8450463481",
        "artifact_zip_sha256": (
            "7f025b28fad8f6574748f58f0de9042cf15c7b93a8fa8070c105a0ba0419311c"
        ),
        "latency_receipt_file_sha256": (
            "f62e7bf061e18e2a49ab6978ad6a15e30363569518eb9f22f2ac554535ffb23c"
        ),
        "latency_receipt_self_digest": (
            "497a6df59d66fdfb47f24aab0c858933ba796c603f613684776837a990149e59"
        ),
        "lifecycle_sha256": (
            "bd12b998fbd1e82c256035af471c0f21c0c9b251f23ef3c5c7235dbaad2326be"
        ),
    }
    assert reconciliation["result"] == {
        "blockers_cleared": [
            "blocked_pending_retrieval_quality",
            "blocked_pending_latency",
        ],
        "latency_blocker_cleared": True,
        "m23_7_r3_closure_complete": True,
        "new_promotion_decision_required": True,
        "parent_issue_474_may_close": True,
        "production_retrieval": "lexical",
        "retrieval_quality_blocker_cleared": True,
        "semantic_answer_serving_enabled": False,
        "semantic_live_acceptance_complete": True,
        "semantic_promotion_enabled": False,
    }
    assert reconciliation["authority"] == {
        "blocker_clearance_authorized": True,
        "m23_7_r3_closure_authorized": True,
        "parent_474_closure_authorized": True,
        "production_mutation_authorized": False,
        "promotion_authorized": False,
        "protected_mutations_dispatched": False,
        "qdrant_mutation_authorized": False,
        "r2_mutation_authorized": False,
        "serving_authorized": False,
        "source_mutation_authorized": False,
    }
    assert reconciliation["next_gate"] == (
        "separate_explicit_semantic_promotion_decision_or_parallel_product_lane"
    )


def test_live_pass_reconciliation_keeps_stable_worker_retained() -> None:
    lifecycle = _load(RECONCILIATION_PATH)["stable_worker_lifecycle"]

    assert lifecycle == {
        "diagnostic_service_retained": True,
        "per_run_deletion_authorization_required": False,
        "per_run_worker_created": False,
        "stable_diagnostic_service": True,
    }
