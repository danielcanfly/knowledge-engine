from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.batch_lifecycle import next_action
from knowledge_engine.batch_registry import load_batch_registry, validate_batch_registry
from knowledge_engine.batch_spec import load_batch_spec

SPEC = Path("governed_batches/m9-001-agent-planning-strategies.json")
REGISTRY = Path("governed_batches/registry-v2.json")
ORIGIN = Path("governed_batches/evidence/m9-001-origin-attestation.json")
SOURCE_BASELINE = Path(
    "governed_batches/evidence/m9-001-source-baseline-attestation.json"
)
PRODUCTION_BASELINE = Path(
    "governed_batches/evidence/m9-001-production-baseline.json"
)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m9_planned_batch_is_registered_and_non_mutating() -> None:
    spec = load_batch_spec(SPEC)
    registry = validate_batch_registry(load_batch_registry(REGISTRY))
    origin = _load(ORIGIN)
    source_baseline = _load(SOURCE_BASELINE)
    production_baseline = _load(PRODUCTION_BASELINE)

    assert spec.batch_id == "m9-001-agent-planning-strategies"
    assert spec.lifecycle_state == "planned"
    assert next_action(spec.lifecycle_state) == "open_source_review"
    assert spec.raw["source"]["sha"] is None
    assert spec.raw["candidate"] == {
        "channel": None,
        "release_id": None,
        "manifest_sha256": None,
    }
    assert spec.raw["production_request"] == {
        "operation_id": None,
        "request_path": None,
    }
    assert spec.raw["acceptance"]["raw_fallback_allowed"] is False

    assert registry["status"] == "valid"
    assert registry["batch_count"] == 2
    assert registry["batches"][-1] == {
        "batch_id": spec.batch_id,
        "lifecycle_state": "planned",
        "spec_path": str(SPEC),
    }

    assert origin["origin_commit"] == "27e2fe996f878f2129bf510d6a326c02f7d87be5"
    assert origin["approved_scope_option"] == "A"
    assert {item["language"] for item in origin["origins"]} == {"en", "zh"}

    assert source_baseline["source_sha"] == (
        "97979c1c07d6208055d2937c68e500ba49a6ed57"
    )
    assert source_baseline["intended_source_path_exists"] is False
    assert source_baseline["duplicate_concept_detected"] is False
    assert source_baseline["conflict_detected"] is False

    assert production_baseline["production_release_id"] == (
        "20260707T111252Z-aebf06593f89"
    )
    assert production_baseline["mutations_performed"] == []
    assert production_baseline["source_mutated"] is False
    assert production_baseline["candidate_built"] is False
    assert production_baseline["r2_mutated"] is False
    assert production_baseline["production_pointer_mutated"] is False
    assert production_baseline["ledger_appended"] is False
    assert production_baseline["next_legal_action"] == "open_source_review"
