from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from knowledge_engine.batch_lifecycle import next_action
from knowledge_engine.batch_registry import load_batch_registry, validate_batch_registry
from knowledge_engine.batch_spec import load_batch_spec, validate_transition


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _evidence(
    transitions: list[dict[str, Any]], source: str, target: str
) -> dict[str, Any]:
    for item in transitions:
        if item.get("from") == source and item.get("to") == target:
            value = item.get("evidence")
            if isinstance(value, dict):
                return value
    raise ValueError(f"missing transition {source} -> {target}")


def validate_closure(
    *, history_path: Path, spec_path: Path, registry_path: Path, baseline_path: Path
) -> dict[str, Any]:
    history = _load(history_path)
    spec = load_batch_spec(spec_path)
    registry = validate_batch_registry(load_batch_registry(registry_path))
    baseline_file = _load(baseline_path)

    if spec.lifecycle_state != "closed":
        raise ValueError("batch is not closed")
    if history.get("initial_state") != "planned":
        raise ValueError("history must start at planned")

    transitions = history.get("transitions")
    if not isinstance(transitions, list) or len(transitions) != 7:
        raise ValueError("closure requires seven transitions")

    current = "planned"
    for index, item in enumerate(transitions):
        if item.get("from") != current:
            raise ValueError(f"transition {index} is not contiguous")
        target = str(item.get("to"))
        validate_transition(current, target)
        if not isinstance(item.get("evidence"), dict) or not item["evidence"]:
            raise ValueError(f"transition {index} has no evidence")
        current = target

    if current != "closed" or history.get("final_state") != "closed":
        raise ValueError("history does not end at closed")
    if registry["batches"][0]["lifecycle_state"] != "closed":
        raise ValueError("registry is not closed")

    candidate = spec.raw["candidate"]
    baseline = history.get("production_baseline")
    target = history.get("production_target")
    if not isinstance(baseline, dict) or not isinstance(target, dict):
        raise ValueError("production identities are incomplete")
    if baseline.get("release_id") != baseline_file.get("release_id"):
        raise ValueError("baseline release drift")
    if baseline.get("manifest_sha256") != baseline_file.get("manifest_sha256"):
        raise ValueError("baseline manifest drift")
    if target.get("release_id") != candidate["release_id"]:
        raise ValueError("target release mismatch")
    if target.get("manifest_sha256") != candidate["manifest_sha256"]:
        raise ValueError("target manifest mismatch")
    pointer_sha = target.get("pointer_sha256")
    if not isinstance(pointer_sha, str) or len(pointer_sha) != 64:
        raise ValueError("target pointer SHA is invalid")
    if history.get("production_mutated") is not True:
        raise ValueError("promotion was not recorded")

    promotion = _evidence(
        transitions, "request_spec_committed", "production_promoted"
    )
    if promotion.get("promotion_status") != "promoted":
        raise ValueError("initial promotion status mismatch")
    if promotion.get("idempotent") is not False:
        raise ValueError("initial promotion idempotency mismatch")
    if promotion.get("production_pointer_sha256") != pointer_sha:
        raise ValueError("initial pointer mismatch")

    replay = _evidence(transitions, "production_promoted", "closed")
    expected_replay = {
        "precondition_state": "already_target",
        "promotion_status": "already_promoted",
        "idempotent": True,
        "public_query_status": "answered",
        "acl_query_status": "not_found",
        "raw_fallback_used": False,
    }
    for field, expected in expected_replay.items():
        if replay.get(field) != expected:
            raise ValueError(f"replay evidence mismatch: {field}")
    if int(replay.get("acl_filtered_count", 0)) < 1:
        raise ValueError("replay did not prove ACL filtering")
    if replay.get("production_pointer_sha256") != pointer_sha:
        raise ValueError("replay pointer mismatch")

    action = next_action(spec.lifecycle_state)
    if action != "start_next_batch":
        raise ValueError("unexpected next action")

    return {
        "schema_version": "m8-closure-validation/v1",
        "status": "passed",
        "batch_id": spec.batch_id,
        "lifecycle_state": "closed",
        "transition_count": 7,
        "production_baseline": baseline,
        "production_target": target,
        "promotion_run": promotion["promotion_run"],
        "replay_run": replay["replay_run"],
        "replay_attempt": replay["replay_attempt"],
        "idempotent_replay": True,
        "production_mutated": True,
        "next_action": action,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate_closure(
        history_path=args.history,
        spec_path=args.spec,
        registry_path=args.registry,
        baseline_path=args.baseline,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
