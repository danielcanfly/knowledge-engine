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
APPROVED_REVIEW = Path(
    "governed_batches/evidence/m9-001-approved-review-decision.json"
)
CANDIDATE_AUTH = Path(
    "governed_batches/evidence/m9-001-candidate-build-authorization.json"
)
OBSERVATION = Path(
    "governed_batches/evidence/m9-001-source-candidate-observation.json"
)
LIFECYCLE = Path("governed_batches/evidence/m9-001-lifecycle-history.json")

SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
CANDIDATE_CHANNEL = f"candidate-source-{SOURCE_SHA}"
RELEASE_ID = "20260708T040116Z-69a9f445699a"
MANIFEST_SHA256 = (
    "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m9_candidate_built_state_is_exact_and_non_production() -> None:
    spec = load_batch_spec(SPEC)
    raw_registry = _load(REGISTRY)
    registry = validate_batch_registry(load_batch_registry(REGISTRY))
    origin = _load(ORIGIN)
    source_baseline = _load(SOURCE_BASELINE)
    production_baseline = _load(PRODUCTION_BASELINE)
    approved_review = _load(APPROVED_REVIEW)
    candidate_auth = _load(CANDIDATE_AUTH)
    observation = _load(OBSERVATION)
    lifecycle = _load(LIFECYCLE)

    assert spec.batch_id == "m9-001-agent-planning-strategies"
    assert spec.lifecycle_state == "candidate_built"
    assert next_action(spec.lifecycle_state) == "run_runtime_acceptance"
    assert spec.raw["source"] == {
        "repository": "danielcanfly/knowledge-source",
        "paths": ["bundle/concepts/agent-planning-strategies.md"],
        "sha": SOURCE_SHA,
    }
    assert spec.raw["candidate"] == {
        "channel": CANDIDATE_CHANNEL,
        "release_id": RELEASE_ID,
        "manifest_sha256": MANIFEST_SHA256,
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
        "lifecycle_state": "candidate_built",
        "spec_path": str(SPEC),
    }
    assert raw_registry["batches"][-1]["candidate_channel"] == CANDIDATE_CHANNEL

    assert origin["origin_commit"] == "27e2fe996f878f2129bf510d6a326c02f7d87be5"
    assert origin["approved_scope_option"] == "A"
    assert {item["language"] for item in origin["origins"]} == {"en", "zh"}

    assert source_baseline["source_sha"] == (
        "97979c1c07d6208055d2937c68e500ba49a6ed57"
    )
    assert source_baseline["intended_source_path_exists"] is False

    assert approved_review["status"] == "approved"
    assert approved_review["canonical_write_authorized"] is True
    assert approved_review["production_mutation_authorized"] is False

    assert candidate_auth["authorized_by"] == "danielcanfly"
    assert candidate_auth["source_pr"] == {
        "repository": "danielcanfly/knowledge-source",
        "number": 13,
    }
    assert candidate_auth["production_request_authorized"] is False
    assert candidate_auth["production_promotion_authorized"] is False
    assert candidate_auth["permanent_ledger_append_authorized"] is False

    source = observation["source"]
    candidate = observation["candidate"]
    limitations = observation["limitations"]
    production = observation["production"]
    assert source["sha"] == SOURCE_SHA
    assert source["validation_run"] == 28916504659
    assert source["validation_artifact"] == 8157822857
    assert source["validation_findings"] == 0
    assert candidate["channel"] == CANDIDATE_CHANNEL
    assert candidate["dispatch_run"] == 28916529017
    assert candidate["release_id"] == RELEASE_ID
    assert candidate["manifest_sha256"] == MANIFEST_SHA256
    assert candidate["reproducibility_passed"] is True
    assert candidate["internal_status"] == "answered"
    assert candidate["internal_citation_count"] == 1
    assert candidate["public_status"] == "not_found"
    assert candidate["public_result_count"] == 0
    assert candidate["public_acl_filtered_count"] == 1
    assert candidate["production_pointer_unchanged"] is True
    assert limitations["targeted_m9_public_query_not_yet_run"] is True
    assert limitations["targeted_m9_acl_query_not_yet_run"] is True
    assert limitations["raw_fallback_not_reported_by_generic_candidate_artifact"] is True
    assert production["pointer_mutated"] is False
    assert production["request_spec_created"] is False
    assert production["ledger_appended"] is False
    assert production["promotion_performed"] is False

    transitions = [(item["from"], item["to"]) for item in lifecycle["transitions"]]
    assert transitions == [
        ("planned", "source_reviewed"),
        ("source_reviewed", "source_validated"),
        ("source_validated", "candidate_built"),
    ]
    assert lifecycle["initial_state"] == "planned"
    assert lifecycle["final_state"] == "candidate_built"
    assert lifecycle["source_identity"] == {"sha": SOURCE_SHA}
    assert lifecycle["candidate_identity"] == {
        "channel": CANDIDATE_CHANNEL,
        "release_id": RELEASE_ID,
        "manifest_sha256": MANIFEST_SHA256,
    }
    assert lifecycle["production_mutated"] is False
    assert lifecycle["next_legal_action"] == "run_targeted_runtime_acceptance"

    assert production_baseline["production_release_id"] == (
        "20260707T111252Z-aebf06593f89"
    )
    assert production_baseline["mutations_performed"] == []
    assert production_baseline["production_pointer_mutated"] is False
    assert production_baseline["ledger_appended"] is False
