from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from knowledge_engine.multi_batch_contracts import (
    ARTIFACT_NAME_RE,
    BATCH_ID_RE,
    CANDIDATE_CHANNEL_RE,
    LEDGER_ID_RE,
    OPERATION_ID_RE,
    REVIEW_ID_RE,
    BatchPlan,
    BatchState,
    OperationKind,
    OperationRequest,
    OperationResult,
    OperationStatus,
    ProductionIdentity,
    artifact_name,
    candidate_channel,
    canonical_json_bytes,
    ledger_identifier,
    review_id,
    validate_batch_transition,
    validate_operation_transition,
)

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/knowledge_engine/multi_batch_contracts.py"
SCHEMAS = (
    ROOT / "schemas/multi-batch/batch-plan.schema.json",
    ROOT / "schemas/multi-batch/operation-request.schema.json",
    ROOT / "schemas/multi-batch/operation-result.schema.json",
)


def _production() -> ProductionIdentity:
    return ProductionIdentity(
        release_id="20260708T040116Z-69a9f445699a",
        manifest_sha256=(
            "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
        ),
        pointer_sha256=(
            "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
        ),
    )


def _plan(*, title: str = "M13 fixture batch") -> BatchPlan:
    return BatchPlan(
        title=title,
        created_at="2026-07-09T04:00:00Z",
        actor="operator@example.com",
        source_commit_sha="2126db2ed4d372d3d61464fe31a86fc0243a1f24",
        base_production=_production(),
        intended_audiences=("internal", "public"),
        source_refs=("intake/v1/snapshots/source-b", "intake/v1/snapshots/source-a"),
        metadata=(("campaign", "m13-fixture"),),
    )


def test_batch_plan_identity_is_deterministic_and_order_normalized() -> None:
    first = _plan()
    second = BatchPlan(
        title="M13 fixture batch",
        created_at="2026-07-09T04:00:00Z",
        actor="operator@example.com",
        source_commit_sha="2126db2ed4d372d3d61464fe31a86fc0243a1f24",
        base_production=_production(),
        intended_audiences=("public", "internal"),
        source_refs=("intake/v1/snapshots/source-a", "intake/v1/snapshots/source-b"),
        metadata=(("campaign", "m13-fixture"),),
    )
    assert first.batch_id == second.batch_id
    assert BATCH_ID_RE.fullmatch(first.batch_id)
    assert first.to_dict() == second.to_dict()
    assert canonical_json_bytes(first.to_dict()) == canonical_json_bytes(second.to_dict())
    assert _plan(title="A different batch").batch_id != first.batch_id


def test_batch_plan_rejects_invalid_policy_and_duplicate_evidence() -> None:
    with pytest.raises(ValueError, match="invalid audience"):
        BatchPlan(
            title="bad",
            created_at="2026-07-09T04:00:00Z",
            actor="operator",
            source_commit_sha="2126db2ed4d372d3d61464fe31a86fc0243a1f24",
            base_production=_production(),
            intended_audiences=("public", "secret"),
            source_refs=("source-a",),
        )
    with pytest.raises(ValueError, match="duplicates"):
        BatchPlan(
            title="bad",
            created_at="2026-07-09T04:00:00Z",
            actor="operator",
            source_commit_sha="2126db2ed4d372d3d61464fe31a86fc0243a1f24",
            base_production=_production(),
            intended_audiences=("public",),
            source_refs=("source-a", "source-a"),
        )


def test_operation_identity_and_candidate_generation_are_deterministic() -> None:
    batch_id = _plan().batch_id
    request = OperationRequest(
        batch_id=batch_id,
        kind=OperationKind.BUILD_CANDIDATE,
        requested_at="2026-07-09T04:10:00Z",
        actor="builder@example.com",
        expected_batch_state=BatchState.SOURCE_REVIEW,
        target_batch_state=BatchState.CANDIDATE_BUILDING,
        candidate_generation=1,
        evidence_refs=("review/m13/source-package", "review/m13/decision"),
    )
    replay = OperationRequest(
        batch_id=batch_id,
        kind=OperationKind.BUILD_CANDIDATE,
        requested_at="2026-07-09T04:10:00Z",
        actor="builder@example.com",
        expected_batch_state=BatchState.SOURCE_REVIEW,
        target_batch_state=BatchState.CANDIDATE_BUILDING,
        candidate_generation=1,
        evidence_refs=("review/m13/decision", "review/m13/source-package"),
    )
    assert request.operation_id == replay.operation_id
    assert OPERATION_ID_RE.fullmatch(request.operation_id)
    assert request.requires_exclusive_production_mutation is False
    assert request.to_dict() == replay.to_dict()

    generation_two = OperationRequest(
        batch_id=batch_id,
        kind=OperationKind.BUILD_CANDIDATE,
        requested_at="2026-07-09T04:10:00Z",
        actor="builder@example.com",
        expected_batch_state=BatchState.SOURCE_REVIEW,
        target_batch_state=BatchState.CANDIDATE_BUILDING,
        candidate_generation=2,
        evidence_refs=("review/m13/decision", "review/m13/source-package"),
    )
    assert generation_two.operation_id != request.operation_id


def test_production_mutation_requires_exact_expected_previous_identity() -> None:
    batch_id = _plan().batch_id
    with pytest.raises(ValueError, match="expected_previous_production"):
        OperationRequest(
            batch_id=batch_id,
            kind=OperationKind.PROMOTE_PRODUCTION,
            requested_at="2026-07-09T04:20:00Z",
            actor="release-operator@example.com",
            expected_batch_state=BatchState.PROMOTION_READY,
            target_batch_state=BatchState.PRODUCTION_ACTIVE,
            evidence_refs=("m12closure2/example",),
        )

    request = OperationRequest(
        batch_id=batch_id,
        kind=OperationKind.PROMOTE_PRODUCTION,
        requested_at="2026-07-09T04:20:00Z",
        actor="release-operator@example.com",
        expected_batch_state=BatchState.PROMOTION_READY,
        target_batch_state=BatchState.PRODUCTION_ACTIVE,
        evidence_refs=("m12closure2/example",),
        expected_previous_production=_production(),
        request_nonce="approval-42",
    )
    assert request.requires_exclusive_production_mutation is True
    assert request.to_dict()["expected_previous_production"] == _production().to_dict()

    with pytest.raises(ValueError, match="only valid for production mutation"):
        OperationRequest(
            batch_id=batch_id,
            kind=OperationKind.START_INTAKE,
            requested_at="2026-07-09T04:20:00Z",
            actor="operator@example.com",
            expected_batch_state=BatchState.PLANNED,
            target_batch_state=BatchState.INTAKE_ACTIVE,
            evidence_refs=("plan/example",),
            expected_previous_production=_production(),
        )


def test_state_machines_reject_skips_and_terminal_reentry() -> None:
    validate_batch_transition(BatchState.PLANNED, BatchState.INTAKE_ACTIVE)
    validate_batch_transition(BatchState.CANDIDATE_READY, BatchState.CANDIDATE_BUILDING)
    validate_operation_transition(OperationStatus.REQUESTED, OperationStatus.VALIDATED)
    validate_operation_transition(OperationStatus.RUNNING, OperationStatus.SUCCEEDED)

    with pytest.raises(ValueError, match="invalid batch transition"):
        validate_batch_transition(BatchState.PLANNED, BatchState.PROMOTION_READY)
    with pytest.raises(ValueError, match="terminal batch state"):
        validate_batch_transition(BatchState.CLOSED, BatchState.PLANNED)
    with pytest.raises(ValueError, match="invalid operation transition"):
        validate_operation_transition(OperationStatus.REQUESTED, OperationStatus.SUCCEEDED)
    with pytest.raises(ValueError, match="terminal operation status"):
        validate_operation_transition(OperationStatus.SUCCEEDED, OperationStatus.RUNNING)


def test_operation_request_rejects_kind_transition_mismatch() -> None:
    with pytest.raises(ValueError, match="operation kind and batch transition"):
        OperationRequest(
            batch_id=_plan().batch_id,
            kind=OperationKind.OPEN_SOURCE_REVIEW,
            requested_at="2026-07-09T04:30:00Z",
            actor="reviewer@example.com",
            expected_batch_state=BatchState.PLANNED,
            target_batch_state=BatchState.SOURCE_REVIEW,
            evidence_refs=("intake/example",),
        )


def test_operation_result_is_review_only_and_fail_closed() -> None:
    request = OperationRequest(
        batch_id=_plan().batch_id,
        kind=OperationKind.START_INTAKE,
        requested_at="2026-07-09T04:40:00Z",
        actor="operator@example.com",
        expected_batch_state=BatchState.PLANNED,
        target_batch_state=BatchState.INTAKE_ACTIVE,
        evidence_refs=("batch-plan/example",),
    )
    result = OperationResult(
        operation_id=request.operation_id,
        batch_id=request.batch_id,
        kind=request.kind,
        status=OperationStatus.SUCCEEDED,
        before_batch_state=BatchState.PLANNED,
        after_batch_state=BatchState.INTAKE_ACTIVE,
        occurred_at="2026-07-09T04:41:00Z",
        evidence_refs=("operation-validation/example",),
    )
    payload = result.to_dict()
    assert payload["mutation_performed"] is False
    assert payload["canonical_source_write_permitted"] is False
    assert payload["candidate_write_permitted"] is False
    assert payload["production_write_permitted"] is False
    assert payload["ledger_append_permitted"] is False

    with pytest.raises(ValueError, match="cannot grant write permissions"):
        OperationResult(
            operation_id=request.operation_id,
            batch_id=request.batch_id,
            kind=request.kind,
            status=OperationStatus.SUCCEEDED,
            before_batch_state=BatchState.PLANNED,
            after_batch_state=BatchState.INTAKE_ACTIVE,
            occurred_at="2026-07-09T04:41:00Z",
            evidence_refs=("operation-validation/example",),
            production_write_permitted=True,
        )

    rejected = OperationResult(
        operation_id=request.operation_id,
        batch_id=request.batch_id,
        kind=request.kind,
        status=OperationStatus.REJECTED,
        before_batch_state=BatchState.PLANNED,
        after_batch_state=BatchState.PLANNED,
        occurred_at="2026-07-09T04:41:00Z",
        evidence_refs=("operation-rejection/example",),
        failure_code="STALE_EXPECTED_STATE",
    )
    assert rejected.to_dict()["failure_code"] == "STALE_EXPECTED_STATE"


def test_standardized_names_are_stable_and_strict() -> None:
    batch_id = _plan().batch_id
    operation_id = OperationRequest(
        batch_id=batch_id,
        kind=OperationKind.START_INTAKE,
        requested_at="2026-07-09T04:50:00Z",
        actor="operator@example.com",
        expected_batch_state=BatchState.PLANNED,
        target_batch_state=BatchState.INTAKE_ACTIVE,
        evidence_refs=("batch-plan/example",),
    ).operation_id
    channel = candidate_channel(batch_id, 3)
    artifact = artifact_name(batch_id, "release-comparison", "a" * 64, "json")
    review = review_id(batch_id, "reviewer@example.com", ("evidence-b", "evidence-a"))
    ledger = ledger_identifier(batch_id, operation_id)

    assert CANDIDATE_CHANNEL_RE.fullmatch(channel)
    assert channel.endswith("/0003")
    assert ARTIFACT_NAME_RE.fullmatch(artifact)
    assert REVIEW_ID_RE.fullmatch(review)
    assert review == review_id(
        batch_id, "reviewer@example.com", ("evidence-a", "evidence-b")
    )
    assert LEDGER_ID_RE.fullmatch(ledger)

    with pytest.raises(ValueError, match="generation"):
        candidate_channel(batch_id, 0)
    with pytest.raises(ValueError, match="artifact kind"):
        artifact_name(batch_id, "Bad Kind", "a" * 64, "json")


def test_schema_files_are_valid_json_and_have_closed_objects() -> None:
    for path in SCHEMAS:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["required"]


def test_contract_module_has_no_network_storage_or_mutation_surface() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    forbidden_imports = {
        "boto3",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "openai",
        "anthropic",
    }
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

    forbidden_calls = {
        "put",
        "delete",
        "write_text",
        "write_bytes",
        "create_pull_request",
        "promote",
        "rollback",
    }
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint(forbidden_calls)
