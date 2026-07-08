from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.batch_lifecycle import next_action
from knowledge_engine.batch_registry import load_batch_registry, validate_batch_registry
from knowledge_engine.batch_spec import load_batch_spec

SPEC = Path("governed_batches/m9-001-agent-planning-strategies.json")
REGISTRY = Path("governed_batches/registry-v2.json")
ORIGIN = Path("governed_batches/evidence/m9-001-origin-attestation.json")
APPROVED_REVIEW = Path(
    "governed_batches/evidence/m9-001-approved-review-decision.json"
)
CANDIDATE_AUTH = Path(
    "governed_batches/evidence/m9-001-candidate-build-authorization.json"
)
RUNTIME = Path(
    "governed_batches/evidence/m9-001-runtime-acceptance-observation.json"
)
PROMOTION_APPROVAL = Path(
    "governed_batches/evidence/m9-001-production-promotion-approval.json"
)
PROMOTION = Path(
    "governed_batches/evidence/m9-001-production-promotion-observation.json"
)
LIFECYCLE = Path("governed_batches/evidence/m9-001-lifecycle-history.json")

SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
CHANNEL = f"candidate-source-{SOURCE_SHA}"
RELEASE = "20260708T040116Z-69a9f445699a"
MANIFEST = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
TARGET_POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m9_production_promoted_state_is_exact() -> None:
    spec = load_batch_spec(SPEC)
    raw_registry = _load(REGISTRY)
    registry = validate_batch_registry(load_batch_registry(REGISTRY))
    origin = _load(ORIGIN)
    review = _load(APPROVED_REVIEW)
    candidate_auth = _load(CANDIDATE_AUTH)
    runtime = _load(RUNTIME)
    promotion_approval = _load(PROMOTION_APPROVAL)
    promotion = _load(PROMOTION)
    lifecycle = _load(LIFECYCLE)

    assert spec.batch_id == "m9-001-agent-planning-strategies"
    assert spec.lifecycle_state == "production_promoted"
    assert next_action(spec.lifecycle_state) == "run_idempotent_replay_and_close"
    assert spec.raw["source"] == {
        "repository": "danielcanfly/knowledge-source",
        "paths": ["bundle/concepts/agent-planning-strategies.md"],
        "sha": SOURCE_SHA,
    }
    assert spec.raw["candidate"] == {
        "channel": CHANNEL,
        "release_id": RELEASE,
        "manifest_sha256": MANIFEST,
    }
    assert spec.raw["production_request"] == {
        "operation_id": "m9-001-agent-planning-strategies-001",
        "request_path": "production_promotions/m9-001-agent-planning-strategies.json",
    }
    assert spec.raw["acceptance"]["raw_fallback_allowed"] is False

    assert registry["status"] == "valid"
    assert registry["batch_count"] == 2
    assert registry["batches"][-1] == {
        "batch_id": spec.batch_id,
        "lifecycle_state": "production_promoted",
        "spec_path": str(SPEC),
    }
    assert raw_registry["batches"][-1]["operation_id"] == (
        "m9-001-agent-planning-strategies-001"
    )

    assert origin["approved_scope_option"] == "A"
    assert {item["language"] for item in origin["origins"]} == {"en", "zh"}
    assert review["status"] == "approved"
    assert review["canonical_write_authorized"] is True
    assert review["production_mutation_authorized"] is False
    assert candidate_auth["production_promotion_authorized"] is False

    assert runtime["status"] == "passed"
    assert runtime["candidate"]["release_id"] == RELEASE
    assert all(
        check["raw_fallback_used"] is False
        for check in runtime["checks"].values()
    )
    assert runtime["production_mutated"] is False

    assert promotion_approval["decision"] == "approve"
    assert promotion_approval["authorization_scope"][
        "promotion_dispatch_authorized"
    ] is True
    assert promotion_approval["authorization_scope"][
        "idempotent_replay_authorized"
    ] is False
    assert promotion_approval["authorization_scope"]["rollback_authorized"] is False

    assert promotion["status"] == "passed"
    assert promotion["promotion"]["run_id"] == 28919098263
    assert promotion["promotion"]["job_id"] == 85792150635
    assert promotion["promotion"]["artifact_id"] == 8158736427
    assert promotion["promotion"]["status"] == "promoted"
    assert promotion["promotion"]["idempotent"] is False
    assert promotion["production_target"] == {
        "release_id": RELEASE,
        "manifest_sha256": MANIFEST,
        "pointer_sha256": TARGET_POINTER,
    }
    assert promotion["runtime_acceptance"]["public_status"] == "answered"
    assert promotion["runtime_acceptance"]["expected_citation_present"] is True
    assert promotion["runtime_acceptance"]["acl_status"] == "not_found"
    assert promotion["runtime_acceptance"]["acl_filtered_count"] == 1
    assert promotion["runtime_acceptance"]["public_raw_fallback_used"] is False
    assert promotion["runtime_acceptance"]["acl_raw_fallback_used"] is False
    assert promotion["ledger"] == {
        "issue": 30,
        "comment_id": 4911573318,
        "comment_url": (
            "https://github.com/danielcanfly/knowledge-engine/issues/30"
            "#issuecomment-4911573318"
        ),
        "appended": True,
    }
    assert promotion["security_notes"]["rollback_used"] is False
    assert promotion["security_notes"]["idempotent_replay_used"] is False
    assert promotion["production_mutated"] is True

    transitions = [(item["from"], item["to"]) for item in lifecycle["transitions"]]
    assert transitions == [
        ("planned", "source_reviewed"),
        ("source_reviewed", "source_validated"),
        ("source_validated", "candidate_built"),
        ("candidate_built", "runtime_accepted"),
        ("runtime_accepted", "request_spec_committed"),
        ("request_spec_committed", "production_promoted"),
    ]
    assert lifecycle["final_state"] == "production_promoted"
    assert lifecycle["source_identity"] == {"sha": SOURCE_SHA}
    assert lifecycle["candidate_identity"] == {
        "channel": CHANNEL,
        "release_id": RELEASE,
        "manifest_sha256": MANIFEST,
    }
    assert lifecycle["production_target"]["pointer_sha256"] == TARGET_POINTER
    assert lifecycle["production_mutated"] is True
    assert lifecycle["next_framework_action"] == "run_idempotent_replay_and_close"
    assert lifecycle["next_legal_action"] == "review_idempotent_replay"
