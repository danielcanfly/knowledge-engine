from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.idempotent_replay_approval import (
    write_replay_approval_validation,
)
from knowledge_engine.idempotent_replay_approval_history import (
    validate_historical_idempotent_replay_approval,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval-path", type=Path, required=True)
    parser.add_argument("--spec-path", type=Path, required=True)
    parser.add_argument("--request-path", type=Path, required=True)
    parser.add_argument("--promotion-observation-path", type=Path, required=True)
    parser.add_argument("--lifecycle-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = validate_historical_idempotent_replay_approval(
        approval_path=args.approval_path,
        spec_path=args.spec_path,
        request_path=args.request_path,
        promotion_observation_path=args.promotion_observation_path,
        lifecycle_path=args.lifecycle_path,
    )
    write_replay_approval_validation(result, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
