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

AFFECTED_RUN_ID = "29506217284"
AFFECTED_ENGINE_SHA = "090db324939a4272b90d212fa462674b371b2e6d"
AFFECTED_WORKER = "knowledge-engine-r3-8-29506217284"
CONFIRMATION = "PROBE_R3_8_RUN_29506217284"
SCHEMA_VERSION = "knowledge-engine-m23-7-r3-8-8-recovery-probe/v1"
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


def classify_control_plane_response(
    status_code: int,
    payload: Any,
    *,
    identity_fields: tuple[str, ...],
) -> dict[str, Any]:
    codes = _error_codes(payload)
    if status_code == 404 and codes and set(codes).issubset(NOT_FOUND_CODES):
        return {
            "state": "absent",
            "http_status": status_code,
            "error_codes": codes,
            "identity_count": 0,
            "identities": [],
        }
    valid_success = (
        status_code == 200
        and isinstance(payload, dict)
        and payload.get("success") is True
    )
    if not valid_success:
        return {
            "state": "indeterminate",
            "http_status": status_code,
            "error_codes": codes,
            "identity_count": 0,
            "identities": [],
        }
    result = payload.get("result")
    if not isinstance(result, list):
        return {
            "state": "indeterminate",
            "http_status": status_code,
            "error_codes": codes,
            "identity_count": 0,
            "identities": [],
        }
    identities: list[str] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        for field in identity_fields:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                identities.append(value.strip())
                break
    identities = sorted(set(identities))
    return {
        "state": "present",
        "http_status": status_code,
        "error_codes": codes,
        "identity_count": len(identities),
        "identities": identities,
    }


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
    if args.confirmation != CONFIRMATION:
        raise RecoveryProbeError("confirmation_mismatch")
    if not _HEX_40.fullmatch(args.expected_head) or args.expected_head != actual_head:
        raise RecoveryProbeError("exact_head_mismatch")
    if args.affected_run_id != AFFECTED_RUN_ID:
        raise RecoveryProbeError("affected_run_identity_mismatch")

    account_id = required_env("CLOUDFLARE_ACCOUNT_ID")
    token = required_env("CLOUDFLARE_API_TOKEN")
    base = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{account_id}/workers/scripts/{AFFECTED_WORKER}"
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
        identity_fields=("id", "version_id"),
    )
    deployments = classify_control_plane_response(
        deployments_response.status_code,
        _bounded_json(deployments_response),
        identity_fields=("id", "deployment_id"),
    )
    state = reconcile_worker_state(versions, deployments)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed_read_only_recovery_probe"
        if state in {"worker_absent", "worker_present"}
        else "completed_fail_closed_recovery_probe",
        "affected_run_id": AFFECTED_RUN_ID,
        "affected_engine_sha": AFFECTED_ENGINE_SHA,
        "probe_engine_sha": actual_head,
        "worker_name": AFFECTED_WORKER,
        "worker_state": state,
        "versions": versions,
        "deployments": deployments,
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
        description="Read-only recovery probe for R3.8 run 29506217284"
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
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "rejected_incomplete_recovery_probe",
            "failure_code": code,
            "affected_run_id": AFFECTED_RUN_ID,
            "affected_engine_sha": AFFECTED_ENGINE_SHA,
            "worker_name": AFFECTED_WORKER,
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
