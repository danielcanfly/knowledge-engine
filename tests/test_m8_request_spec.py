from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.batch_lifecycle import next_action
from knowledge_engine.batch_registry import load_batch_registry, validate_batch_registry
from knowledge_engine.batch_spec import load_batch_spec
from knowledge_engine.promotion_request import load_promotion_request_spec

REQUEST = Path("production_promotions/m8-001-agent-execution-paths.json")
SPEC = Path("governed_batches/m8-001-agent-execution-paths.json")
REGISTRY = Path("governed_batches/registry-v2.json")
POINTER = Path("governed_batches/evidence/m8-001-production-pointer.json")


def test_m8_request_identity_is_preserved() -> None:
    request = load_promotion_request_spec(
        request_path=REQUEST,
        control_plane_sha="0" * 40,
    )
    spec = load_batch_spec(SPEC)
    registry = validate_batch_registry(load_batch_registry(REGISTRY))
    pointer = json.loads(POINTER.read_text(encoding="utf-8"))
    normalized = request.normalized()

    assert "control_plane_sha" not in request.raw
    assert spec.lifecycle_state == "closed"
    assert next_action(spec.lifecycle_state) == "start_next_batch"
    assert registry["status"] == "valid"
    assert registry["batch_count"] == 1
    assert normalized["operation_id"] == spec.raw["production_request"]["operation_id"]
    assert str(REQUEST) == spec.raw["production_request"]["request_path"]
    assert normalized["candidate_channel"] == spec.raw["candidate"]["channel"]
    assert normalized["release_id"] == spec.raw["candidate"]["release_id"]
    assert normalized["manifest_sha256"] == spec.raw["candidate"]["manifest_sha256"]
    assert normalized["source_repository"] == spec.raw["source"]["repository"]
    assert normalized["source_sha"] == spec.raw["source"]["sha"]
    assert normalized["builder_sha"] == spec.raw["builder_sha"]
    assert normalized["foundation_sha"] == spec.raw["foundation_sha"]
    assert normalized["expected_previous_release_id"] == pointer["release_id"]
    assert normalized["expected_previous_manifest_sha256"] == pointer["manifest_sha256"]

    acceptance = spec.raw["acceptance"]
    assert normalized["post_promote_public_query"] == acceptance["public_query"]
    assert normalized["expected_public_status"] == acceptance["expected_public_status"]
    assert normalized["expected_citation_url"] == acceptance["expected_citation_url"]
    assert normalized["post_promote_acl_query"] == acceptance["acl_query"]
    assert normalized["expected_acl_status"] == acceptance["expected_acl_status"]
