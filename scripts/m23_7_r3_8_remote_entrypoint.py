from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any

ENTRY_SCHEMA = "knowledge-engine-m23-7-r3-8-remote-entrypoint/v1"


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


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded R3.8 remote operator entrypoint")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--evidence-key", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    actual_head = "unknown"
    with suppress(OSError, subprocess.SubprocessError):
        actual_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()

    entry = {
        "schema_version": ENTRY_SCHEMA,
        "status": "operator_entry_started",
        "github_run_id": args.run_id,
        "github_run_attempt": args.run_attempt,
        "expected_head": args.expected_head,
        "actual_head": actual_head,
        "credentials_persisted": False,
        "service_url_persisted": False,
        "raw_evidence_persisted": False,
        "production_retrieval": "lexical",
        "protected_mutations_dispatched": False,
        "blockers_cleared": False,
    }
    entry["entry_sha256"] = canonical_sha256(entry)
    write_json(output_dir / "remote-entry.json", entry)

    try:
        from scripts import m23_7_r3_8_remote_operator as operator

        return operator.execute(args)
    except Exception:
        failure = {
            "schema_version": ENTRY_SCHEMA,
            "status": "rejected_incomplete_remote_observation",
            "failure_code": "bounded_remote_entrypoint_failure",
            "failure_stage": "remote_entrypoint",
            "github_run_id": args.run_id,
            "github_run_attempt": args.run_attempt,
            "expected_head": args.expected_head,
            "actual_head": actual_head,
            "arbitrary_exception_text_persisted": False,
            "credentials_persisted": False,
            "service_url_persisted": False,
            "raw_evidence_persisted": False,
            "worker_deployed": False,
            "worker_state_known": False,
            "production_retrieval": "lexical",
            "protected_mutations_dispatched": False,
            "blockers_cleared": False,
        }
        failure["failure_sha256"] = canonical_sha256(failure)
        write_json(output_dir / "remote-entry-failure.json", failure)
        return 23


if __name__ == "__main__":
    raise SystemExit(main())
