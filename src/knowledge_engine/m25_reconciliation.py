from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from knowledge_engine.m25_formal_closure import self_digest, validate_repository


class M25ReconciliationError(ValueError):
    pass


EXPECTED_RECONCILIATION_STATUS = "m25_final_reconciliation_ready"
EXPECTED_RESULT = "m25_closed"
EXPECTED_OUTCOME = "approved_bounded_large_scale_ingestion"
EXPECTED_CLOSURE_HEAD = "7a8d68c2c3d8486ae1ff45eff46b5f60ddd11165"
EXPECTED_CLOSURE_MERGE = "dd373e932b75c89de3bdea45e581fd0df512c40b"
EXPECTED_CLOSURE_ARTIFACT_DIGEST = (
    "sha256:7203dfa9b935dd0f05a30227ce7ae4aa81a29ede776d1b4bc3500d0e11cb7f48"
)
EXPECTED_OWNER_DECISION_SHA256 = (
    "4a340df130df29c57e32bac80eaebc9e5b428aae80b6e8cdda4bff7e98809629"
)
EXPECTED_FINAL_ACCEPTANCE_SHA256 = (
    "15012cfa708c7c19cf1be91ac6ea566886c3728b880fdf42d4b9d7b5f0bbc4ed"
)
EXPECTED_CLOSURE_EVIDENCE_SHA256 = (
    "0fd453e708ab940dbc123577f239fb45cf1d8b6057ec6223dbc6fbbc55167a91"
)
REQUIRED_RUNS = {
    "architecture-canon",
    "formal-closure-evidence",
    "graph-v2",
    "identity-governance",
    "release-lifecycle",
    "test",
}
AUTHORITY_FALSE_KEYS = {
    "cloudflare_access_mutation",
    "credential_mutation",
    "dns_mutation",
    "foundation_mutation",
    "m26_production_answer_serving",
    "new_ingestion_workload_execution",
    "production_pointer_mutation",
    "public_production_traffic_expansion",
    "qdrant_mutation",
    "r2_production_mutation",
    "semantic_or_hybrid_serving_expansion",
    "source_mutation",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise M25ReconciliationError(f"{path} must contain a JSON object")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_reconciliation(root: Path) -> dict[str, Any]:
    validate_repository(root)

    reconciliation = load_json(root / "pilot" / "m25" / "m25-final-reconciliation.json")
    if reconciliation.get("schema_version") != (
        "knowledge-engine-m25-final-reconciliation/v1"
    ):
        raise M25ReconciliationError("schema version mismatch")
    if reconciliation.get("status") != EXPECTED_RECONCILIATION_STATUS:
        raise M25ReconciliationError("reconciliation status mismatch")
    if reconciliation.get("result") != EXPECTED_RESULT:
        raise M25ReconciliationError("reconciliation result mismatch")
    if reconciliation.get("self_sha256") != self_digest(reconciliation):
        raise M25ReconciliationError("self digest mismatch")

    closure_pr = reconciliation.get("closure_pr")
    if not isinstance(closure_pr, dict):
        raise M25ReconciliationError("closure PR missing")
    if closure_pr.get("head_sha") != EXPECTED_CLOSURE_HEAD:
        raise M25ReconciliationError("closure PR head mismatch")
    if closure_pr.get("merge_sha") != EXPECTED_CLOSURE_MERGE:
        raise M25ReconciliationError("closure PR merge mismatch")
    if closure_pr.get("expected_head_merge") is not True:
        raise M25ReconciliationError("expected-head merge not recorded")

    owner_decision = load_json(root / "pilot" / "m25" / "m25-10-owner-decision.json")
    final_acceptance = load_json(
        root / "pilot" / "m25" / "m25-10-final-acceptance.json"
    )
    closure_evidence = load_json(
        root / "pilot" / "m25" / "m25-10-formal-closure-evidence.json"
    )
    if owner_decision.get("self_sha256") != EXPECTED_OWNER_DECISION_SHA256:
        raise M25ReconciliationError("owner decision digest mismatch")
    if owner_decision.get("outcome") != EXPECTED_OUTCOME:
        raise M25ReconciliationError("owner decision outcome mismatch")
    if final_acceptance.get("self_sha256") != EXPECTED_FINAL_ACCEPTANCE_SHA256:
        raise M25ReconciliationError("final acceptance digest mismatch")
    if final_acceptance.get("status") != EXPECTED_RESULT:
        raise M25ReconciliationError("final acceptance status mismatch")
    if closure_evidence.get("self_sha256") != EXPECTED_CLOSURE_EVIDENCE_SHA256:
        raise M25ReconciliationError("closure evidence digest mismatch")
    if closure_evidence.get("status") != EXPECTED_RESULT:
        raise M25ReconciliationError("closure evidence status mismatch")

    runs = reconciliation.get("closure_workflow_runs")
    if not isinstance(runs, dict) or set(runs) != REQUIRED_RUNS:
        raise M25ReconciliationError("workflow run set mismatch")
    if any(not isinstance(value, int) or value <= 0 for value in runs.values()):
        raise M25ReconciliationError("workflow run id mismatch")
    artifact = reconciliation.get("closure_workflow_artifact")
    if not isinstance(artifact, dict):
        raise M25ReconciliationError("closure workflow artifact missing")
    if artifact.get("digest") != EXPECTED_CLOSURE_ARTIFACT_DIGEST:
        raise M25ReconciliationError("closure workflow artifact digest mismatch")

    stage_reconciliation = reconciliation.get("m25_stage_reconciliation")
    if not isinstance(stage_reconciliation, dict):
        raise M25ReconciliationError("stage reconciliation missing")
    if stage_reconciliation.get("required_stage_count") != 10:
        raise M25ReconciliationError("stage count mismatch")
    for key in (
        "m25_1_through_m25_10_present",
        "m25_8_original_blocker_preserved_as_superseded",
        "m25_9_original_blocker_preserved_as_superseded",
        "m25_10_production_pointer_promoted",
        "final_acceptance_on_main",
    ):
        if stage_reconciliation.get(key) is not True:
            raise M25ReconciliationError(f"stage reconciliation missing: {key}")

    authority = reconciliation.get("authority_boundaries")
    if not isinstance(authority, dict):
        raise M25ReconciliationError("authority boundaries missing")
    if authority.get("m25_closed") is not True:
        raise M25ReconciliationError("m25_closed boundary missing")
    if authority.get("bounded_large_scale_ingestion_readiness") is not True:
        raise M25ReconciliationError("bounded readiness boundary missing")
    for key in AUTHORITY_FALSE_KEYS:
        if authority.get(key) is not False:
            raise M25ReconciliationError(f"authority escalation detected: {key}")

    return {
        "status": "m25_final_reconciliation_valid",
        "result": EXPECTED_RESULT,
        "closure_merge_sha": closure_pr["merge_sha"],
        "workflow_run_count": len(runs),
        "authority_false_count": len(AUTHORITY_FALSE_KEYS),
    }


def validate_repository_reconciliation(root: Path) -> dict[str, Any]:
    return validate_reconciliation(root)
