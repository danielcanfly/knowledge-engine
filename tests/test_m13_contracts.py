from __future__ import annotations

import ast
from pathlib import Path

import pytest
from knowledge_engine.m13_contracts import (
    GOVERNANCE_NO_WRITE,
    ExpectedPreviousProduction,
    M13BatchRecord,
    M13BatchSeed,
    M13OperationRequest,
    M13OperationResult,
    ProductionIdentity,
    assert_expected_previous_production,
    production_slot_key,
    validate_batch_transition,
    validate_operation_transition,
)

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/knowledge_engine/m13_contracts.py"
SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
PRODUCTION = ProductionIdentity(
    release_id="20260708T040116Z-69a9f445699a",
    manifest_sha256="2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb",
    pointer_sha256="38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5",
)


def _seed() -> M13BatchSeed:
    return M13BatchSeed(
        source_repository="danielcanfly/knowledge-source",
        source_commit_sha=SOURCE_SHA,
        production=PRODUCTION,
        requested_by="reviewer@example.com",
        requested_at="2026-07-09T04:00:00Z",
        purpose="M13 fixture batch",
        review_ids=("rqdecision_" + "a" * 32,),
    )


def _expected_previous() -> ExpectedPreviousProduction:
    return ExpectedPreviousProduction(
        production=PRODUCTION,
        checked_at="2026-07-09T04:01:00Z",
    )


def test_batch_seed_and_record_identities_are_deterministic() -> None:
    seed = _seed()
    replay = _seed()
    assert seed.batch_id() == replay.batch_id()
    assert seed.batch_id().startswith("mbatch_")
    batch = M13BatchRecord.from_seed(seed)
    assert batch.batch_id == seed.batch_id()
    assert batch.state == "planned"
    assert batch.to_identity()["terminal"] is False


def test_candidate_states_require_candidate_channel() -> None:
    with pytest.raises(ValueError, match="candidate_channel"):
        M13BatchRecord.from_seed(_seed(), state="candidate_ready")
    batch = M13BatchRecord.from_seed(
        _seed(),
        state="candidate_ready",
        candidate_channel="candidate-m13-fixture",
    )
    assert batch.candidate_channel == "candidate-m13-fixture"


def test_batch_transitions_reject_invalid_jumps() -> None:
    validate_batch_transition("planned", "reviewing_source")
    validate_batch_transition("promoting", "closed")
    with pytest.raises(ValueError, match="invalid batch transition"):
        validate_batch_transition("planned", "closed")
    with pytest.raises(ValueError, match="invalid batch transition"):
        validate_batch_transition("closed", "promoting")


def test_operation_request_identities_and_transition_contracts() -> None:
    request = M13OperationRequest(
        kind="candidate_build",
        batch_id=_seed().batch_id(),
        requested_by="operator@example.com",
        requested_at="2026-07-09T04:02:00Z",
        expected_previous_production=_expected_previous(),
        artifact_names=("m13/candidate-plan.json",),
    )
    assert request.operation_id().startswith("mop_")
    assert request.operation_id() == M13OperationRequest(
        kind="candidate_build",
        batch_id=_seed().batch_id(),
        requested_by="operator@example.com",
        requested_at="2026-07-09T04:02:00Z",
        expected_previous_production=_expected_previous(),
        artifact_names=("m13/candidate-plan.json",),
    ).operation_id()
    validate_operation_transition("planned", "running")
    validate_operation_transition("running", "completed")
    with pytest.raises(ValueError, match="invalid operation transition"):
        validate_operation_transition("completed", "running")


def test_operation_result_enforces_no_write_for_planning_operations() -> None:
    request = M13OperationRequest(
        kind="release_comparison",
        batch_id=_seed().batch_id(),
        requested_by="operator@example.com",
        requested_at="2026-07-09T04:03:00Z",
        expected_previous_production=_expected_previous(),
        artifact_names=("m13/release-comparison.json",),
    )
    result = M13OperationResult(
        operation_id=request.operation_id(),
        request=request,
        state="completed",
        result_at="2026-07-09T04:04:00Z",
        evidence_refs=("m13/release-comparison.json",),
    )
    assert result.governance == GOVERNANCE_NO_WRITE
    assert result.to_identity()["terminal"] is True
    with pytest.raises(ValueError, match="governance boundary"):
        M13OperationResult(
            operation_id=request.operation_id(),
            request=request,
            state="completed",
            result_at="2026-07-09T04:04:00Z",
            governance={**GOVERNANCE_NO_WRITE, "production_write_permitted": True},
        )


def test_production_mutation_operations_require_slot_and_explicit_governance() -> None:
    with pytest.raises(ValueError, match="production mutations cannot be planning_only"):
        M13OperationRequest(
            kind="production_promotion",
            batch_id=_seed().batch_id(),
            requested_by="operator@example.com",
            requested_at="2026-07-09T04:05:00Z",
            expected_previous_production=_expected_previous(),
        )
    request = M13OperationRequest(
        kind="production_promotion",
        batch_id=_seed().batch_id(),
        requested_by="operator@example.com",
        requested_at="2026-07-09T04:05:00Z",
        expected_previous_production=_expected_previous(),
        planning_only=False,
        requires_production_slot=True,
    )
    mutation_governance = {
        **GOVERNANCE_NO_WRITE,
        "release_write_permitted": True,
        "production_write_permitted": True,
        "permanent_ledger_append_permitted": True,
    }
    result = M13OperationResult(
        operation_id=request.operation_id(),
        request=request,
        state="completed",
        result_at="2026-07-09T04:06:00Z",
        governance=mutation_governance,
    )
    assert result.governance["production_write_permitted"] is True


def test_expected_previous_production_and_slot_key_are_stale_safe() -> None:
    assert_expected_previous_production(expected=PRODUCTION, observed=PRODUCTION)
    stale = ProductionIdentity(
        release_id=PRODUCTION.release_id,
        manifest_sha256=PRODUCTION.manifest_sha256,
        pointer_sha256="f" * 64,
    )
    with pytest.raises(ValueError, match="stale"):
        assert_expected_previous_production(expected=PRODUCTION, observed=stale)
    assert production_slot_key(PRODUCTION) == production_slot_key(PRODUCTION)
    assert production_slot_key(PRODUCTION).startswith("mopslot_")


def test_blocked_and_rejected_operation_results_require_reasons() -> None:
    request = M13OperationRequest(
        kind="source_review",
        batch_id=_seed().batch_id(),
        requested_by="operator@example.com",
        requested_at="2026-07-09T04:07:00Z",
        expected_previous_production=_expected_previous(),
    )
    with pytest.raises(ValueError, match="blocked_reason"):
        M13OperationResult(
            operation_id=request.operation_id(),
            request=request,
            state="blocked",
            result_at="2026-07-09T04:08:00Z",
        )
    with pytest.raises(ValueError, match="rejection_reason"):
        M13OperationResult(
            operation_id=request.operation_id(),
            request=request,
            state="rejected",
            result_at="2026-07-09T04:08:00Z",
        )


def test_m13_contract_module_has_no_network_or_mutating_surface() -> None:
    forbidden_imports = {
        "boto3",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "openai",
        "anthropic",
    }
    forbidden_calls = {
        "create_pull_request",
        "merge_pull_request",
        "promote",
        "rollback",
        "delete",
        "put",
        "write_text",
        "write_bytes",
    }
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
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
