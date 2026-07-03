from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings
from .resolution import ResolveRequest, resolve_synthesis
from .storage import create_object_store


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-resolution")
    parser.add_argument("--synthesis-id", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument(
        "--source-repository",
        default="danielcanfly/knowledge-source",
    )
    parser.add_argument(
        "--requested-audience",
        choices=("public", "internal", "confidential", "restricted"),
        required=True,
    )
    parser.add_argument("--resolver-version", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--resolved-at", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".artifacts/resolution-review"),
    )
    args = parser.parse_args()

    result = resolve_synthesis(
        store=create_object_store(Settings.from_env()),
        request=ResolveRequest(
            synthesis_id=args.synthesis_id,
            source_repository=args.source_repository,
            source_commit_sha=args.source_sha,
            requested_audience=args.requested_audience,
            resolver_version=args.resolver_version,
            actor=args.actor,
            resolved_at=args.resolved_at,
        ),
        source_root=args.source_root,
        output_dir=args.output_dir,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
