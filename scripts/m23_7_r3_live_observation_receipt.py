from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from scripts.m23_operator_command_bus import (
    OperatorCommandError,
    canonical_json,
    canonical_sha256,
    validate_authorization,
)

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-live-observation-receipt/v1"
COMMAND_TYPE = "r3_live_reobservation"
WORKER_PREFIX = "knowledge-engine-m23-7-r3-live"


class LiveObservationReceiptError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise LiveObservationReceiptError(f"missing_{name.lower()}")
    return value


def _worker_name(value: str) -> str:
    if not re.fullmatch(r"knowledge-engine-m23-7-r3-live-[a-z0-9-]{6,24}", value):
        raise LiveObservationReceiptError("worker_name_invalid")
    return value


def _load_report(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LiveObservationReceiptError("report_shape")
    stored = value.get("report_sha256")
    unsigned = dict(value)
    unsigned.pop("report_sha256", None)
    if not isinstance(stored, str) or stored != canonical_sha256(unsigned):
        raise LiveObservationReceiptError("report_digest")
    return value


def _actual_head(repo_root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
    ).strip()


def build_receipt(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    actual_head = _actual_head(repo_root)
    if actual_head != args.expected_head:
        raise LiveObservationReceiptError("exact_head_mismatch")
    worker_name = _worker_name(_required_env("M23_R3_TRANSIENT_WORKER_NAME"))
    auth = validate_authorization(
        (repo_root / args.authorization_path).resolve(),
        expected_nonce=args.nonce,
    )
    if auth.get("command_type") != COMMAND_TYPE:
        raise LiveObservationReceiptError("command_type_mismatch")
    if not worker_name.startswith(auth["worker_name_prefix"] + "-"):
        raise LiveObservationReceiptError("worker_prefix_mismatch")
    report = _load_report(Path(args.report_path))
    deletion_completed = args.deletion_completed == "true"
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "pass_live_observation_pending_reconciliation"
            if report["status"] == "pass_bounded_live_reobservation"
            else "rejected_live_observation_pending_reconciliation"
        ),
        "command_type": COMMAND_TYPE,
        "issue_number": 595,
        "probe_engine_sha": actual_head,
        "worker_name_sha256": canonical_sha256(worker_name),
        "worker_name_prefix": WORKER_PREFIX,
        "transient_worker_deploy_dispatched": True,
        "transient_worker_secret_mutation_dispatched": True,
        "transient_worker_route_invoked": True,
        "transient_worker_delete_dispatched": True,
        "transient_worker_deletion_completed": deletion_completed,
        "report_sha256": report["report_sha256"],
        "report_status": report["status"],
        "metrics": report["metrics"],
        "gates": report["gates"],
        "remaining_blockers": report["remaining_blockers"],
        "operator_authorization_sha256": auth["authorization_sha256"],
        "production_retrieval": "lexical",
        "qdrant_write_dispatched": False,
        "r2_mutation_dispatched": False,
        "pointer_mutation_dispatched": False,
        "source_mutation_dispatched": False,
        "blockers_cleared": False,
        "parent_closure_dispatched": False,
        "m23_7_closure_dispatched": False,
        "privacy": {
            "worker_url_persisted": False,
            "service_url_persisted": False,
            "service_hostname_persisted": False,
            "credentials_persisted": False,
            "raw_queries_persisted": False,
            "raw_answers_persisted": False,
            "arbitrary_exception_text_persisted": False,
        },
    }
    receipt["live_observation_receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seal an R3 live observation receipt")
    parser.add_argument("--authorization-path", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--report-path", required=True)
    parser.add_argument("--deletion-completed", choices=("true", "false"), required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        receipt = build_receipt(args)
        output.write_text(canonical_json(receipt) + "\n", encoding="utf-8")
        return 0
    except (
        LiveObservationReceiptError,
        OperatorCommandError,
        OSError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as exc:
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "rejected_incomplete_live_observation",
            "failure_code": getattr(exc, "code", "bounded_live_observation_failure"),
            "command_type": COMMAND_TYPE,
            "issue_number": 595,
            "production_retrieval": "lexical",
            "blockers_cleared": False,
            "credentials_persisted": False,
            "service_url_persisted": False,
            "arbitrary_exception_text_persisted": False,
        }
        failure["live_observation_receipt_sha256"] = canonical_sha256(failure)
        output.write_text(canonical_json(failure) + "\n", encoding="utf-8")
        return 23


if __name__ == "__main__":
    raise SystemExit(main())
