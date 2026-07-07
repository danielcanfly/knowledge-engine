from __future__ import annotations

import argparse
import json
from pathlib import Path

from .batch_registry import load_batch_registry, write_registry_evidence
from .batch_spec import REGISTRY_PATH, load_batch_spec, validate_transition
from .operator_preflight import run_operator_preflight, write_preflight_evidence
from .scale_readiness import run_scale_readiness, write_readiness_evidence


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-batch")
    subcommands = parser.add_subparsers(dest="command", required=True)

    validate = subcommands.add_parser("validate")
    validate.add_argument("--registry-path", type=Path, default=REGISTRY_PATH)
    validate.add_argument("--evidence-dir", type=Path, default=Path("evidence"))

    inspect = subcommands.add_parser("inspect")
    inspect.add_argument("--spec-path", type=Path, required=True)

    check = subcommands.add_parser("check-transition")
    check.add_argument("--current", required=True)
    check.add_argument("--target", required=True)

    preflight = subcommands.add_parser("preflight")
    preflight.add_argument("--spec-path", type=Path, required=True)
    preflight.add_argument("--registry-path", type=Path, default=REGISTRY_PATH)
    preflight.add_argument("--require-env", action="append", default=[])
    preflight.add_argument("--allow-dirty", action="store_true")
    preflight.add_argument("--production-pointer-path", type=Path)
    preflight.add_argument(
        "--output",
        type=Path,
        default=Path("evidence/operator-preflight.json"),
    )

    readiness = subcommands.add_parser("readiness")
    readiness.add_argument("--registry-path", type=Path, default=REGISTRY_PATH)
    readiness.add_argument("--production-pointer-path", type=Path, required=True)
    readiness.add_argument("--expected-release-id", required=True)
    readiness.add_argument("--expected-manifest-sha256", required=True)
    readiness.add_argument("--workflow-health-path", type=Path, required=True)
    readiness.add_argument(
        "--output",
        type=Path,
        default=Path("evidence/scale-readiness.json"),
    )

    args = parser.parse_args()
    if args.command == "validate":
        result = write_registry_evidence(
            registry=load_batch_registry(args.registry_path),
            evidence_dir=args.evidence_dir,
        )
    elif args.command == "inspect":
        spec = load_batch_spec(args.spec_path)
        result = {
            "status": "valid",
            "batch_id": spec.batch_id,
            "lifecycle_state": spec.lifecycle_state,
        }
    elif args.command == "check-transition":
        validate_transition(args.current, args.target)
        result = {"status": "valid", "current": args.current, "target": args.target}
    elif args.command == "preflight":
        result = run_operator_preflight(
            spec_path=args.spec_path,
            registry_path=args.registry_path,
            required_env=args.require_env,
            allow_dirty=args.allow_dirty,
            production_pointer_path=args.production_pointer_path,
        )
        write_preflight_evidence(result, args.output)
    else:
        result = run_scale_readiness(
            registry_path=args.registry_path,
            production_pointer_path=args.production_pointer_path,
            expected_release_id=args.expected_release_id,
            expected_manifest_sha256=args.expected_manifest_sha256,
            workflow_health_path=args.workflow_health_path,
        )
        write_readiness_evidence(result, args.output)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
