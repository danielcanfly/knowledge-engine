from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from knowledge_engine.errors import IntegrityError
from knowledge_engine.release_checks import validate_runtime_evidence


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"invalid evidence JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise IntegrityError(f"evidence must be a JSON object: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", type=Path, required=True)
    parser.add_argument("--internal", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--expected-release-id", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate_runtime_evidence(
        health=_load(args.health),
        internal=_load(args.internal),
        public=_load(args.public),
        expected_release_id=args.expected_release_id,
        expected_manifest_sha256=args.expected_manifest_sha256,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
