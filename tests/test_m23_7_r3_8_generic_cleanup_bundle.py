from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_delete import validate_authorization
from scripts.m23_7_r3_8_remote_operator import canonical_sha256

BUNDLE_DIR = Path(".github/evidence/m23-7-r3-8-generic-cleanup")
SEAL_PATH = BUNDLE_DIR / "worker-present-recovery-seal-29711546707.json"
RECONCILIATION_PATH = BUNDLE_DIR / "worker-present-reconciliation-29711546707.json"
AUTHORIZATION_PATH = Path(
    "deletion_authorizations/m23-7/r3-8/knowledge-engine-r3-8-29696136508.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_self_digest(value: dict, key: str) -> None:
    expected = value[key]
    unsigned = dict(value)
    unsigned.pop(key)
    assert canonical_sha256(unsigned) == expected


def test_generic_cleanup_bundle_binds_worker_present_evidence() -> None:
    seal = _load(SEAL_PATH)
    reconciliation = _load(RECONCILIATION_PATH)
    authorization = validate_authorization(AUTHORIZATION_PATH)

    _assert_self_digest(seal, "seal_sha256")
    _assert_self_digest(reconciliation, "reconciliation_sha256")

    receipt = seal["receipt"]
    assert receipt["schema_version"] == (
        "knowledge-engine-m23-7-r3-8-generic-recovery-probe/v1"
    )
    assert receipt["status"] == "completed_read_only_recovery_probe"
    assert receipt["affected_run_id"] == "29696136508"
    assert receipt["affected_engine_sha"] == "b57f0a05f6dca2d4030fdee354a478be6f295ff8"
    assert receipt["probe_engine_sha"] == "c5357c47dd34b462be64175888f76cec54299904"
    assert receipt["worker_name"] == "knowledge-engine-r3-8-29696136508"
    assert receipt["worker_state"] == "worker_present"
    assert receipt["versions"]["identity_count"] == 4
    assert receipt["deployments"]["identity_count"] == 4
    assert receipt["recovery_probe_sha256"] == (
        "3fe39c82f8030a142bd2b78cf33b9ba9e3a1044cea111fa7d9f0add27d904efe"
    )

    for field in (
        "worker_delete_dispatched",
        "worker_deploy_dispatched",
        "worker_route_invoked",
        "worker_secret_mutation_dispatched",
        "qdrant_read_dispatched",
        "qdrant_mutation_dispatched",
        "r2_read_dispatched",
        "r2_mutation_dispatched",
        "protected_mutations_dispatched",
        "blockers_cleared",
    ):
        assert receipt[field] is False

    assert reconciliation["seal_sha256"] == seal["seal_sha256"]
    assert reconciliation["result"] == {
        "blocker_clearance_eligible": False,
        "deletion_authorization_next_gate": True,
        "next_gate": "exact_deletion_authorization",
        "production_retrieval": "lexical",
        "worker_lifecycle_clean": False,
        "worker_present_evidence_reconciled": True,
        "worker_state": "worker_present",
    }

    assert authorization["worker_name"] == receipt["worker_name"]
    assert authorization["observation_run_id"] == receipt["affected_run_id"]
    assert authorization["recovery_run_id"] == "29711546707"
    assert authorization["receipt_sha256"] == receipt["recovery_probe_sha256"]
    assert authorization["evidence_seal_sha256"] == seal["seal_sha256"]
    assert (
        authorization["independent_reconciliation_sha256"]
        == reconciliation["reconciliation_sha256"]
    )
    assert authorization["worker_version_ids"] == receipt["versions"]["identities"]
    assert authorization["worker_deployment_ids"] == receipt["deployments"][
        "identities"
    ]
