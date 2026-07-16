from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
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

AUTH_SCHEMA = "knowledge-engine-m23-7-r3-8-remote-deletion-authorization/v1"
RECEIPT_SCHEMA = "knowledge-engine-m23-7-r3-8-remote-deletion-receipt/v1"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_WORKER = re.compile(r"^knowledge-engine-r3-8-[0-9]{1,20}$")


def validate_authorization(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if len(raw) > 50_000:
        raise RemoteOperatorError("deletion_authorization_oversized")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_version") != AUTH_SCHEMA:
        raise RemoteOperatorError("deletion_authorization_schema")
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
    if not isinstance(value.get("worker_version_id"), str) or not value["worker_version_id"]:
        raise RemoteOperatorError("deletion_worker_version")
    authority = value.get("authority")
    expected = {
        "diagnostic_worker_deletion_authorized": True,
        "production_mutation_authorized": False,
        "qdrant_mutation_authorized": False,
        "r2_mutation_authorized": False,
        "pointer_mutation_authorized": False,
        "source_mutation_authorized": False,
    }
    if authority != expected:
        raise RemoteOperatorError("deletion_authority_boundary")
    return value


def execute(args: argparse.Namespace) -> int:
    if args.confirmation != "DELETE_RECONCILED_R3_8_WORKER":
        raise RemoteOperatorError("deletion_confirmation_mismatch")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual != args.expected_head:
        raise RemoteOperatorError("deletion_exact_head_mismatch")
    auth = validate_authorization(Path(args.authorization_path))
    for name in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "QDRANT_URL"):
        required_env(name)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    worker_name = auth["worker_name"]
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="m23-r3-8-delete-") as temp_name:
        temp = Path(temp_name)
        config = temp / "wrangler.delete.jsonc"
        generate_wrangler_config(required_env("QDRANT_URL"), worker_name, config)
        command = ["npx", "--yes", f"wrangler@{WRANGLER_VERSION}"]
        deleted = subprocess.run(
            command + ["delete", "--name", worker_name, "--config", str(config), "--force"],
            cwd=Path("workers/m23-7-r3-8-latency-repair"),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if deleted.returncode != 0:
            raise RemoteOperatorError(
                "delete_" + classify_wrangler_error(deleted.stdout + deleted.stderr)
            )
        probe = subprocess.run(
            command + ["versions", "list", "--name", worker_name, "--config", str(config), "--json"],
            cwd=Path("workers/m23-7-r3-8-latency-repair"),
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
        "worker_version_id": auth["worker_version_id"],
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete reconciled R3.8 Worker")
    parser.add_argument("--authorization-path", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return execute(parse_args(argv))
    except (RemoteOperatorError, OSError, json.JSONDecodeError):
        return 23


if __name__ == "__main__":
    raise SystemExit(main())
