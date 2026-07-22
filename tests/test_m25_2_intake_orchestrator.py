from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m25_intake_orchestrator import (
    LOCAL_MARKDOWN_ADAPTER,
    AdapterOutcome,
    build_orchestrator_report,
    build_plan_bundle,
    build_source_inventory,
    execute_next,
    load_plan_bundle,
    resume_orchestrator,
)
from m25_2_test_support import _descriptor, _load_json, _prepare, _unresolved


def test_same_descriptors_and_bytes_produce_identical_inventory_and_plan(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("# Alpha\n\nDeterministic.\n", encoding="utf-8")
    descriptors = [_descriptor("a.md")]
    first_inventory = build_source_inventory(
        descriptors,
        captured_at="2026-07-23T00:00:00Z",
        allowed_root=tmp_path,
    )
    second_inventory = build_source_inventory(
        descriptors,
        captured_at="2026-07-23T00:00:00Z",
        allowed_root=tmp_path,
    )
    assert first_inventory == second_inventory

    first = build_plan_bundle(
        first_inventory,
        created_at="2026-07-23T00:00:00Z",
    )
    second = build_plan_bundle(
        second_inventory,
        created_at="2026-07-23T00:00:00Z",
    )
    for key in (
        "adapter_registry",
        "authority_envelope",
        "admission_plan",
        "batch_plan",
        "m21_compatibility_plan",
        "checkpoint",
    ):
        assert first[key] == second[key]


def test_full_population_has_explicit_policy_size_and_adapter_blocks(
    tmp_path: Path,
) -> None:
    (tmp_path / "valid.md").write_text("valid\n", encoding="utf-8")
    (tmp_path / "policy.md").write_text("policy\n", encoding="utf-8")
    (tmp_path / "large.md").write_text("x" * 80, encoding="utf-8")
    descriptors = [
        _descriptor("valid.md"),
        _descriptor("policy.md", license_value=_unresolved()),
        _descriptor("large.md"),
        _descriptor(
            "remote-item",
            adapter_id="m25_adapter_unapproved_fixture",
            declared_bytes=10,
            expected_content_sha256="a" * 64,
        ),
    ]
    inventory = build_source_inventory(
        descriptors,
        captured_at="2026-07-23T00:00:00Z",
        allowed_root=tmp_path,
    )
    bundle = build_plan_bundle(
        inventory,
        max_sources_per_batch=2,
        max_bytes_per_batch=32,
        created_at="2026-07-23T00:00:00Z",
    )
    population = bundle["batch_plan"]["population"]
    reasons = {item["reason_code"] for item in bundle["batch_plan"]["blocked_items"]}
    assert population == {
        "inventory_source_count": 4,
        "inventory_total_declared_bytes": 6 + 7 + 80 + 10,
        "executable_source_count": 1,
        "blocked_source_count": 3,
        "planned_batch_count": 1,
        "coverage_complete": True,
    }
    assert reasons == {
        "LICENSE_UNRESOLVED",
        "SOURCE_EXCEEDS_BATCH_BYTES",
        "ADAPTER_NOT_APPROVED",
    }
    counts = bundle["checkpoint"]["state_counts"]
    assert counts["planned"] == 1
    assert counts["blocked"] == 3
    assert bundle["checkpoint"]["population_complete"] is True


def test_local_markdown_execution_reuses_intake_and_emits_reference_only_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Source\n\nEvidence.\n", encoding="utf-8")
    store, bundle = _prepare(tmp_path, [_descriptor("source.md")])
    result = resume_orchestrator(
        store,
        bundle["admission_plan"]["plan_id"],
        allowed_root=tmp_path,
        run_at="2026-07-23T00:00:00Z",
        max_items=5,
    )
    report = result["report"]
    assert report["ready_for_m25_3"] is True
    assert report["state_counts"]["normalized"] == 1
    assert report["source_mutation_performed"] is False
    assert report["silent_exclusion_count"] == 0

    output_files = list(
        (tmp_path / "store" / "admission" / "v1" / "normalized").rglob("*.json")
    )
    assert len(output_files) == 1
    output = _load_json(output_files[0])
    assert output["authority"] == "candidate_only"
    assert output["canonical_knowledge"] is False
    assert output["production_authority"] is False
    assert output["source_mutation_permitted"] is False
    assert "text" not in output
    assert output["raw_ref"]["object_key"].startswith("intake/v1/raw/")
    assert output["snapshot_ref"]["object_key"].startswith("intake/v1/snapshots/")
    assert output["normalized_ref"]["object_key"].startswith("intake/v1/normalized/")
    assert not list((tmp_path / "store").glob("knowledge-source/**"))


def test_retryable_adapter_is_bounded_and_becomes_explicit_block(
    tmp_path: Path,
) -> None:
    (tmp_path / "retry.md").write_text("retry\n", encoding="utf-8")
    store, bundle = _prepare(
        tmp_path,
        [_descriptor("retry.md")],
        max_attempts=2,
    )

    def retrying_executor(
        store_value: object,
        item: object,
        allowed_root: Path | None,
        run_at: str,
    ) -> AdapterOutcome:
        del store_value, item, allowed_root
        return AdapterOutcome(
            status="retryable",
            failure_code="TEMPORARY_FIXTURE_FAILURE",
            retry_at=run_at,
        )

    result = resume_orchestrator(
        store,
        bundle["admission_plan"]["plan_id"],
        allowed_root=tmp_path,
        run_at="2026-07-23T00:00:00Z",
        max_items=3,
        executors={LOCAL_MARKDOWN_ADAPTER: retrying_executor},
    )
    checkpoint = result["checkpoint"]
    state = checkpoint["states"][0]
    assert state["state"] == "blocked"
    assert state["attempts"] == 2
    assert "reason:RETRY_ATTEMPTS_EXHAUSTED" in state["evidence_refs"]
    assert result["report"]["retries_bounded"] is True
    assert result["report"]["population"]["coverage_complete"] is True


def test_resume_uses_latest_checkpoint_head_and_rejects_revision_collision(
    tmp_path: Path,
) -> None:
    (tmp_path / "resume.md").write_text("resume\n", encoding="utf-8")
    store, bundle = _prepare(tmp_path, [_descriptor("resume.md")])
    plan_id = bundle["admission_plan"]["plan_id"]
    loaded = load_plan_bundle(store, plan_id)
    advanced = execute_next(
        store,
        loaded["admission_plan"],
        loaded["batch_plan"],
        loaded["inventory"],
        loaded["checkpoint"],
        allowed_root=tmp_path,
        run_at="2026-07-23T00:00:00Z",
    )
    reloaded = load_plan_bundle(store, plan_id)
    assert reloaded["checkpoint"] == advanced

    stale = dict(bundle["checkpoint"])
    stale["updated_at"] = "2026-07-23T00:00:01Z"
    unsigned = dict(stale)
    unsigned.pop("checkpoint_sha256")
    from knowledge_engine.intake_v1 import canonical_json_bytes
    from knowledge_engine.storage import sha256_bytes

    stale["checkpoint_sha256"] = sha256_bytes(canonical_json_bytes(unsigned))
    with pytest.raises(IntegrityError, match="head moved forward"):
        from knowledge_engine.m25_intake_orchestrator import persist_checkpoint

        persist_checkpoint(store, stale)


def test_report_reconciles_all_denominators_without_silent_exclusion(
    tmp_path: Path,
) -> None:
    (tmp_path / "good.md").write_text("good\n", encoding="utf-8")
    (tmp_path / "blocked.md").write_text("blocked\n", encoding="utf-8")
    store, bundle = _prepare(
        tmp_path,
        [
            _descriptor("good.md"),
            _descriptor("blocked.md", license_value=_unresolved()),
        ],
    )
    result = resume_orchestrator(
        store,
        bundle["admission_plan"]["plan_id"],
        allowed_root=tmp_path,
        run_at="2026-07-23T00:00:00Z",
        max_items=5,
    )
    report = build_orchestrator_report(
        bundle["admission_plan"],
        bundle["batch_plan"],
        bundle["inventory"],
        result["checkpoint"],
    )
    assert report["population"] == {
        "inventory_source_count": 2,
        "terminal_source_count": 2,
        "actionable_source_count": 0,
        "in_flight_source_count": 0,
        "accounted_source_count": 2,
        "coverage_complete": True,
    }
    assert report["state_counts"]["normalized"] == 1
    assert report["state_counts"]["blocked"] == 1
    assert report["silent_exclusion_count"] == 0


