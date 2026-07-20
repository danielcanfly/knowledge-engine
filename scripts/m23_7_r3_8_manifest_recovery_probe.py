from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import httpx

from scripts.m23_7_r3_8_remote_operator import canonical_sha256
from scripts.m23_7_r3_8_remote_recovery_probe import (
    SCHEMA_VERSION,
    _bounded_json,
    classify_control_plane_response,
    reconcile_worker_state,
    required_env,
)
from scripts.m23_7_r3_8_run_authorization import (
    RunAuthorizationError,
    load_authorization,
)

GENERIC_RECEIPT_SCHEMA = "knowledge-engine-m23-7-r3-8-generic-recovery-probe/v1"
CONFIRMATION = "PROBE_R3_8_AUTHORIZED_MANIFEST"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def execute(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    actual_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    if args.confirmation != CONFIRMATION:
        raise RunAuthorizationError("confirmation_mismatch")
    authorization = load_authorization(
        Path(args.authorization_path),
        requested_action="recovery_probe",
        actual_head=actual_head,
    )
    account_id = required_env("CLOUDFLARE_ACCOUNT_ID")
    token = required_env("CLOUDFLARE_API_TOKEN")
    affected_worker = authorization["worker_name"]
    base = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{account_id}/workers/scripts/{affected_worker}"
    )
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
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
        "schema_version": GENERIC_RECEIPT_SCHEMA,
        "legacy_response_schema": SCHEMA_VERSION,
        "status": "completed_read_only_recovery_probe"
        if state in {"worker_absent", "worker_present"}
        else "completed_fail_closed_recovery_probe",
        "authorization_path": args.authorization_path,
        "authorization_sha256": authorization["authorization_sha256"],
        "observation_artifact_sha256": authorization["observation_artifact_sha256"],
        "affected_run_id": authorization["affected_run_id"],
        "affected_engine_sha": authorization["affected_engine_sha"],
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
    _write_json(output_dir / "generic-recovery-probe.json", receipt)
    if state in {"worker_absent", "worker_present"}:
        return 0
    if state == "worker_state_inconsistent":
        return 30
    return 23


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manifest-driven read-only recovery probe for R3.8 runs"
    )
    parser.add_argument("--authorization-path", required=True)
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
            if isinstance(exc, RunAuthorizationError)
            else "bounded_generic_recovery_probe_failure"
        )
        failure = {
            "schema_version": GENERIC_RECEIPT_SCHEMA,
            "status": "rejected_incomplete_recovery_probe",
            "failure_code": code,
            "authorization_path": args.authorization_path,
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
        _write_json(output_dir / "generic-recovery-probe-failure.json", failure)
        return 23


if __name__ == "__main__":
    raise SystemExit(main())
