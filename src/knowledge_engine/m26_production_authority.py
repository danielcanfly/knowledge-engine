from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class AuthorityContractError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def verify_self_digest(value: dict[str, Any]) -> None:
    expected = value.get("self_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise AuthorityContractError("missing or invalid self_sha256")
    candidate = dict(value)
    candidate["self_sha256"] = ""
    actual = hashlib.sha256(canonical_json(candidate).encode("utf-8")).hexdigest()
    if actual != expected:
        raise AuthorityContractError("self digest mismatch")


def load_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuthorityContractError("contract must be an object")
    verify_self_digest(value)
    return value


def validate_m26_11_contracts(root: Path) -> dict[str, Any]:
    pilot = root / "pilot" / "m26"
    entry = load_contract(pilot / "m26-11-entry-contract.json")
    matrix = load_contract(pilot / "m26-11-authority-matrix.json")
    gates = load_contract(pilot / "m26-11-production-gates.json")
    registry = load_contract(pilot / "m26-11-contract-registry.json")

    if entry["predecessors"]["m26_10_status"] != (
        "m26_10_synthetic_final_authority_gate_accepted"
    ):
        raise AuthorityContractError("M26.10 predecessor is not accepted")

    current = matrix["current_stage_authority"]
    forbidden = {
        "live_provider_calls",
        "real_corpus_answer_execution",
        "verified_final_answers",
        "public_traffic",
        "production_pointer_mutation",
        "source_mutation",
        "foundation_mutation",
        "release_mutation",
        "r2_production_mutation",
        "qdrant_production_mutation",
        "dns_or_access_mutation",
    }
    if any(current[name] for name in forbidden):
        raise AuthorityContractError("M26.11 authority escalation detected")

    if not gates["secret_values_must_not_be_persisted"]:
        raise AuthorityContractError("secret persistence must remain forbidden")
    if len(gates["automatic_stop_conditions"]) < 10:
        raise AuthorityContractError("automatic stop conditions are incomplete")

    expected_files = {
        "entry_contract_sha256": entry,
        "authority_matrix_sha256": matrix,
        "production_gates_sha256": gates,
    }
    for key, value in expected_files.items():
        digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
        if registry["artifacts"][key] != digest:
            raise AuthorityContractError(f"registry mismatch: {key}")

    return {
        "status": "m26_11_contract_valid",
        "stage_count": len(matrix["stages"]),
        "stop_condition_count": len(gates["automatic_stop_conditions"]),
        "secret_name_count": len(gates["required_secret_names"]),
        "public_traffic": False,
        "live_provider_calls": False,
        "production_pointer_mutation": False,
    }
