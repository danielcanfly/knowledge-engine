from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings
from .intake import IntakeRequest, intake_markdown
from .storage import create_object_store


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-intake")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--kind",
        choices=("markdown", "media2md_markdown", "transcript"),
        default="markdown",
    )
    parser.add_argument(
        "--audience",
        choices=("public", "internal", "confidential", "restricted"),
        required=True,
    )
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--content-type", default="text/markdown")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".artifacts/intake-review-packet"),
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    result = intake_markdown(
        store=create_object_store(settings),
        request=IntakeRequest(
            source_id=args.source_id,
            source_uri=args.source_uri,
            title=args.title,
            kind=args.kind,
            audience=args.audience,
            retrieved_at=args.retrieved_at,
            owner=args.owner,
            license=args.license,
            content_type=args.content_type,
        ),
        input_path=args.input,
        output_dir=args.output_dir,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
