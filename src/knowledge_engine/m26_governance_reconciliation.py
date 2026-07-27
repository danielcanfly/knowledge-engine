from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SPEC_SHA = "6e71ca5981e3eb45987d188c9c7fb2851a4b5f31803655dd2fc7e28ed4bd22a9"
DENIED = {
    "answer_generation",
    "credential_or_secret_access",
    "dns_or_access_mutation",
    "foundation_mutation",
    "live_provider_calls",
    "production_pointer_mutation",
    "public_or_shadow_or_canary_traffic",
    "qdrant_read_or_write",
    "r2_read_or_write",
    "real_corpus_live_reads",
    "release_mutation",
    "source_mutation",
    "worker_or_pages_mutation",
}
ARTIFACTS = {
    "owner_decision_sha256": "m26-g0-owner-decision.json",
    "milestone_alias_map_sha256": "m26-g0-milestone-alias-map.json",
    "stage_registry_sha256": "m26-g0-stage-registry.json",
    "pa1_ratification_sha256": "m26-g0-pa1-ratification.json",
    "legacy_pa2_candidate_sha256": "m26-g0-legacy-pa2-candidate.json",
}
SCHEMAS = {
    "governance_adoption_schema_sha256": "m26-g0-governance-adoption-v1.schema.json",
    "pa1_ratification_schema_sha256": "m26-g0-pa1-ratification-v1.schema.json",
}
EXPECTED_ALIASES = {
    "M26.9": "M26.S9",
    "M26.10": "M26.S10",
    "M26.11": "M26.PA.1",
    "M26.12": "M26.PA.2",
    "M26.13": "M26.PA.3",
    "M26.14": "M26.PA.4",
    "M26.15": "M26.PA.5",
    "M26.16": "M26.PA.6",
    "M26.17": "M26.PA.7",
}
EXPECTED_STAGES = {
    "M26.G0",
    "M26.S9",
    "M26.S10",
    "M26.PA.1",
    "M26.PA.2",
    "M26.PA.3",
    "M26.PA.4",
    "M26.PA.5",
    "M26.PA.6",
    "M26.PA.7",
}


class GovernanceReconciliationError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GovernanceReconciliationError(f"{path} must contain an object")
    return value


def verify_self_digest(value: dict[str, Any], label: str) -> None:
    expected = value.get("self_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise GovernanceReconciliationError(f"{label}: invalid self_sha256")
    candidate = dict(value)
    candidate["self_sha256"] = ""
    if object_sha256(candidate) != expected:
        raise GovernanceReconciliationError(f"{label}: self digest mismatch")


def _validate_schema(instance: dict[str, Any], schema: dict[str, Any], label: str) -> None:
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=str)
    if errors:
        raise GovernanceReconciliationError(f"{label}: {errors[0].message}")


def _verify_graph(stages: list[dict[str, Any]]) -> None:
    by_id = {stage["stage_id"]: stage for stage in stages}
    if set(by_id) != EXPECTED_STAGES:
        raise GovernanceReconciliationError("stage registry is incomplete")
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(stage_id: str) -> None:
        if stage_id in visiting:
            raise GovernanceReconciliationError("stage dependency cycle detected")
        if stage_id in visited:
            return
        visiting.add(stage_id)
        for predecessor in by_id[stage_id]["predecessors"]:
            if predecessor in by_id:
                walk(predecessor)
        visiting.remove(stage_id)
        visited.add(stage_id)

    for stage_id in by_id:
        walk(stage_id)


def validate_m26_g0(root: Path) -> dict[str, Any]:
    pilot = root / "pilot" / "m26"
    schema_dir = root / "schemas"
    governance_schema = load_json(schema_dir / SCHEMAS["governance_adoption_schema_sha256"])
    pa1_schema = load_json(schema_dir / SCHEMAS["pa1_ratification_schema_sha256"])
    artifacts = {key: load_json(pilot / name) for key, name in ARTIFACTS.items()}
    registry = load_json(pilot / "m26-g0-contract-registry.json")

    for key, value in artifacts.items():
        verify_self_digest(value, key)
        if key != "pa1_ratification_sha256":
            _validate_schema(value, governance_schema, key)
    verify_self_digest(registry, "contract_registry")
    _validate_schema(registry, governance_schema, "contract_registry")
    _validate_schema(artifacts["pa1_ratification_sha256"], pa1_schema, "pa1")

    for key, name in ARTIFACTS.items():
        if registry["artifacts"][key] != object_sha256(artifacts[key]):
            raise GovernanceReconciliationError(f"registry artifact mismatch: {name}")
    for key, name in SCHEMAS.items():
        if registry["schemas"][key] != file_sha256(schema_dir / name):
            raise GovernanceReconciliationError(f"registry schema mismatch: {name}")

    owner = artifacts["owner_decision_sha256"]
    aliases = artifacts["milestone_alias_map_sha256"]
    stages = artifacts["stage_registry_sha256"]
    pa1 = artifacts["pa1_ratification_sha256"]
    legacy = artifacts["legacy_pa2_candidate_sha256"]

    if owner["specification"]["sha256"] != SPEC_SHA or set(owner["denied_authority"]) != DENIED:
        raise GovernanceReconciliationError("owner authority boundary mismatch")
    alias_map = {
        item["historical_label"]: item["canonical_stage_id"]
        for item in aliases["aliases"]
    }
    if alias_map != EXPECTED_ALIASES:
        raise GovernanceReconciliationError("milestone alias map mismatch")
    _verify_graph(stages["stages"])
    by_id = {stage["stage_id"]: stage for stage in stages["stages"]}
    if stages["m25_closed_at_snapshot"] is not True:
        raise GovernanceReconciliationError("formal M25 closure is not bound")
    if set(by_id["M26.PA.2"]["predecessors"]) != {"M26.G0", "M26.PA.1", "M25.closed"}:
        raise GovernanceReconciliationError("PA.2 predecessor chain mismatch")
    if any(set(stage["denied_capabilities"]) != DENIED for stage in stages["stages"]):
        raise GovernanceReconciliationError("stage denied-capability set mismatch")
    if pa1["effective_only_after_status"] != "m26_g0_milestone_reconciliation_accepted":
        raise GovernanceReconciliationError("PA.1 ratification is prematurely effective")
    if pa1["historical_artifact_rewrite"] is not False:
        raise GovernanceReconciliationError("historical rewrite detected")
    if any(pa1["ratified_authority"][name] for name in (
        "live_provider_calls",
        "real_corpus_live_reads",
        "answer_generation",
        "public_traffic",
        "production_pointer_mutation",
        "r2_read_or_write",
        "qdrant_read_or_write",
    )):
        raise GovernanceReconciliationError("PA.1 authority escalation detected")
    if legacy["classification"] != "candidate_patch_only" or legacy["merge_ready"]:
        raise GovernanceReconciliationError("legacy PA.2 branch was elevated")
    if legacy["live_run"] or legacy["acceptance"] or legacy["pull_request_number"] is not None:
        raise GovernanceReconciliationError("legacy PA.2 branch has forbidden authority")

    return {
        "schema_version": "knowledge-engine-m26-g0-governance-evidence/v1",
        "status": "m26_g0_governance_evidence_candidate",
        "accepted": False,
        "accepted_status_reserved_for_reconciliation": "m26_g0_milestone_reconciliation_accepted",
        "pa1_status_reserved_for_reconciliation": (
            "m26_pa_1_production_activation_authority_freeze_accepted"
        ),
        "unified_specification_sha256": SPEC_SHA,
        "alias_count": len(aliases["aliases"]),
        "stage_count": len(stages["stages"]),
        "artifact_digests": registry["artifacts"],
        "schema_digests": registry["schemas"],
        "live_execution": False,
        "secret_access": False,
        "production_mutation": False,
    }


def write_evidence(root: Path, output: Path) -> None:
    output.write_text(canonical_json(validate_m26_g0(root)) + "\n", encoding="utf-8")
