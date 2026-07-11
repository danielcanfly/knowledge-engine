from __future__ import annotations

import argparse
import json
from pathlib import Path

from .m17_operator_qualification import assess_submission, build_training_plan

DEFAULT_REGISTRY = Path("docs/operations/m17/training-registry.json")


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-qualify")
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan")
    plan.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)

    assess = commands.add_parser("assess")
    assess.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    assess.add_argument("--submission", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "plan":
        report = build_training_plan(args.registry)
    else:
        report = assess_submission(args.registry, args.submission)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"passed", "qualified"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
