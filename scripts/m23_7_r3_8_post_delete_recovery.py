from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx

from scripts.m23_7_r3_8_remote_recovery_probe import (
    _bounded_json,
    canonical_json,
    canonical_sha256,
    classify_control_plane_response,
    reconcile_worker_state,
)
from scripts.m23_operator_command_bus import (
    OperatorCommandError,
    validate_authorization,
)

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-8-12-post-delete-recovery/v1"
SOURCE_RUN_ID = "29521901629"
SOURCE_ENGINE_SHA = "542907fa0cfae47addd6d777c1708ae62155aea4"
WORKER_NAME = "knowledge-engine-r3-8-29506217284"
PREVIOUS_AUTHORIZATION_PATH = (
    "deletion_authorizations/m23-7/r3-8/"
    "knowledge-engine-r3-8-29506217284.json"
)
_PREVIOUS_AUTH_KEYS = {
    "schema_version",
    "worker_name",
    "observation_run_id",
    "recovery_run_id",
    "receipt_sha256",
    "evidence_seal_sha256",
    "independent_reconciliation_sha256",
    "worker_version_ids",
    "worker_deployment_ids",
    "authority",
    "authorization_sha256",
}


class PostDeleteRecoveryError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise PostDeleteRecoveryError(f"missing_{name.lower()}")
    return value


def load_previous_authorization(repo_root: Path) -> dict[str, Any]:
    path = (repo_root / PREVIOUS_AUTHORIZATION_PATH).resolve()
    root = repo_root.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PostDeleteRecoveryError("previous_authorization_path_escape") from exc
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != _PREVIOUS_AUTH_KEYS:
        raise PostDeleteRecoveryError("previous_authorization_keys")
    if value.get("worker_name") != WORKER_NAME:
        raise PostDeleteRecoveryError("previous_authorization_worker")
    stored = value.get("authorization_sha256")
    unsigned = dict(value)
    unsigned.pop("authorization_sha256", None)
    if not isinstance(stored, str) or stored != canonical_sha256(unsigned):
        raise PostDeleteRecoveryError("previous_authorization_digest")
    return value


def execute(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(args.repo_root).resolve()
    actual_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
    ).strip()
    if actual_head != args.expected_head:
        raise PostDeleteRecoveryError("exact_head_mismatch")

    auth = validate_authorization(
        (repo_root / args.authorization_path).resolve(),
        expected_nonce=args.nonce,
    )
    if auth.get("command_type") != "r3_8_post_delete_recovery":
        raise PostDeleteRecoveryError("command_type_mismatch")
    previous = load_previous_authorization(repo_root)

    account_id = required_env("CLOUDFLARE_ACCOUNT_ID")
    token = required_env("CLOUDFLARE_API_TOKEN")
    base = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{account_id}/workers/scripts/{WORKER_NAME}"
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
        "schema_version": SCHEMA_VERSION,
        "status": (
            "diagnostic_worker_absence_recovered"
            if state == "worker_absent"
            else "completed_fail_closed_post_delete_recovery"
        ),
        "source_deletion_run_id": SOURCE_RUN_ID,
        "source_deletion_engine_sha": SOURCE_ENGINE_SHA,
        "probe_engine_sha": actual_head,
        "worker_name": WORKER_NAME,
        "worker_state": state,
        "versions": versions,
        "deployments": deployments,
        "operator_authorization_sha256": auth["authorization_sha256"],
        "previous_deletion_authorization_sha256": previous["authorization_sha256"],
        "worker_version_ids": previous["worker_version_ids"],
        "worker_deployment_ids": previous["worker_deployment_ids"],
        "control_plane_absence_proven": state == "worker_absent",
        "destructive_deletion_replayed": False,
        "worker_deploy_dispatched": False,
        "worker_secret_mutation_dispatched": False,
        "worker_route_invoked": False,
        "qdrant_read_dispatched": False,
        "qdrant_mutation_dispatched": False,
        "r2_read_dispatched": False,
        "r2_mutation_dispatched": False,
        "pointer_mutation_dispatched": False,
        "source_mutation_dispatched": False,
        "production_retrieval": "lexical",
        "blockers_cleared": False,
        "parent_closure_dispatched": False,
        "m23_7_closure_dispatched": False,
    }
    receipt["post_delete_recovery_sha256"] = canonical_sha256(receipt)
    (output_dir / "post-delete-recovery-receipt.json").write_text(
        canonical_json(receipt) + "\n", encoding="utf-8"
    )
    if state == "worker_absent":
        return 0
    if state in {"worker_present", "worker_state_inconsistent"}:
        return 30
    return 23


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover R3.8 post-delete evidence")
    parser.add_argument("--authorization-path", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        return execute(args)
    except (
        OperatorCommandError,
        PostDeleteRecoveryError,
        OSError,
        json.JSONDecodeError,
        httpx.HTTPError,
    ) as exc:
        code = getattr(exc, "code", "bounded_post_delete_recovery_failure")
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "rejected_incomplete_post_delete_recovery",
            "failure_code": code,
            "source_deletion_run_id": SOURCE_RUN_ID,
            "source_deletion_engine_sha": SOURCE_ENGINE_SHA,
            "worker_name": WORKER_NAME,
            "destructive_deletion_replayed": False,
            "credentials_persisted": False,
            "service_url_persisted": False,
            "arbitrary_exception_text_persisted": False,
            "production_retrieval": "lexical",
            "blockers_cleared": False,
        }
        failure["post_delete_recovery_sha256"] = canonical_sha256(failure)
        (output_dir / "post-delete-recovery-failure.json").write_text(
            canonical_json(failure) + "\n", encoding="utf-8"
        )
        return 23


if __name__ == "__main__":
    raise SystemExit(main())
