from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.m25_intake_orchestrator import (
    LOCAL_MARKDOWN_ADAPTER,
    AdapterOutcome,
    build_adapter_registry,
    build_plan_bundle,
    build_source_inventory,
    persist_plan_bundle,
    resume_orchestrator,
)
from knowledge_engine.storage import FileObjectStore
from m25_2_test_support import (
    M25_DOC_ROOT,
    ROOT,
    SCHEMA_ROOT,
    _descriptor,
    _load_json,
    _prepare,
)


def test_adapter_registry_is_exactly_bounded_and_protected() -> None:
    registry = build_adapter_registry()
    assert registry["approved_adapter_count"] == 2
    assert {adapter["adapter_id"] for adapter in registry["adapters"]} == {
        "m25_adapter_intake_v1_local_markdown",
        "m25_adapter_intake_v1_existing_ref",
    }
    for adapter in registry["adapters"]:
        assert adapter["hidden_io_permitted"] is False
        assert "knowledge-source/*" in adapter["must_not_write"]
        assert "channels/production.json" in adapter["must_not_write"]
        assert adapter["pinned_repositories"] == {
            "engine_sha": "8830a59d34dc0df9305b53f9bbb9eff63e03d225",
            "source_sha": "acf78596ace8a7366688ccef72b507204d09d9f9",
            "foundation_sha": "e5ef644053d34e89c70d2ceb37521e1c59234832",
        }


def test_m25_2_schemas_are_closed_draft_2020_12_contracts() -> None:
    expected = {
        "m25-source-inventory-v1.schema.json": "knowledge-engine-m25-source-inventory/v1",
        "m25-batch-plan-v1.schema.json": "knowledge-engine-m25-batch-plan/v1",
        "m25-admission-checkpoint-v1.schema.json": (
            "knowledge-engine-m25-admission-checkpoint/v1"
        ),
        "m25-normalized-output-v1.schema.json": (
            "knowledge-engine-m25-normalized-output/v1"
        ),
        "m25-orchestrator-report-v1.schema.json": (
            "knowledge-engine-m25-orchestrator-report/v1"
        ),
    }
    for filename, schema_version in expected.items():
        schema = _load_json(SCHEMA_ROOT / filename)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == schema_version


def test_docs_pin_reuse_fail_closed_and_forbidden_scope() -> None:
    document = (M25_DOC_ROOT / "m25-2-intake-orchestrator.md").read_text(encoding="utf-8")
    lowered = document.lower()
    assert "m25_2_intake_orchestrator_accepted" in document
    assert "intake/v1" in document
    assert "m21_resumable_batch" in document
    assert "no silent exclusion" in lowered
    assert "unresolved acl" in lowered
    assert "unresolved licence" in lowered
    assert "live extraction" in lowered
    assert "continuous unbounded queue" in lowered
    assert "source mutation" in lowered


def test_operator_run_time_does_not_change_immutable_intake_identity(tmp_path: Path) -> None:
    (tmp_path / "stable.md").write_text("stable\n", encoding="utf-8")
    descriptors = [_descriptor("stable.md")]
    inventory = build_source_inventory(
        descriptors,
        captured_at="2026-07-23T00:00:00Z",
        allowed_root=tmp_path,
    )
    bundle = build_plan_bundle(
        inventory,
        created_at="2026-07-23T00:00:00Z",
    )
    outputs = []
    for index, run_at in enumerate(
        ("2026-07-23T01:00:00Z", "2026-07-24T01:00:00Z"),
        start=1,
    ):
        store = FileObjectStore(tmp_path / f"store-{index}")
        persist_plan_bundle(store, bundle)
        result = resume_orchestrator(
            store,
            bundle["admission_plan"]["plan_id"],
            allowed_root=tmp_path,
            run_at=run_at,
        )
        assert result["report"]["ready_for_m25_3"] is True
        path = next(
            (tmp_path / f"store-{index}" / "admission" / "v1" / "normalized").rglob(
                "*.json"
            )
        )
        outputs.append(path.read_bytes())
    assert outputs[0] == outputs[1]


def test_future_retry_time_pauses_resume_without_consuming_attempt(tmp_path: Path) -> None:
    (tmp_path / "later.md").write_text("later\n", encoding="utf-8")
    store, bundle = _prepare(tmp_path, [_descriptor("later.md")], max_attempts=3)

    def delayed_executor(
        store_value: object,
        item: object,
        allowed_root: Path | None,
        run_at: str,
    ) -> AdapterOutcome:
        del store_value, item, allowed_root, run_at
        return AdapterOutcome(
            status="retryable",
            failure_code="FIXTURE_DELAY",
            retry_at="2026-07-24T00:00:00Z",
        )

    first = resume_orchestrator(
        store,
        bundle["admission_plan"]["plan_id"],
        allowed_root=tmp_path,
        run_at="2026-07-23T00:00:00Z",
        max_items=5,
        executors={LOCAL_MARKDOWN_ADAPTER: delayed_executor},
    )
    state = first["checkpoint"]["states"][0]
    assert state["state"] == "retryable"
    assert state["attempts"] == 1
    assert "reason:FIXTURE_DELAY" in state["evidence_refs"]
    assert first["report"]["population"]["actionable_source_count"] == 1

    second = resume_orchestrator(
        store,
        bundle["admission_plan"]["plan_id"],
        allowed_root=tmp_path,
        run_at="2026-07-23T12:00:00Z",
        max_items=5,
        executors={LOCAL_MARKDOWN_ADAPTER: delayed_executor},
    )
    assert second["checkpoint"]["checkpoint_sha256"] == first["checkpoint"][
        "checkpoint_sha256"
    ]
    assert second["checkpoint"]["states"][0]["attempts"] == 1


def test_existing_intake_adapter_verifies_exact_reference_bindings(tmp_path: Path) -> None:
    source = tmp_path / "existing.md"
    source.write_text("existing\n", encoding="utf-8")
    first_store, first_bundle = _prepare(tmp_path, [_descriptor("existing.md")])
    resume_orchestrator(
        first_store,
        first_bundle["admission_plan"]["plan_id"],
        allowed_root=tmp_path,
        run_at="2026-07-23T00:00:00Z",
    )
    output_path = next(
        (tmp_path / "store" / "admission" / "v1" / "normalized").rglob("*.json")
    )
    output = _load_json(output_path)
    item = first_bundle["inventory"]["items"][0]
    local_result_key = next(
        path.relative_to(tmp_path / "store").as_posix()
        for path in (tmp_path / "store" / "intake" / "v1" / "attempts").rglob(
            "result.json"
        )
    )
    result = json.loads(first_store.get(local_result_key))
    result.update(
        {
            "snapshot_key": output["snapshot_ref"]["object_key"],
            "derivative_key": output["derivative_ref"]["object_key"],
            "normalized_key": output["normalized_ref"]["object_key"],
            "raw_blob_key": output["raw_ref"]["object_key"],
        }
    )
    first_store.put(
        local_result_key,
        json.dumps(result, sort_keys=True).encode(),
        content_type="application/json",
    )
    snapshot = json.loads(first_store.get(output["snapshot_ref"]["object_key"]))
    snapshot["snapshot_id"] = output["snapshot_ref"]["snapshot_id"]
    first_store.put(
        output["snapshot_ref"]["object_key"],
        json.dumps(snapshot, sort_keys=True).encode(),
        content_type="application/json",
    )
    derivative = json.loads(first_store.get(output["derivative_ref"]["object_key"]))
    derivative.update(
        {
            "derivative_id": output["derivative_ref"]["derivative_id"],
            "snapshot_id": output["snapshot_ref"]["snapshot_id"],
            "normalized_key": output["normalized_ref"]["object_key"],
        }
    )
    first_store.put(
        output["derivative_ref"]["object_key"],
        json.dumps(derivative, sort_keys=True).encode(),
        content_type="application/json",
    )

    descriptor = _descriptor(
        "existing-ref",
        adapter_id="m25_adapter_intake_v1_existing_ref",
        declared_bytes=item["declared_bytes"],
        expected_content_sha256=item["expected_content_sha256"],
    )
    descriptor["adapter_config"] = {
        "result_key": local_result_key,
        "snapshot_key": output["snapshot_ref"]["object_key"],
        "derivative_key": output["derivative_ref"]["object_key"],
        "normalized_key": output["normalized_ref"]["object_key"],
        "raw_blob_key": output["raw_ref"]["object_key"],
    }
    inventory = build_source_inventory(
        [descriptor],
        captured_at="2026-07-23T00:00:00Z",
    )
    bundle = build_plan_bundle(inventory, created_at="2026-07-23T00:00:00Z")
    persist_plan_bundle(first_store, bundle)
    result = resume_orchestrator(
        first_store,
        bundle["admission_plan"]["plan_id"],
        allowed_root=None,
        run_at="2026-07-24T00:00:00Z",
    )
    assert result["report"]["ready_for_m25_3"] is True
    assert result["report"]["state_counts"]["normalized"] == 1


def test_ci_and_operator_entrypoint_are_forward_compatible() -> None:
    legacy_workflow = (
        ROOT / ".github" / "workflows" / "m25-1-admission-architecture.yml"
    ).read_text(encoding="utf-8")
    current_workflow = (
        ROOT / ".github" / "workflows" / "m25-2-intake-orchestrator.yml"
    ).read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "docs/architecture/m25/**" not in legacy_workflow
    assert "schemas/m25-*.schema.json" not in legacy_workflow
    assert "Protect frozen M25.1 artifacts" in legacy_workflow
    assert "Verify exact workflow head" in current_workflow
    assert "Prove deterministic operator vertical slice" in current_workflow
    assert "continuous unbounded queue" in (
        M25_DOC_ROOT / "m25-2-intake-orchestrator.md"
    ).read_text(encoding="utf-8").lower()
    assert (
        'knowledge-m25-admission = "knowledge_engine.m25_intake_orchestrator_cli:main"'
        in project
    )


