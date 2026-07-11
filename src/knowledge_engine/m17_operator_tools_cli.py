from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings
from .m17_operator_tools import (
    build_batch_status_report,
    build_checklist_report,
    build_doctor_report,
    build_production_status_report,
    compare_release_manifests,
    fetch_artifact,
    generate_handoff,
    generate_incident_bundle,
    summarize_ledger_export,
    verify_evidence_file,
)
from .storage import create_object_store


def _paths(values: list[str]) -> list[Path]:
    return [Path(item) for item in values]


def _print(payload: dict[str, object]) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("status") == "passed" else 2


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-inspect")
    commands = parser.add_subparsers(dest="command", required=True)

    checklist = commands.add_parser("checklist")
    checklist.add_argument(
        "--registry",
        type=Path,
        default=Path("docs/operations/m17/runbook-registry.json"),
    )

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--root", type=Path, default=Path("."))

    batch_status = commands.add_parser("batch-status")
    batch_status.add_argument("--input", type=Path, required=True)

    production_status = commands.add_parser("production-status")
    production_status.add_argument("--channel", default=None)
    production_status.add_argument("--max-artifacts", type=int, default=512)

    artifact_fetch = commands.add_parser("artifact-fetch")
    artifact_fetch.add_argument("--key", required=True)
    artifact_fetch.add_argument("--output-dir", type=Path, required=True)
    artifact_fetch.add_argument("--expected-sha256")
    artifact_fetch.add_argument("--max-bytes", type=int, default=32_000_000)

    evidence_verify = commands.add_parser("evidence-verify")
    evidence_verify.add_argument("--input", type=Path, required=True)

    release_compare = commands.add_parser("release-compare")
    release_compare.add_argument("--left", type=Path, required=True)
    release_compare.add_argument("--right", type=Path, required=True)

    ledger_summarize = commands.add_parser("ledger-summarize")
    ledger_summarize.add_argument("--input", type=Path, required=True)
    ledger_summarize.add_argument("--max-entries", type=int, default=5000)

    incident_bundle = commands.add_parser("incident-bundle")
    incident_bundle.add_argument("--incident-id", required=True)
    incident_bundle.add_argument("--failure-id", required=True)
    incident_bundle.add_argument("--evidence", nargs="+", required=True)
    incident_bundle.add_argument("--output", type=Path, required=True)

    handoff = commands.add_parser("handoff-generate")
    handoff.add_argument("--handoff-id", required=True)
    handoff.add_argument("--components", nargs="+", required=True)
    handoff.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()

    try:
        if args.command == "checklist":
            return _print(build_checklist_report(args.registry))
        if args.command == "doctor":
            return _print(build_doctor_report(args.root))
        if args.command == "batch-status":
            return _print(build_batch_status_report(args.input))
        if args.command == "evidence-verify":
            return _print(verify_evidence_file(args.input))
        if args.command == "release-compare":
            return _print(compare_release_manifests(args.left, args.right))
        if args.command == "ledger-summarize":
            return _print(summarize_ledger_export(args.input, max_entries=args.max_entries))
        if args.command == "incident-bundle":
            return _print(
                generate_incident_bundle(
                    _paths(args.evidence),
                    args.output,
                    incident_id=args.incident_id,
                    failure_id=args.failure_id,
                )
            )
        if args.command == "handoff-generate":
            return _print(
                generate_handoff(
                    _paths(args.components),
                    args.output,
                    handoff_id=args.handoff_id,
                )
            )

        settings = Settings.from_env()
        store = create_object_store(settings)
        if args.command == "production-status":
            return _print(
                build_production_status_report(
                    store,
                    args.channel or settings.channel,
                    max_artifacts=args.max_artifacts,
                )
            )
        if args.command == "artifact-fetch":
            return _print(
                fetch_artifact(
                    store,
                    args.key,
                    args.output_dir,
                    expected_sha256=args.expected_sha256,
                    max_bytes=args.max_bytes,
                )
            )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "knowledge-engine-m17-operator-tooling-error/v1",
                    "status": "blocked",
                    "tool": args.command,
                    "error_code": exc.__class__.__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
