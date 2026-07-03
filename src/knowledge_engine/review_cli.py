from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings
from .review import (
    ReviewDecisionRequest,
    SourcePackageRequest,
    materialize_source_package,
    record_review_decision,
)
from .storage import create_object_store


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-review")
    commands = parser.add_subparsers(dest="command", required=True)

    decide = commands.add_parser("decide")
    decide.add_argument("--resolution-id", required=True)
    decide.add_argument(
        "--decision",
        choices=("approved", "rejected", "needs_changes"),
        required=True,
    )
    decide.add_argument("--reviewer", required=True)
    decide.add_argument("--reviewed-at", required=True)
    decide.add_argument("--notes", required=True)
    decide.add_argument(
        "--approved-audience",
        choices=("public", "internal", "confidential", "restricted"),
    )
    decide.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".artifacts/review-decision"),
    )

    package = commands.add_parser("package")
    package.add_argument("--decision-id", required=True)
    package.add_argument("--source-root", type=Path, required=True)
    package.add_argument("--source-sha", required=True)
    package.add_argument(
        "--source-repository",
        default="danielcanfly/knowledge-source",
    )
    package.add_argument("--package-version", required=True)
    package.add_argument("--actor", required=True)
    package.add_argument("--packaged-at", required=True)
    package.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".artifacts/source-change-package"),
    )

    args = parser.parse_args()
    store = create_object_store(Settings.from_env())
    if args.command == "decide":
        result = record_review_decision(
            store=store,
            request=ReviewDecisionRequest(
                resolution_id=args.resolution_id,
                decision=args.decision,
                reviewer=args.reviewer,
                reviewed_at=args.reviewed_at,
                notes=args.notes,
                approved_audience=args.approved_audience,
            ),
            output_dir=args.output_dir,
        )
    else:
        result = materialize_source_package(
            store=store,
            request=SourcePackageRequest(
                decision_id=args.decision_id,
                source_repository=args.source_repository,
                source_commit_sha=args.source_sha,
                package_version=args.package_version,
                actor=args.actor,
                packaged_at=args.packaged_at,
            ),
            source_root=args.source_root,
            output_dir=args.output_dir,
        )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
