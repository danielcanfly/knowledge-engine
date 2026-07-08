from __future__ import annotations

import hashlib
import json
from pathlib import Path

from knowledge_engine.batch_lifecycle import next_action
from knowledge_engine.batch_registry import load_batch_registry, validate_batch_registry
from knowledge_engine.batch_spec import load_batch_spec
from knowledge_engine.promotion_request import load_promotion_request_spec

REQUEST = Path("production_promotions/m9-001-agent-planning-strategies.json")
SPEC = Path("governed_batches/m9-001-agent-planning-strategies.json")
REGISTRY = Path("governed_batches/registry-v2.json")
BASELINE = Path("governed_batches/evidence/m9-001-production-baseline.json")
RUNTIME = Path("governed_batches/evidence/m9-001-runtime-acceptance-observation.json")
LIFECYCLE = Path("governed_batches/evidence/m9-001-lifecycle-history.json")

OPERATION_ID = "m9-001-agent-planning-strategies-001"
REQUEST_SHA256 = "41564a42a3f207ea87bbc600935effbb9c3979c8366e16a4b1c7d1f35e172b5b"
PREVIOUS_RELEASE = "20260707T111252Z-aebf06593f89"
PREVIOUS_MANIFEST = (
    "1a2f2014073e9e97f9e1fdd5df4e43bf19cb2b2679532b6e52ea38480ec4d2ec"
)
POINTER_SHA256 = "2de63a9ff5963ea3f72f0051b25a084dda9e5e609fe79615e55e3f95a1351914"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m9_request_spec_is_exact_and_non_mutating() -> None:
    request = load_promotion_request_spec(
        request_path=REQUEST,
        control_plane_sha="0" * 40,
    )
    spec = load_batch_spec(SPEC)
    raw_registry = _load(REGISTRY)
    registry = validate_batch_registry(load_batch_registry(REGISTRY))
    baseline = _load(BASELINE)
    runtime = _load(RUNTIME)
    lifecycle = _load(LIFECYCLE)
    normalized = request.normalized()

    assert hashlib.sha256(REQUEST.read_bytes()).hexdigest() == REQUEST_SHA256
    assert "control_plane_sha" not in request.raw
    assert normalized["control_plane_sha"] == "0" * 40

    assert spec.lifecycle_state == "request_spec_committed"
    assert next_action(spec.lifecycle_state) == "review_production_promotion"
    assert normalized["operation_id"] == OPERATION_ID
    assert spec.raw["production_request"] == {
        "operation_id": OPERATION_ID,
        "request_path": str(REQUEST),
    }

    assert normalized["candidate_channel"] == spec.raw["candidate"]["channel"]
    assert normalized["release_id"] == spec.raw["candidate"]["release_id"]
    assert normalized["manifest_sha256"] == spec.raw["candidate"]["manifest_sha256"]
    assert normalized["source_repository"] == spec.raw["source"]["repository"]
    assert normalized["source_sha"] == spec.raw["source"]["sha"]
    assert normalized["builder_sha"] == spec.raw["builder_sha"]
    assert normalized["foundation_sha"] == spec.raw["foundation_sha"]

    assert normalized["expected_previous_release_id"] == PREVIOUS_RELEASE
    assert normalized["expected_previous_manifest_sha256"] == PREVIOUS_MANIFEST
    assert baseline["production_release_id"] == PREVIOUS_RELEASE
    assert baseline["production_manifest_sha256"] == PREVIOUS_MANIFEST
    assert baseline["production_pointer_sha256"] == POINTER_SHA256

    acceptance = spec.raw["acceptance"]
    assert normalized["post_promote_public_query"] == acceptance["public_query"]
    assert normalized["expected_public_status"] == acceptance["expected_public_status"]
    assert normalized["expected_citation_url"] == acceptance["expected_citation_url"]
    assert normalized["post_promote_acl_query"] == acceptance["acl_query"]
    assert normalized["expected_acl_status"] == acceptance["expected_acl_status"]
    assert normalized["actor"] == "danielcanfly"
    assert "28917325425" in normalized["reason"]

    assert registry["status"] == "valid"
    assert registry["batch_count"] == 2
    entry = raw_registry["batches"][-1]
    assert entry["batch_id"] == spec.batch_id
    assert entry["lifecycle_state"] == "request_spec_committed"
    assert entry["operation_id"] == OPERATION_ID
    assert entry["request_path"] == str(REQUEST)

    transitions = [(item["from"], item["to"]) for item in lifecycle["transitions"]]
    assert transitions[-1] == ("runtime_accepted", "request_spec_committed")
    evidence = lifecycle["transitions"][-1]["evidence"]
    assert evidence["request_sha256"] == REQUEST_SHA256
    assert evidence["control_plane_sha_committed"] is False
    assert evidence["production_promotion_authorized"] is False
    assert lifecycle["final_state"] == "request_spec_committed"
    assert lifecycle["production_mutated"] is False
    assert lifecycle["next_legal_action"] == "review_production_promotion"

    assert runtime["status"] == "passed"
    assert runtime["production_pointer"]["before_sha256"] == POINTER_SHA256
    assert runtime["production_pointer"]["after_sha256"] == POINTER_SHA256
    assert runtime["production_pointer"]["byte_exact_unchanged"] is True
    assert runtime["production_request_created"] is False
    assert runtime["permanent_ledger_appended"] is False
    assert runtime["production_mutated"] is False
    assert baseline["mutations_performed"] == []
    assert baseline["ledger_appended"] is False
