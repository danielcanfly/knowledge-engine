from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

BUNDLE_DIR = Path(".github/evidence/m23-7-r3-8-generic-cleanup")
SEAL_PATH = BUNDLE_DIR / "deletion-absence-evidence-seal-29711739513.json"
RECONCILIATION_PATH = BUNDLE_DIR / "deletion-absence-reconciliation-29711739513.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_self_digest(value: dict, key: str) -> None:
    expected = value[key]
    unsigned = dict(value)
    unsigned.pop(key)
    assert canonical_sha256(unsigned) == expected


def test_generic_cleanup_absence_evidence_reconciles_delete_and_probe() -> None:
    seal = _load(SEAL_PATH)
    reconciliation = _load(RECONCILIATION_PATH)
    _assert_self_digest(seal, "seal_sha256")
    _assert_self_digest(reconciliation, "reconciliation_sha256")

    deletion = seal["deletion_failure"]
    probe = seal["post_delete_probe"]
    assert deletion["worker_name"] == "knowledge-engine-r3-8-29696136508"
    assert deletion["worker_delete_dispatched"] is True
    assert deletion["failure_stage"] == "absence_probe"
    assert deletion["failure_code"] == "delete_absence_not_proven"
    assert deletion["control_plane_absence_proven"] is False

    assert probe["worker_name"] == deletion["worker_name"]
    assert probe["worker_state"] == "worker_absent"
    assert probe["versions"]["http_status"] == 404
    assert probe["versions"]["error_codes"] == [10007]
    assert probe["versions"]["identity_count"] == 0
    assert probe["deployments"]["http_status"] == 404
    assert probe["deployments"]["error_codes"] == [10007]
    assert probe["deployments"]["identity_count"] == 0

    assert seal["result"] == {
        "blocker_clearance_eligible": False,
        "control_plane_absence_proven": True,
        "delete_dispatched_once": True,
        "destructive_deletion_replayed": False,
        "production_retrieval": "lexical",
        "worker_lifecycle_clean": True,
        "worker_name": "knowledge-engine-r3-8-29696136508",
        "worker_state": "worker_absent",
    }
    assert reconciliation["seal_sha256"] == seal["seal_sha256"]
    assert reconciliation["result"] == {
        "control_plane_absence_proven": True,
        "m23_7_closure_authorized": False,
        "next_gate": "harness_reset_or_governed_live_acceptance_defer",
        "post_delete_absence_reconciled": True,
        "production_retrieval": "lexical",
        "semantic_live_acceptance_complete": False,
        "worker_lifecycle_clean": True,
        "worker_name": "knowledge-engine-r3-8-29696136508",
        "worker_state": "worker_absent",
    }
