from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .m25_identity_benchmark import (
    build_adjudication_ledger,
    build_provisional_suite,
    build_split_manifest,
    digest,
    run_benchmark,
    validate_suite,
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge-m25-identity-benchmark")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate")
    generate.add_argument("--annotation-policy", type=Path, required=True)
    generate.add_argument("--output-dir", type=Path, required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--suite", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--suite", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "generate":
        policy = _read(args.annotation_policy)
        policy_sha = digest(policy)
        suite = build_provisional_suite(policy_sha)
        split = build_split_manifest(suite)
        ledger = build_adjudication_ledger(suite)
        report = run_benchmark(suite)
        _write(args.output_dir / "gold-suite.json", suite)
        _write(args.output_dir / "split-manifest.json", split)
        _write(args.output_dir / "adjudication-ledger.json", ledger)
        _write(args.output_dir / "baseline-report.json", report)
        print(json.dumps({
            "suite_sha256": suite["suite_sha256"],
            "report_sha256": report["report_sha256"],
            "item_count": suite["item_count"],
            "approval_status": suite["approval_status"],
        }, sort_keys=True))
        return 0
    if args.command == "run":
        suite = _read(args.suite)
        report = run_benchmark(suite)
        _write(args.output, report)
        print(json.dumps({
            "suite_sha256": report["suite_sha256"],
            "report_sha256": report["report_sha256"],
            "semantic_decision_accuracy": report["metrics"]["semantic_decision_accuracy"],
            "explanation_signal_coverage": report["metrics"]["explanation_signal_coverage"],
        }, sort_keys=True))
        return 0
    suite = validate_suite(_read(args.suite), require_approval=False)
    print(json.dumps({
        "suite_id": suite["suite_id"],
        "suite_sha256": suite["suite_sha256"],
        "item_count": suite["item_count"],
        "approval_status": suite["approval_status"],
        "m25_5_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
