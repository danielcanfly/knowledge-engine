from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx

AUTHORIZED_RUNS = {
    "29506217284": {
        "engine_sha": "090db324939a4272b90d212fa462674b371b2e6d",
        "worker_name": "knowledge-engine-r3-8-29506217284",
    },
    "29546336917": {
        "engine_sha": "b6c60752741b7079d93b25ddbe16a6582f9db966",
        "worker_name": "knowledge-engine-r3-8-29546336917",
    },
    "29548837457": {
        "engine_sha": "47e16b4981698fb304af48377b93210e841c72e2",
        "worker_name": "knowledge-engine-r3-8-29548837457",
    },
    "29550965495": {
        "engine_sha": "e36559665429514789a6a0122d3b7ac8ff4d5765",
        "worker_name": "knowledge-engine-r3-8-29550965495",
    },
    "29553221650": {
        "engine_sha": "b7ff3c05e8eb2e2c7fcc56c206dd2da678256674",
        "worker_name": "knowledge-engine-r3-8-29553221650",
    },
    "29557251118": {
        "engine_sha": "4729ee2264fdd3650770a9be227606e995973725",
        "worker_name": "knowledge-engine-r3-8-29557251118",
    },
    "29558980092": {
        "engine_sha": "3aca4b793a841858bd0682fe61cc0febe8b649cd",
        "worker_name": "knowledge-engine-r3-8-29558980092",
    },
    "29561411876": {
        "engine_sha": "cb7ecefa8f5a4ac31bdfb71d891b60f3aa51555d",
        "worker_name": "knowledge-engine-r3-8-29561411876",
    },
    "29564569280": {
        "engine_sha": "8cc41a192104d2361d7cf3b388f5fedb6bd1cf56",
        "worker_name": "knowledge-engine-r3-8-29564569280",
    },
    "29568576968": {
        "engine_sha": "11970fc0624f86e30499297dc8154edbb6210163",
        "worker_name": "knowledge-engine-r3-8-29568576968",
    },
    "29568662778": {
        "engine_sha": "11970fc0624f86e30499297dc8154edbb6210163",
        "worker_name": "knowledge-engine-r3-8-29568662778",
    },
    "29572790495": {
        "engine_sha": "53c4b7a230ce73cf49980d605ca905b8a73f50e4",
        "worker_name": "knowledge-engine-r3-8-29572790495",
    },
}
CONFIRMATION_SUFFIX = "_SCHEMA_V2"
SCHEMA_VERSION = "knowledge-engine-m23-7-r3-8-9-recovery-probe/v2"
MAX_RESPONSE_BYTES = 1_000_000
NOT_FOUND_CODES = {10007, 10090}
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")


class RecoveryProbeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RecoveryProbeError(f"missing_{name.lower()}")
    return value


def _error_codes(payload: Any) -> list[int]:
    if not isinstance(payload, dict):
        return []
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return []
    codes: list[int] = []
    for error in errors:
        if isinstance(error, dict) and isinstance(error.get("code"), int):
            codes.append(error["code"])
    return sorted(set(codes))


def _bounded_json(response: httpx.Response) -> Any:
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise RecoveryProbeError("cloudflare_response_oversized")
    try:
        return response.json()
    except ValueError as exc:
        raise RecoveryProbeError("cloudflare_response_not_json") from exc


def _state(
    state: str,
    status_code: int,
    codes: list[int],
    collection_key: str,
    identities: list[str] | None = None,
) -> dict[str, Any]:
    bounded = identities or []
    return {
        "state": state,
        "http_status": status_code,
        "error_codes": codes,
        "collection_key": collection_key,
        "identity_count": len(bounded),
        "identities": bounded,
    }


def classify_control_plane_response(
    status_code: int,
    payload: Any,
    *,
    collection_key: str,
    identity_fields: tuple[str, ...],
) -> dict[str, Any]:
    codes = _error_codes(payload)
    if status_code == 404 and codes and set(codes).issubset(NOT_FOUND_CODES):
        return _state("absent", status_code, codes, collection_key)
    valid_success = (
        status_code == 200
        and isinstance(payload, dict)
        and payload.get("success") is True
        and not codes
    )
    if not valid_success:
        return _state("indeterminate", status_code, codes, collection_key)
    result = payload.get("result")
    if not isinstance(result, dict) or set(result) != {collection_key}:
        return _state("indeterminate", status_code, codes, collection_key)
    collection = result.get(collection_key)
    if not isinstance(collection, list):
        return _state("indeterminate", status_code, codes, collection_key)
    if not collection:
        return _state("absent", status_code, codes, collection_key)

    identities: list[str] = []
    for item in collection:
        if not isinstance(item, dict):
            return _state("indeterminate", status_code, codes, collection_key)
        identity = ""
        for field in identity_fields:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                identity = value.strip()
                break
        if not identity:
            return _state("indeterminate", status_code, codes, collection_key)
        identities.append(identity)
    if len(set(identities)) != len(identities):
        return _state("indeterminate", status_code, codes, collection_key)
    return _state(
        "present",
        status_code,
        codes,
        collection_key,
        sorted(identities),
    )


def reconcile_worker_state(
    versions: dict[str, Any],
    deployments: dict[str, Any],
) -> str:
    states = {versions["state"], deployments["state"]}
    if states == {"absent"}:
        return "worker_absent"
    if states == {"present"}:
        return "worker_present"
    if "indeterminate" in states:
        return "worker_state_indeterminate"
    return "worker_state_inconsistent"


def execute(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    actual_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    authorized = AUTHORIZED_RUNS.get(args.affected_run_id)
    if authorized is None:
        raise RecoveryProbeError("affected_run_identity_mismatch")
    expected_confirmation = f"PROBE_R3_8_RUN_{args.affected_run_id}{CONFIRMATION_SUFFIX}"
    if args.confirmation != expected_confirmation:
        raise RecoveryProbeError("confirmation_mismatch")
    if not _HEX_40.fullmatch(args.expected_head) or args.expected_head != actual_head:
        raise RecoveryProbeError("exact_head_mismatch")

    account_id = required_env("CLOUDFLARE_ACCOUNT_ID")
    token = required_env("CLOUDFLARE_API_TOKEN")
    affected_worker = str(authorized["worker_name"])
    base = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{account_id}/workers/scripts/{affected_worker}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    with httpx.Client(headers=headers, timeout=30.0) as client:
        versions_response = client.get(base + "/versions")
        deployments_response = client.get(base + "/deployments")
    versions = classify_control_plane_response(
        versions_response.status_code,
        _bounded_json(versions_response),
        collection_key="items",
        identity_fields=("id",),
    )
    deployments = classify_control_plane_response(
        deployments_response.status_code,
        _bounded_json(deployments_response),
        collection_key="deployments",
        identity_fields=("id",),
    )
    state = reconcile_worker_state(versions, deployments)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed_read_only_recovery_probe"
        if state in {"worker_absent", "worker_present"}
        else "completed_fail_closed_recovery_probe",
        "affected_run_id": args.affected_run_id,
        "affected_engine_sha": authorized["engine_sha"],
        "probe_engine_sha": actual_head,
        "worker_name": affected_worker,
        "worker_state": state,
        "versions": versions,
        "deployments": deployments,
        "response_schema": {
            "versions_collection": "result.items",
            "deployments_collection": "result.deployments",
        },
        "observation_replayed": False,
        "worker_deploy_dispatched": False,
        "worker_secret_mutation_dispatched": False,
        "worker_delete_dispatched": False,
        "worker_route_invoked": False,
        "qdrant_read_dispatched": False,
        "qdrant_mutation_dispatched": False,
        "r2_read_dispatched": False,
        "r2_mutation_dispatched": False,
        "production_retrieval": "lexical",
        "protected_mutations_dispatched": False,
        "blockers_cleared": False,
    }
    receipt["recovery_probe_sha256"] = canonical_sha256(receipt)
    (output_dir / "remote-recovery-probe.json").write_text(
        canonical_json(receipt) + "\n",
        encoding="utf-8",
    )
    if state in {"worker_absent", "worker_present"}:
        return 0
    if state == "worker_state_inconsistent":
        return 30
    return 23


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only schema-v2 recovery probe for authorized R3.8 runs"
    )
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--affected-run-id", required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        return execute(args)
    except Exception as exc:
        code = (
            exc.code
            if isinstance(exc, RecoveryProbeError)
            else "bounded_recovery_probe_failure"
        )
        authorized = AUTHORIZED_RUNS.get(args.affected_run_id, {})
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "rejected_incomplete_recovery_probe",
            "failure_code": code,
            "affected_run_id": args.affected_run_id,
            "affected_engine_sha": authorized.get("engine_sha"),
            "worker_name": authorized.get("worker_name"),
            "arbitrary_exception_text_persisted": False,
            "credentials_persisted": False,
            "service_url_persisted": False,
            "observation_replayed": False,
            "worker_deploy_dispatched": False,
            "worker_secret_mutation_dispatched": False,
            "worker_delete_dispatched": False,
            "worker_route_invoked": False,
            "qdrant_read_dispatched": False,
            "qdrant_mutation_dispatched": False,
            "r2_read_dispatched": False,
            "r2_mutation_dispatched": False,
            "production_retrieval": "lexical",
            "protected_mutations_dispatched": False,
            "blockers_cleared": False,
        }
        failure["recovery_probe_sha256"] = canonical_sha256(failure)
        (output_dir / "remote-recovery-probe-failure.json").write_text(
            canonical_json(failure) + "\n",
            encoding="utf-8",
        )
        return 23


if __name__ == "__main__":
    raise SystemExit(main())
