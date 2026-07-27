from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


UNIFIED_V3_SHA256 = "6e71ca5981e3eb45987d188c9c7fb2851a4b5f31803655dd2fc7e28ed4bd22a9"
G0_STAGE_PACKAGE_SHA256 = "65a2e6ae16837c66acf9b79d7f5ffa7e9b4e082d0d2e268ebf508630ef12407a"

GOVERNANCE_SCHEMA = "schemas/m26-g0-governance-adoption-v1.schema.json"
PA1_SCHEMA = "schemas/m26-g0-pa1-ratification-v1.schema.json"

OWNER_DECISION = "pilot/m26/m26-g0-owner-decision.json"
ALIAS_MAP = "pilot/m26/m26-g0-milestone-alias-map.json"
STAGE_REGISTRY = "pilot/m26/m26-g0-stage-registry.json"
PA1_RATIFICATION = "pilot/m26/m26-g0-pa1-ratification.json"
LEGACY_PA2 = "pilot/m26/m26-g0-legacy-pa2-candidate.json"
CONTRACT_REGISTRY = "pilot/m26/m26-g0-contract-registry.json"

M26_9_ACCEPTANCE = "pilot/m26/m26-9-acceptance.json"
M26_10_ACCEPTANCE = "pilot/m26/m26-10-acceptance.json"
M26_11_ACCEPTANCE = "pilot/m26/m26-11-acceptance.json"
M25_RECONCILIATION = "pilot/m25/m25-final-reconciliation.json"

EXPECTED_CHANGED_FILES = frozenset(
    {
        ".github/workflows/m26-g0-milestone-reconciliation.yml",
        "docs/architecture/m26/m26-g0-v3-repository-adoption.md",
        OWNER_DECISION,
        ALIAS_MAP,
        STAGE_REGISTRY,
        PA1_RATIFICATION,
        LEGACY_PA2,
        CONTRACT_REGISTRY,
        GOVERNANCE_SCHEMA,
        PA1_SCHEMA,
        "src/knowledge_engine/m26_governance_reconciliation.py",
        "tests/test_m26_g0_governance_reconciliation.py",
    }
)

PROTECTED_PREFIXES = (
    "source/",
    "foundation/",
    "release/",
    "r2/",
    "qdrant/",
    "production/",
    "channels/",
    "packages/",
    "workers/",
    "pages/",
)

CANONICAL_STATUS_CATALOG = [
    "m26_g0_milestone_reconciliation_accepted",
    "m26_s9_synthetic_qa_preflight_accepted",
    "m26_s10_synthetic_authority_preflight_accepted",
    "m26_pa_1_production_activation_authority_freeze_accepted",
    "m26_pa_2_real_corpus_retrieval_binding_accepted",
    "m26_pa_3_live_provider_execution_accepted",
    "m26_pa_4_verified_answer_citation_gate_accepted",
    "m26_pa_5_controlled_internal_shadow_pilot_accepted",
    "m26_pa_6_canary_slo_rollback_accepted",
    "m26_pa_7_production_answer_authority_and_closure_accepted",
]

EXPECTED_ALIAS_IDENTITIES = {
    "M26.9": (
        "M26.S9",
        "m26_9_candidate_qa_feedback_baseline_refresh_accepted",
        "m26_s9_synthetic_qa_preflight_accepted",
    ),
    "M26.10": (
        "M26.S10",
        "m26_10_synthetic_final_authority_gate_accepted",
        "m26_s10_synthetic_authority_preflight_accepted",
    ),
    "M26.11": (
        "M26.PA.1",
        "m26_11_production_authority_activation_contract_accepted",
        "m26_pa_1_production_activation_authority_freeze_accepted",
    ),
    "M26.12": (
        "M26.PA.2",
        None,
        "m26_pa_2_real_corpus_retrieval_binding_accepted",
    ),
    "M26.13": (
        "M26.PA.3",
        None,
        "m26_pa_3_live_provider_execution_accepted",
    ),
    "M26.14": (
        "M26.PA.4",
        None,
        "m26_pa_4_verified_answer_citation_gate_accepted",
    ),
    "M26.15": (
        "M26.PA.5",
        None,
        "m26_pa_5_controlled_internal_shadow_pilot_accepted",
    ),
    "M26.16": (
        "M26.PA.6",
        None,
        "m26_pa_6_canary_slo_rollback_accepted",
    ),
    "M26.17": (
        "M26.PA.7",
        None,
        "m26_pa_7_production_answer_authority_and_closure_accepted",
    ),
}

LEGACY_PA2_FILES = [
    "pilot/m26/m26-12-contract-registry.json",
    "pilot/m26/m26-12-entry-contract.json",
    "pilot/m26/m26-12-retrieval-policy.json",
    "schemas/m26-12-real-corpus-receipt-v1.schema.json",
    "src/knowledge_engine/m26_real_corpus_binding.py",
    "tests/test_m26_12_real_corpus_binding.py",
]


class GovernanceReconciliationError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceReconciliationError(f"cannot load JSON: {path}") from exc
    if not isinstance(value, dict):
        raise GovernanceReconciliationError(f"JSON root must be object: {path}")
    return value


def verify_self_digest(value: Mapping[str, Any]) -> None:
    expected = value.get("self_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise GovernanceReconciliationError("missing or invalid self_sha256")
    candidate = dict(value)
    candidate["self_sha256"] = ""
    actual = canonical_sha256(candidate)
    if actual != expected:
        raise GovernanceReconciliationError("self digest mismatch")


def validate_schema(instance: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise GovernanceReconciliationError(
            f"schema validation failed at {location}: {first.message}"
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GovernanceReconciliationError(message)


def validate_changed_files(changed_files: Iterable[str]) -> None:
    observed = frozenset(changed_files)
    _require(observed == EXPECTED_CHANGED_FILES, "changed-file allowlist mismatch")
    protected = sorted(
        path for path in observed if path.startswith(PROTECTED_PREFIXES)
    )
    _require(not protected, f"protected mutation path detected: {protected}")


def _validate_acyclic(dag: Mapping[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            raise GovernanceReconciliationError("dependency DAG cycle detected")
        visiting.add(node)
        for dependency in dag.get(node, []):
            if dependency in dag:
                visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in dag:
        visit(node)


def _load_and_validate_new_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    governance_schema = load_json(root / GOVERNANCE_SCHEMA)
    pa1_schema = load_json(root / PA1_SCHEMA)
    artifacts: dict[str, dict[str, Any]] = {}
    for relative_path in (
        OWNER_DECISION,
        ALIAS_MAP,
        STAGE_REGISTRY,
        LEGACY_PA2,
        CONTRACT_REGISTRY,
    ):
        value = load_json(root / relative_path)
        verify_self_digest(value)
        validate_schema(value, governance_schema)
        artifacts[relative_path] = value
    pa1 = load_json(root / PA1_RATIFICATION)
    verify_self_digest(pa1)
    validate_schema(pa1, pa1_schema)
    artifacts[PA1_RATIFICATION] = pa1
    return artifacts


def _validate_owner_decision(owner: Mapping[str, Any], root: Path) -> None:
    _require(
        owner["unified_specification"]["sha256"] == UNIFIED_V3_SHA256,
        "Unified v3 digest mismatch",
    )
    _require(
        owner["g0_stage_package"]["sha256"] == G0_STAGE_PACKAGE_SHA256,
        "G0 stage package digest mismatch",
    )
    _require(owner["no_live_permission"] is True, "owner decision must deny live permission")
    _require(
        all(value is False for value in owner["authority_boundary"].values()),
        "G0 authority escalation detected",
    )
    snapshot = owner["repository_snapshot"]
    _require(
        snapshot["m25_closure_not_inferred_from_pointer"] is True,
        "M25 closure cannot be inferred from pointer promotion",
    )
    m25 = load_json(root / M25_RECONCILIATION)
    _require(m25.get("result") == "m25_closed", "formal M25 reconciliation is not closed")
    _require(
        m25.get("final_acceptance", {}).get("status") == "m25_closed",
        "M25 final acceptance is missing",
    )
    _require(
        m25.get("closure_pr", {}).get("merge_sha")
        == snapshot["m25_reconciliation_merge_sha"],
        "M25 reconciliation merge identity mismatch",
    )


def _validate_alias_map(alias_map: Mapping[str, Any], root: Path) -> None:
    aliases = alias_map["aliases"]
    historical = [entry["historical_label"] for entry in aliases]
    canonical = [entry["canonical_stage_id"] for entry in aliases]
    _require(len(historical) == len(set(historical)), "duplicate historical label")
    _require(len(canonical) == len(set(canonical)), "duplicate canonical stage")
    _require(
        alias_map["canonical_status_catalog"] == CANONICAL_STATUS_CATALOG,
        "canonical status catalog mismatch",
    )
    by_historical = {entry["historical_label"]: entry for entry in aliases}
    _require(set(by_historical) == set(EXPECTED_ALIAS_IDENTITIES), "alias population mismatch")
    for label, expected in EXPECTED_ALIAS_IDENTITIES.items():
        entry = by_historical[label]
        observed = (
            entry["canonical_stage_id"],
            entry["historical_status"],
            entry["canonical_status"],
        )
        _require(observed == expected, f"alias identity mismatch: {label}")
        _require(bool(entry["non_equivalence_warning"]), f"missing warning: {label}")

    s9 = by_historical["M26.9"]
    s10 = by_historical["M26.10"]
    _require("synthetic" in s9["classification"], "M26.9 must remain synthetic")
    _require("synthetic" in s10["classification"], "M26.10 must remain synthetic")
    _require("pilot" in s9["non_equivalence_warning"], "S9 pilot warning missing")
    _require("final_answer" in s10["non_equivalence_warning"], "S10 authority warning missing")

    m26_9 = load_json(root / M26_9_ACCEPTANCE)
    m26_10 = load_json(root / M26_10_ACCEPTANCE)
    _require(
        m26_9.get("status") == s9["historical_status"],
        "historical M26.9 status was replaced",
    )
    _require(
        m26_10.get("status") == s10["historical_status"],
        "historical M26.10 status was replaced",
    )
    _require(
        m26_9.get("implementation", {}).get("pull_request_number") == 1166,
        "M26.9 implementation identity mismatch",
    )
    _require(
        m26_10.get("implementation", {}).get("pull_request_number") == 1170,
        "M26.10 implementation identity mismatch",
    )

    obligations = alias_map["preserved_obligations"]
    _require(
        "frozen_population_between_200_and_500_questions" in obligations["M26.PA.5"],
        "PA.5 pilot denominator obligation missing",
    )
    _require(
        "daniel_explicit_answer_serving_authority_outcome" in obligations["M26.PA.7"],
        "PA.7 final authority obligation missing",
    )


def _validate_stage_registry(registry: Mapping[str, Any]) -> None:
    stages = registry["stages"]
    stage_ids = [stage["stage_id"] for stage in stages]
    statuses = [stage["accepted_status"] for stage in stages]
    _require(len(stage_ids) == len(set(stage_ids)), "duplicate stage ID")
    _require(len(statuses) == len(set(statuses)), "duplicate accepted status")
    _require(statuses == CANONICAL_STATUS_CATALOG, "stage status catalog mismatch")
    by_id = {stage["stage_id"]: stage for stage in stages}
    _require(
        set(by_id)
        == {
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
        },
        "stage registry population mismatch",
    )
    forbidden_g0 = {
        "live_provider_calls",
        "real_corpus_live_reads",
        "answer_generation",
        "shadow_traffic",
        "canary_traffic",
        "public_traffic",
        "production_answer_serving",
        "production_pointer_mutation",
        "secret_access",
        "secret_persistence",
    }
    _require(
        forbidden_g0.issubset(set(by_id["M26.G0"]["denied_capabilities"])),
        "G0 denied capability population incomplete",
    )
    _require(
        set(by_id["M26.PA.2"]["requires"]) == {"M26.G0", "M26.PA.1"},
        "PA.2 predecessor requirements are incomplete",
    )
    _require(
        "m25_closed" in by_id["M26.PA.2"]["daniel_gate"],
        "PA.2 M25 closure live gate missing",
    )
    _require(
        "separate_provider" in by_id["M26.PA.3"]["daniel_gate"],
        "PA.3 Daniel provider gate missing",
    )
    _require(
        "frozen_population_between_200_and_500_questions"
        in by_id["M26.PA.5"]["preserved_obligations"],
        "PA.5 pilot population missing",
    )
    _require(
        "daniel_explicit_answer_serving_authority_outcome"
        in by_id["M26.PA.7"]["preserved_obligations"],
        "PA.7 final Daniel decision missing",
    )
    dag = registry["dependency_dag"]
    _validate_acyclic(dag)
    for stage_id, dependencies in dag.items():
        _require(stage_id in by_id, f"DAG contains unknown stage: {stage_id}")
        _require(
            all(dependency in by_id for dependency in dependencies),
            f"DAG contains unknown dependency for {stage_id}",
        )


def _validate_pa1(pa1: Mapping[str, Any], root: Path) -> None:
    historical = load_json(root / M26_11_ACCEPTANCE)
    identity = pa1["historical_identity"]
    _require(
        historical.get("status") == identity["historical_status"],
        "historical M26.11 status mismatch",
    )
    implementation = historical.get("implementation", {})
    _require(
        implementation.get("pull_request_number") == identity["implementation_pr_number"],
        "PA.1 implementation PR mismatch",
    )
    _require(
        implementation.get("final_head_sha") == identity["implementation_head_sha"],
        "PA.1 implementation head mismatch",
    )
    _require(
        implementation.get("merge_sha") == identity["implementation_merge_sha"],
        "PA.1 implementation merge mismatch",
    )
    _require(
        historical.get("self_sha256") == identity["acceptance_self_sha256"],
        "PA.1 historical acceptance digest mismatch",
    )
    _require(
        historical.get("evidence_artifact", {}).get("artifact_id")
        == pa1["historical_evidence_artifact"]["artifact_id"],
        "PA.1 evidence artifact mismatch",
    )
    ratification = pa1["ratification"]
    _require(ratification["historical_artifacts_rewritten"] is False, "history rewrite detected")
    _require(
        all(
            ratification[key] is False
            for key in (
                "live_authority_granted",
                "provider_authority_granted",
                "real_corpus_live_read_authority_granted",
                "traffic_authority_granted",
                "mutation_authority_granted",
            )
        ),
        "PA.1 live authority escalation detected",
    )
    _require(
        all(value is False for value in pa1["authority_boundary"].values()),
        "PA.1 authority boundary is not closed",
    )


def _validate_legacy_pa2(candidate: Mapping[str, Any]) -> None:
    _require(candidate["issue_number"] == 1176, "legacy issue mismatch")
    _require(
        candidate["branch"] == "chatgpt/m26-12-real-corpus-binding",
        "legacy branch mismatch",
    )
    _require(
        candidate["head_sha"] == "40061ebf66b057dca490708b7abbaa5988b4edb8",
        "legacy head mismatch",
    )
    _require(candidate["files"] == LEGACY_PA2_FILES, "legacy file inventory mismatch")
    _require(candidate["pull_request"] is None, "legacy PR must remain absent")
    _require(candidate["live_run"] is None, "legacy live run must remain absent")
    _require(candidate["acceptance"] is None, "legacy acceptance must remain absent")
    _require(candidate["do_not_merge"] is True, "legacy branch marked merge-ready")
    _require(candidate["do_not_run_live"] is True, "legacy branch marked live-ready")
    _require(
        candidate["repair_required"] == {"P0": True, "P1": True},
        "legacy P0/P1 repair requirement missing",
    )


def _validate_contract_registry(
    contract_registry: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    _require(
        contract_registry["unified_spec_sha256"] == UNIFIED_V3_SHA256,
        "registry Unified v3 digest mismatch",
    )
    _require(
        contract_registry["g0_stage_package_sha256"] == G0_STAGE_PACKAGE_SHA256,
        "registry G0 package digest mismatch",
    )
    expected_paths = {
        OWNER_DECISION,
        ALIAS_MAP,
        STAGE_REGISTRY,
        PA1_RATIFICATION,
        LEGACY_PA2,
    }
    _require(
        set(contract_registry["artifacts"]) == expected_paths,
        "contract registry artifact inventory mismatch",
    )
    for relative_path in sorted(expected_paths):
        expected = canonical_sha256(artifacts[relative_path])
        observed = contract_registry["artifacts"][relative_path]
        _require(observed == expected, f"registry mismatch: {relative_path}")
    _require(
        contract_registry["canonical_status_catalog_sha256"]
        == canonical_sha256(CANONICAL_STATUS_CATALOG),
        "canonical status catalog digest mismatch",
    )


def validate_m26_g0(root: Path) -> dict[str, Any]:
    artifacts = _load_and_validate_new_artifacts(root)
    owner = artifacts[OWNER_DECISION]
    alias_map = artifacts[ALIAS_MAP]
    stage_registry = artifacts[STAGE_REGISTRY]
    pa1 = artifacts[PA1_RATIFICATION]
    legacy = artifacts[LEGACY_PA2]
    contract_registry = artifacts[CONTRACT_REGISTRY]

    _validate_owner_decision(owner, root)
    _validate_alias_map(alias_map, root)
    _validate_stage_registry(stage_registry)
    _validate_pa1(pa1, root)
    _validate_legacy_pa2(legacy)
    _validate_contract_registry(contract_registry, artifacts)

    artifact_digests = {
        path: canonical_sha256(artifacts[path])
        for path in sorted(artifacts)
    }
    return {
        "schema_version": "knowledge-engine-m26-g0-validation-report/v1",
        "status": "m26_g0_governance_adoption_valid",
        "accepted_status_pending_independent_reconciliation": (
            "m26_g0_milestone_reconciliation_accepted"
        ),
        "pa1_status_pending_same_reconciliation": (
            "m26_pa_1_production_activation_authority_freeze_accepted"
        ),
        "unified_spec_sha256": UNIFIED_V3_SHA256,
        "g0_stage_package_sha256": G0_STAGE_PACKAGE_SHA256,
        "base_main_sha": owner["repository_snapshot"]["base_main_sha"],
        "m25_status": "m25_closed",
        "m25_closure_source": M25_RECONCILIATION,
        "artifact_digests": artifact_digests,
        "contract_registry_self_sha256": contract_registry["self_sha256"],
        "canonical_status_catalog_sha256": canonical_sha256(CANONICAL_STATUS_CATALOG),
        "stage_count": len(stage_registry["stages"]),
        "alias_count": len(alias_map["aliases"]),
        "legacy_pa2_classification": "candidate_patch_only",
        "live_execution": False,
        "provider_execution": False,
        "answer_generation": False,
        "production_mutation": False,
        "secret_access": False,
    }
