from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from scripts.m23_7_r3_8_remote_operator import (
    WRANGLER_VERSION,
    RemoteOperatorError,
    canonical_json,
    canonical_sha256,
    classify_wrangler_error,
    generate_wrangler_config,
    required_env,
)

AUTH_SCHEMA = "knowledge-engine-m23-7-r3-8-remote-deletion-authorization/v2"
RECEIPT_SCHEMA = "knowledge-engine-m23-7-r3-8-remote-deletion-receipt/v2"
FAILURE_SCHEMA = "knowledge-engine-m23-7-r3-8-remote-deletion-failure/v1"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_WORKER = re.compile(r"^knowledge-engine-r3-8-[0-9]{1,20}$")
_RUN_ID = re.compile(r"^[0-9]{1,20}$")
_CONTROL_PLANE_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_AUTH_KEYS = {
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


def _validate_identity_list(value: Any, failure_code: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RemoteOperatorError(failure_code)
    if any(
        not isinstance(identity, str) or not _CONTROL_PLANE_ID.fullmatch(identity)
        for identity in value
    ):
        raise RemoteOperatorError(failure_code)
    if value != sorted(value) or len(value) != len(set(value)):
        raise RemoteOperatorError(failure_code)
    return value


def validate_authorization(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if len(raw) > 50_000:
        raise RemoteOperatorError("deletion_authorization_oversized")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_version") != AUTH_SCHEMA:
        raise RemoteOperatorError("deletion_authorization_schema")
    if set(value) != _AUTH_KEYS:
        raise RemoteOperatorError("deletion_authorization_keys")
    stored = value.get("authorization_sha256")
    unsigned = dict(value)
    unsigned.pop("authorization_sha256", None)
    if not isinstance(stored, str) or stored != canonical_sha256(unsigned):
        raise RemoteOperatorError("deletion_authorization_digest")
    for field in (
        "receipt_sha256",
        "evidence_seal_sha256",
        "independent_reconciliation_sha256",
    ):
        if not isinstance(value.get(field), str) or not _HEX_64.fullmatch(value[field]):
            raise RemoteOperatorError("deletion_authorization_identity")
    if not isinstance(value.get("worker_name"), str) or not _WORKER.fullmatch(
        value["worker_name"]
    ):
        raise RemoteOperatorError("deletion_worker_name")
    for field in ("observation_run_id", "recovery_run_id"):
        if not isinstance(value.get(field), str) or not _RUN_ID.fullmatch(value[field]):
            raise RemoteOperatorError("deletion_run_identity")
    _validate_identity_list(value.get("worker_version_ids"), "deletion_worker_versions")
    _validate_identity_list(
        value.get("worker_deployment_ids"), "deletion_worker_deployments"
    )
    expected_authority = {
        "diagnostic_worker_deletion_authorized": True,
        "production_mutation_authorized": False,
        "qdrant_mutation_authorized": False,
        "r2_mutation_authorized": False,
        "pointer_mutation_authorized": False,
        "source_mutation_authorized": False,
    }
    if value.get("authority") != expected_authority:
        raise RemoteOperatorError("deletion_authority_boundary")
    return value


def build_delete_command(worker_name: str, config: Path) -> list[str]:
    if not _WORKER.fullmatch(worker_name):
        raise RemoteOperatorError("deletion_worker_name")
    return [
        "npx",
        "--yes",
        f"wrangler@{WRANGLER_VERSION}",
        "delete",
        worker_name,
        "--config",
        str(config),
        "--force",
    ]


def execute(args: argparse.Namespace) -> int:
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    actual = "unknown"
    stage = "preflight"
    worker_name = "unknown"
    auth: dict[str, Any] | None = None
    worker_delete_dispatched = False
    absence_probe_dispatched = False
    try:
        if args.confirmation != "DELETE_RECONCILED_R3_8_WORKER":
            raise RemoteOperatorError("deletion_confirmation_mismatch")
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        if actual != args.expected_head:
            raise RemoteOperatorError("deletion_exact_head_mismatch")
        auth = validate_authorization(Path(args.authorization_path))
        worker_name = auth["worker_name"]
        for name in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "QDRANT_URL"):
            required_env(name)

        worker_dir = Path("workers/m23-7-r3-8-latency-repair").resolve()
        config = worker_dir / f"wrangler.delete.{worker_name}.jsonc"
        env = os.environ.copy()
        command = ["npx", "--yes", f"wrangler@{WRANGLER_VERSION}"]

        generate_wrangler_config(required_env("QDRANT_URL"), worker_name, config)
        stage = "worker_delete"
        worker_delete_dispatched = True
        deleted = subprocess.run(
            build_delete_command(worker_name, config),
            cwd=worker_dir,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if deleted.returncode != 0:
            raise RemoteOperatorError(
                "delete_" + classify_wrangler_error(deleted.stdout + deleted.stderr)
            )
        stage = "absence_probe"
        absence_probe_dispatched = True
        probe = subprocess.run(
            command
            + [
                "versions",
                "list",
                "--name",
                worker_name,
                "--config",
                str(config),
                "--json",
            ],
            cwd=worker_dir,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        classification = classify_wrangler_error(probe.stdout + probe.stderr)
        if probe.returncode == 0 or classification != "worker_not_found":
            raise RemoteOperatorError("delete_absence_not_proven")

        receipt = {
            "schema_version": RECEIPT_SCHEMA,
            "status": "diagnostic_worker_deleted_and_absence_proven",
            "engine_sha": actual,
            "worker_name": worker_name,
            "observation_run_id": auth["observation_run_id"],
            "recovery_run_id": auth["recovery_run_id"],
            "worker_version_ids": auth["worker_version_ids"],
            "worker_deployment_ids": auth["worker_deployment_ids"],
            "receipt_sha256": auth["receipt_sha256"],
            "evidence_seal_sha256": auth["evidence_seal_sha256"],
            "independent_reconciliation_sha256": auth[
                "independent_reconciliation_sha256"
            ],
            "control_plane_absence_proven": True,
            "production_retrieval": "lexical",
            "protected_mutations_dispatched": False,
            "qdrant_mutation_dispatched": False,
            "r2_mutation_dispatched": False,
            "pointer_mutation_dispatched": False,
            "source_mutation_dispatched": False,
        }
        receipt["deletion_receipt_sha256"] = canonical_sha256(receipt)
        (output / "remote-deletion-receipt.json").write_text(
            canonical_json(receipt) + "\n", encoding="utf-8"
        )
        return 0
    except (RemoteOperatorError, OSError, json.JSONDecodeError) as exc:
        code = exc.code if isinstance(exc, RemoteOperatorError) else "bounded_failure"
        failure = {
            "schema_version": FAILURE_SCHEMA,
            "status": "rejected_remote_deletion_failure",
            "failure_code": code,
            "failure_stage": stage,
            "engine_sha": actual,
            "authorization_path": args.authorization_path,
            "worker_name": worker_name,
            "observation_run_id": auth.get("observation_run_id") if auth else None,
            "recovery_run_id": auth.get("recovery_run_id") if auth else None,
            "receipt_sha256": auth.get("receipt_sha256") if auth else None,
            "evidence_seal_sha256": auth.get("evidence_seal_sha256") if auth else None,
            "independent_reconciliation_sha256": (
                auth.get("independent_reconciliation_sha256") if auth else None
            ),
            "worker_delete_dispatched": worker_delete_dispatched,
            "absence_probe_dispatched": absence_probe_dispatched,
            "control_plane_absence_proven": False,
            "production_retrieval": "lexical",
            "protected_mutations_dispatched": False,
            "qdrant_mutation_dispatched": False,
            "r2_mutation_dispatched": False,
            "pointer_mutation_dispatched": False,
            "source_mutation_dispatched": False,
            "arbitrary_exception_text_persisted": False,
        }
        failure["deletion_failure_sha256"] = canonical_sha256(failure)
        (output / "remote-deletion-failure.json").write_text(
            canonical_json(failure) + "\n", encoding="utf-8"
        )
        return 23
    finally:
        if "config" in locals():
            config.unlink(missing_ok=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete reconciled R3.8 Worker")
    parser.add_argument("--authorization-path", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return execute(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
