from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from knowledge_engine.compiler_contract_v1 import json_bytes
from knowledge_engine.compiler_review_packet_contract_v1 import ReviewerPacketRequest
from knowledge_engine.compiler_review_packet_v1 import (
    build_reviewer_packet,
    verify_reviewer_packet_event,
)
from knowledge_engine.compiler_synthesis_contract_v1 import SynthesisProposalRequest
from knowledge_engine.compiler_synthesis_v1 import (
    synthesize_resolution_batch,
    verify_synthesis_event,
)
from knowledge_engine.errors import IntegrityError
from knowledge_engine.intake_v1 import canonical_json_bytes
from knowledge_engine.storage import FileObjectStore, sha256_bytes

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    ROOT / "src/knowledge_engine/compiler_synthesis_contract_v1.py",
    ROOT / "src/knowledge_engine/compiler_synthesis_v1.py",
    ROOT / "src/knowledge_engine/compiler_review_packet_contract_v1.py",
    ROOT / "src/knowledge_engine/compiler_review_packet_v1.py",
)


def _put(store: FileObjectStore, key: str, value: dict[str, Any]) -> None:
    store.put(key, json_bytes(value), content_type="application/json")


def _json(store: FileObjectStore, key: str) -> dict[str, Any]:
    value = json.loads(store.get(key))
    assert isinstance(value, dict)
    return value


def _resolution_event(
    batch_id: str,
    ordinal: int,
    before: str | None,
    after: str,
    previous: str | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "knowledge-compiler-resolution-event/v1",
        "resolution_batch_id": batch_id,
        "ordinal": ordinal,
        "from_state": before,
        "to_state": after,
        "event_at": "2026-07-08T09:00:00Z",
        "input_artifact_refs": [f"input-{ordinal}"],
        "output_artifact_refs": [f"output-{ordinal}"],
        "previous_event_hash": previous,
        "mutations_performed": ["compiler_review_object_write"],
    }
    return {**payload, "event_sha256": sha256_bytes(canonical_json_bytes(payload))}


def _resolution(
    ordinal: int,
    outcome: str,
    *,
    target_ids: list[str] | None = None,
    audience: str = "public",
    eligible: bool,
) -> dict[str, Any]:
    candidate_id = f"cand_{ordinal:064x}"
    resolution_id = f"cres_{ordinal:064x}"
    value = {
        "new_concept": "Novel Topic",
        "existing_concept_update": "Existing Topic has additional evidence.",
        "alias": "Old Alias",
        "supersession": "Supersedes: Legacy Topic — Replaced by current evidence.",
        "contradiction": "Agents must not retry forever.",
    }[outcome]
    result = {
        "schema_version": "knowledge-compiler-resolution/v1",
        "resolution_id": resolution_id,
        "compiler_run_id": f"crun_{'b' * 64}",
        "candidate_id": candidate_id,
        "outcome": outcome,
        "target_ids": target_ids or [],
        "evidence_refs": [candidate_id, f"smap_{ordinal:064x}"],
        "reason_codes": ["FIXTURE"],
        "match_observations": [],
        "supersession_basis": None,
        "effective_audience": audience,
        "review_status": "pending_human_review",
        "synthesis_eligible": eligible,
        "canonical_write_permitted": False,
        "fixture_value": value,
    }
    if outcome == "supersession":
        result["review_status"] = "pending_conflict_review"
        result["supersession_basis"] = {
            "superseded_target_id": "ko_legacy",
            "basis": "Replaced by current evidence.",
            "effective_at": None,
            "evidence_refs": result["evidence_refs"],
        }
    return result


def _fixture(store: FileObjectStore) -> str:
    batch_id = f"rslv_{'a' * 64}"
    compiler_run_id = f"crun_{'b' * 64}"
    snapshot_sha = "c" * 64
    prefix = f"compiler/v1/resolutions/{batch_id}"
    resolutions = [
        _resolution(1, "new_concept", eligible=True),
        _resolution(
            2,
            "existing_concept_update",
            target_ids=["ko_existing"],
            audience="internal",
            eligible=True,
        ),
        _resolution(
            3,
            "alias",
            target_ids=["ko_existing"],
            audience="internal",
            eligible=True,
        ),
        _resolution(4, "supersession", target_ids=["ko_legacy"], eligible=True),
        _resolution(5, "contradiction", target_ids=["ko_existing"], eligible=False),
    ]
    candidates = [
        {
            "candidate_id": item["candidate_id"],
            "candidate_type": "concept" if item["outcome"] in {"new_concept", "alias"} else "claim",
            "value": item.pop("fixture_value"),
            "evidence_refs": [
                {
                    "source_map_id": item["evidence_refs"][1],
                    "block_id": f"block_{ordinal:064x}",
                }
            ],
            "effective_audience": item["effective_audience"],
            "synthesis_eligible": item["synthesis_eligible"],
        }
        for ordinal, item in enumerate(resolutions, 1)
    ]
    candidate_key = f"compiler/v1/runs/{compiler_run_id}/extraction/candidates.json"
    _put(
        store,
        candidate_key,
        {
            "schema_version": "knowledge-compiler-extraction-candidate-set/v1",
            "compiler_run_id": compiler_run_id,
            "candidate_count": len(candidates),
            "candidates": candidates,
        },
    )
    _put(
        store,
        f"{prefix}/resolution-record.json",
        {
            "schema_version": "knowledge-compiler-resolution-batch/v1",
            "request": {
                "schema_version": "knowledge-compiler-resolution-request/v1",
                "compiler_run_id": compiler_run_id,
                "source_repository": "danielcanfly/knowledge-source",
                "source_commit_sha": "d" * 40,
                "resolved_at": "2026-07-08T09:00:00Z",
            },
            "resolution_batch_id": batch_id,
            "status": "review_only_complete",
            "canonical_write_permitted": False,
            "github_write_permitted": False,
            "production_write_permitted": False,
        },
    )
    _put(
        store,
        f"{prefix}/source-snapshot.json",
        {
            "schema_version": "knowledge-compiler-source-snapshot/v1",
            "repository": "danielcanfly/knowledge-source",
            "commit_sha": "d" * 40,
            "source_snapshot_sha256": snapshot_sha,
        },
    )
    _put(
        store,
        f"{prefix}/candidate-index.json",
        {
            "schema_version": "knowledge-compiler-source-candidate-index/v1",
            "resolution_batch_id": batch_id,
            "source_snapshot_sha256": snapshot_sha,
            "concept_count": 2,
            "concepts": [
                {
                    "concept_id": "ko_existing",
                    "path": "bundle/concepts/existing.md",
                    "title": "Existing Topic",
                    "aliases": ["Old Alias"],
                    "audience": "internal",
                },
                {
                    "concept_id": "ko_legacy",
                    "path": "bundle/concepts/legacy.md",
                    "title": "Legacy Topic",
                    "aliases": [],
                    "audience": "public",
                },
            ],
            "canonical_write_permitted": False,
        },
    )
    _put(
        store,
        f"{prefix}/resolutions.json",
        {
            "schema_version": "knowledge-compiler-resolution-set/v1",
            "resolution_batch_id": batch_id,
            "compiler_run_id": compiler_run_id,
            "resolution_count": len(resolutions),
            "resolutions": resolutions,
            "canonical_write_permitted": False,
        },
    )
    _put(
        store,
        f"{prefix}/validation-report.json",
        {
            "schema_version": "knowledge-compiler-resolution-validation/v1",
            "resolution_batch_id": batch_id,
            "compiler_run_id": compiler_run_id,
            "source_snapshot_sha256": snapshot_sha,
            "all_candidates_evidence_valid": True,
            "audience_broadening_detected": False,
            "canonical_write_permitted": False,
            "github_write_permitted": False,
            "production_write_permitted": False,
        },
    )
    states = [
        (None, "validated_input"),
        ("validated_input", "source_indexed"),
        ("source_indexed", "resolved"),
        ("resolved", "review_only_complete"),
    ]
    event_keys = []
    previous = None
    for ordinal, (before, after) in enumerate(states, 1):
        event = _resolution_event(batch_id, ordinal, before, after, previous)
        previous = event["event_sha256"]
        key = f"{prefix}/events/{ordinal:06d}-{previous}.json"
        event_keys.append(key)
        _put(store, key, event)
    _put(
        store,
        f"{prefix}/result.json",
        {
            "resolution_batch_id": batch_id,
            "compiler_run_id": compiler_run_id,
            "status": "review_only_complete",
            "result_key": f"{prefix}/result.json",
            "event_keys": event_keys,
            "resolution_count": len(resolutions),
            "source_snapshot_sha256": snapshot_sha,
            "resolution_prefix": prefix,
            "canonical_write_permitted": False,
            "github_write_permitted": False,
            "production_write_permitted": False,
        },
    )
    return batch_id


def _synthesis_request(batch_id: str, **overrides: Any) -> SynthesisProposalRequest:
    values: dict[str, Any] = {
        "resolution_batch_id": batch_id,
        "proposed_at": "2026-07-08T10:00:00Z",
    }
    values.update(overrides)
    return SynthesisProposalRequest(**values)


def _packet_request(batch_id: str) -> ReviewerPacketRequest:
    return ReviewerPacketRequest(
        proposal_batch_id=batch_id,
        assembled_at="2026-07-08T10:30:00Z",
    )


def test_synthesis_and_reviewer_packet_are_evidence_bound_and_replayable(
    tmp_path: Path,
) -> None:
    store = FileObjectStore(tmp_path / "store")
    resolution_batch_id = _fixture(store)

    synthesis = synthesize_resolution_batch(
        store,
        _synthesis_request(resolution_batch_id),
        tmp_path / "synthesis-output",
    )
    assert synthesis.status == "review_only_complete"
    assert synthesis.proposal_count == 4
    assert synthesis.quarantine_count == 1
    assert synthesis.idempotent is False
    assert synthesis.proposal_prefix
    proposals = _json(store, f"{synthesis.proposal_prefix}/proposal-set.json")["proposals"]
    assert {item["proposal_kind"] for item in proposals} == {
        "concept_create",
        "concept_update",
        "alias_add",
        "supersession_update",
    }
    assert all(item["provider"] == "none" for item in proposals)
    assert all(item["provider_invocation_permitted"] is False for item in proposals)
    assert all(item["canonical_write_permitted"] is False for item in proposals)
    update = next(item for item in proposals if item["proposal_kind"] == "concept_update")
    assert update["effective_audience"] == "internal"
    quarantine = _json(store, f"{synthesis.proposal_prefix}/quarantine.json")
    assert quarantine["items"][0]["outcome"] == "contradiction"

    previous = None
    for key in synthesis.event_keys:
        event = _json(store, key)
        assert verify_synthesis_event(event)
        assert event["previous_event_hash"] == previous
        previous = event["event_sha256"]

    replay = synthesize_resolution_batch(store, _synthesis_request(resolution_batch_id))
    assert replay.to_dict() == {**synthesis.to_dict(), "idempotent": True}

    packet = build_reviewer_packet(
        store,
        _packet_request(synthesis.proposal_batch_id),
        tmp_path / "packet-output",
    )
    assert packet.status == "review_ready"
    assert packet.proposal_count == 4
    assert packet.quarantine_count == 1
    assert packet.high_risk_count == 1
    assert packet.human_decision_required is True
    assert packet.packet_prefix
    summary = _json(store, f"{packet.packet_prefix}/summary.json")
    assert summary["decision_state"] == "awaiting_human_decision"
    checklist = _json(store, f"{packet.packet_prefix}/review-checklist.json")
    assert checklist["automatic_approval_permitted"] is False
    assert all(item["decision"] is None for item in checklist["items"])
    quarantine_report = _json(store, f"{packet.packet_prefix}/quarantine-report.json")
    assert quarantine_report["release_blocking"] is True

    previous = None
    for key in packet.event_keys:
        event = _json(store, key)
        assert verify_reviewer_packet_event(event)
        assert event["previous_event_hash"] == previous
        previous = event["event_sha256"]

    packet_replay = build_reviewer_packet(store, _packet_request(synthesis.proposal_batch_id))
    assert packet_replay.to_dict() == {**packet.to_dict(), "idempotent": True}


def test_reviewer_packet_rejects_audience_broadening(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    resolution_batch_id = _fixture(store)
    synthesis = synthesize_resolution_batch(store, _synthesis_request(resolution_batch_id))
    assert synthesis.proposal_prefix
    key = f"{synthesis.proposal_prefix}/proposal-set.json"
    proposal_set = _json(store, key)
    update = next(
        item for item in proposal_set["proposals"] if item["proposal_kind"] == "concept_update"
    )
    update["effective_audience"] = "public"
    _put(store, key, proposal_set)

    packet = build_reviewer_packet(store, _packet_request(synthesis.proposal_batch_id))
    assert packet.status == "rejected"
    assert packet.failure_code == "REVIEW_PACKET_POLICY_BROADENING"
    assert packet.canonical_write_permitted is False


def test_synthesis_rejects_provider_and_orphan_resolution(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    resolution_batch_id = _fixture(store)
    provider = synthesize_resolution_batch(
        store,
        _synthesis_request(resolution_batch_id, provider="example-provider"),
    )
    assert provider.status == "rejected"
    assert provider.failure_code == "SYNTHESIS_PROVIDER_NOT_NEUTRAL"

    resolution_key = f"compiler/v1/resolutions/{resolution_batch_id}/resolutions.json"
    resolution_set = _json(store, resolution_key)
    resolution_set["resolutions"][0]["candidate_id"] = f"cand_{'f' * 64}"
    resolution_set["resolutions"][0]["evidence_refs"][0] = f"cand_{'f' * 64}"
    _put(store, resolution_key, resolution_set)
    orphan = synthesize_resolution_batch(store, _synthesis_request(resolution_batch_id))
    assert orphan.status == "rejected"
    assert orphan.failure_code == "SYNTHESIS_ORPHAN_RESOLUTION"


def test_synthesis_immutable_collision_fails_hard(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    resolution_batch_id = _fixture(store)
    result = synthesize_resolution_batch(store, _synthesis_request(resolution_batch_id))
    assert result.proposal_prefix
    key = f"{result.proposal_prefix}/proposal-set.json"
    proposal_set = _json(store, key)
    proposal_set["proposal_count"] = 999
    _put(store, key, proposal_set)
    with pytest.raises(IntegrityError):
        synthesize_resolution_batch(store, _synthesis_request(resolution_batch_id))


def test_m11_4_and_m11_5_modules_have_no_forbidden_runtime_surface() -> None:
    forbidden_imports = {
        "boto3",
        "httpx",
        "requests",
        "subprocess",
        "socket",
        "openai",
        "anthropic",
    }
    forbidden_calls = {
        "delete",
        "create_pull_request",
        "merge_pull_request",
        "promote",
        "rollback",
    }
    for path in MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert imported.isdisjoint(forbidden_imports)
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert calls.isdisjoint(forbidden_calls)
