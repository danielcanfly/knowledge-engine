from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .m25_identity_governance import (
    build_calibration_policy,
    build_governance_gate,
    run_calibrated_benchmark,
    validate_policy,
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
    parser = argparse.ArgumentParser(prog="knowledge-m25-identity-governance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    policy = subparsers.add_parser("policy")
    policy.add_argument("--suite", type=Path, required=True)
    policy.add_argument("--baseline", type=Path, required=True)
    policy.add_argument("--output", type=Path, required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--suite", type=Path, required=True)
    run.add_argument("--baseline", type=Path, required=True)
    run.add_argument("--policy", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--gate-output", type=Path, required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--policy", type=Path, required=True)
    status.add_argument("--report", type=Path, required=True)
    status.add_argument("--gate", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "policy":
        policy = build_calibration_policy(_read(args.suite), _read(args.baseline))
        _write(args.output, policy)
        print(
            json.dumps(
                {
                    "policy_sha256": policy["policy_sha256"],
                    "calibration_item_count": policy["calibration"]["item_count"],
                    "held_out_item_count": policy["held_out_evaluation"]["item_count"],
                    "final_split_used": policy["calibration"]["final_split_used"],
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "run":
        report = run_calibrated_benchmark(
            _read(args.suite),
            _read(args.baseline),
            validate_policy(_read(args.policy)),
        )
        gate = build_governance_gate(report)
        _write(args.output, report)
        _write(args.gate_output, gate)
        print(
            json.dumps(
                {
                    "report_sha256": report["report_sha256"],
                    "gate_sha256": gate["gate_sha256"],
                    "status": gate["status"],
                    "false_merge_count": report["metrics"]["false_merge_count"],
                    "explanation_signal_coverage": report["metrics"][
                        "explanation_signal_coverage"
                    ],
                },
                sort_keys=True,
            )
        )
        return 0
    policy = validate_policy(_read(args.policy))
    report = _read(args.report)
    gate = _read(args.gate)
    print(
        json.dumps(
            {
                "policy_sha256": policy["policy_sha256"],
                "report_sha256": report["report_sha256"],
                "gate_sha256": gate["gate_sha256"],
                "status": gate["status"],
                "m25_6_authorized": gate["m25_6_authorized"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
