from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings
from .storage import create_object_store
from .synthesis import SynthesisRequest, prepare_synthesis, validate_synthesis


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-synthesis")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--capture-id", required=True)
    prepare.add_argument("--provider", required=True)
    prepare.add_argument("--model", required=True)
    prepare.add_argument("--model-version", required=True)
    prepare.add_argument("--prompt-version", required=True)
    prepare.add_argument("--harness-version", required=True)
    prepare.add_argument("--seed", type=int, required=True)
    prepare.add_argument("--temperature", type=float, required=True)
    prepare.add_argument("--requested-at", required=True)
    prepare.add_argument("--actor", required=True)
    prepare.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".artifacts/synthesis-request"),
    )

    validate = commands.add_parser("validate")
    validate.add_argument("--request-id", required=True)
    validate.add_argument("--model-output", type=Path, required=True)
    validate.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".artifacts/synthesis-review"),
    )

    args = parser.parse_args()
    store = create_object_store(Settings.from_env())

    if args.command == "prepare":
        result = prepare_synthesis(
            store=store,
            request=SynthesisRequest(
                capture_id=args.capture_id,
                provider=args.provider,
                model=args.model,
                model_version=args.model_version,
                prompt_version=args.prompt_version,
                harness_version=args.harness_version,
                seed=args.seed,
                temperature=args.temperature,
                requested_at=args.requested_at,
                actor=args.actor,
            ),
            output_dir=args.output_dir,
        )
    else:
        result = validate_synthesis(
            store=store,
            request_id=args.request_id,
            model_output_path=args.model_output,
            output_dir=args.output_dir,
        )

    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
