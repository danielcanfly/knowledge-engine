from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from knowledge_engine.batch_lifecycle import next_action
from knowledge_engine.batch_registry import load_batch_registry, validate_batch_registry
from knowledge_engine.batch_spec import load_batch_spec, validate_transition


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def validate_history(
    *,
    history_path: Path,
    spec_path: Path,
    registry_path: Path,
    production_pointer_path: Path,
) -> dict[str, Any]:
    history = _load_object(history_path)
    spec = load_batch_spec(spec_path)
    registry = validate_batch_registry(load_batch_registry(registry_path))
    pointer = _load_object(production_pointer_path)

    if history.get("schema_version") != "m8-lifecycle-history/v1":
        raise ValueError("invalid lifecycle history schema")
    if history.get("batch_id") != spec.batch_id:
        raise ValueError("history batch_id mismatch")
    if history.get("initial_state") != "planned":
        raise ValueError("history must start at planned")

    transitions = history.get("transitions")
    if not isinstance(transitions, list) or not transitions:
        raise ValueError("history transitions must be a non-empty list")

    current = history["initial_state"]
    for index, item in enumerate(transitions):
        if not isinstance(item, dict):
            raise ValueError(f"transition {index} must be an object")
        source = item.get("from")
        target = item.get("to")
        if source != current:
            raise ValueError(f"transition {index} does not continue from {current}")
        validate_transition(str(source), str(target))
        evidence = item.get("evidence")
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError(f"transition {index} must include evidence")
        current = str(target)

    if current != history.get("final_state"):
        raise ValueError("history final_state mismatch")
    if current != spec.lifecycle_state:
        raise ValueError("history and spec lifecycle states differ")

    source_sha = spec.raw["source"]["sha"]
    candidate = spec.raw["candidate"]
    if history.get("source_identity") != {"sha": source_sha}:
        raise ValueError("history source identity mismatch")
    if history.get("candidate_identity") != candidate:
        raise ValueError("history candidate identity mismatch")

    baseline = history.get("production_baseline")
    if not isinstance(baseline, dict):
        raise ValueError("production baseline is required")
    if baseline.get("release_id") != pointer.get("release_id"):
        raise ValueError("production release baseline drift")
    if baseline.get("manifest_sha256") != pointer.get("manifest_sha256"):
        raise ValueError("production manifest baseline drift")
    if history.get("production_mutated") is not False:
        raise ValueError("history must prove production was not mutated")

    if registry.get("batch_count") != 1:
        raise ValueError("M8 registry must contain exactly one batch")
    if registry["batches"][0]["lifecycle_state"] != spec.lifecycle_state:
        raise ValueError("registry lifecycle state mismatch")

    action = next_action(spec.lifecycle_state)

    return {
        "schema_version": "m8-lifecycle-reconciliation/v1",
        "status": "passed",
        "batch_id": spec.batch_id,
        "lifecycle_state": spec.lifecycle_state,
        "transition_count": len(transitions),
        "source_sha": source_sha,
        "candidate": candidate,
        "production_baseline": baseline,
        "production_mutated": False,
        "next_action": action,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--production-pointer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = validate_history(
        history_path=args.history,
        spec_path=args.spec,
        registry_path=args.registry,
        production_pointer_path=args.production_pointer,
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
