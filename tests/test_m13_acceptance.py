from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.m13_acceptance import (
    IsolatedObjectStore,
    M13AcceptanceError,
    _run_three_batch_acceptance,
    run_isolated_acceptance,
)
from knowledge_engine.storage import FileObjectStore, sha256_bytes

ENGINE_SHA = "6c901981b6a0cb4ca36985f39875b645c43df5b7"
SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"


def _base_store(tmp_path: Path) -> tuple[FileObjectStore, bytes, str]:
    store = FileObjectStore(tmp_path / "store")
    pointer = (
        json.dumps(
            {
                "channel": "production",
                "manifest_key": "releases/real/manifest.json",
                "manifest_sha256": "a" * 64,
                "release_id": "20260708T040116Z-69a9f445699a",
                "schema_version": "1.0",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    digest = sha256_bytes(pointer)
    store.put(
        "channels/production.json",
        pointer,
        content_type="application/json",
        sha256=digest,
    )
    return store, pointer, digest


def test_three_batch_acceptance_replays_and_detects_collision(
    tmp_path: Path,
) -> None:
    store, real_pointer, real_pointer_sha = _base_store(tmp_path)
    report, receipt = run_isolated_acceptance(
        store,
        run_id="unit-three-batch",
        engine_sha=ENGINE_SHA,
        canonical_source_sha=SOURCE_SHA,
        expected_real_production_pointer_sha256=real_pointer_sha,
    )
    assert report["result"] == "passed"
    assert report["promoted_batch_count"] == 3
    assert report["operator_reconstruction"]["audit_passed"] is True
    assert report["operator_reconstruction"]["stale_finding_count"] == 0
    assert report["operator_reconstruction"]["state_counts"] == {
        "abandoned": 2,
        "closed": 3,
        "rejected": 2,
    }
    assert report["lifecycle_cases"]["capacity_rejection_code"] == (
        "M13_CANDIDATE_CAPACITY_EXHAUSTED"
    )
    assert report["lifecycle_cases"]["production_busy_code"] == (
        "M13_PRODUCTION_LEASE_BUSY"
    )
    assert report["lifecycle_cases"]["stale_expected_previous_code"] == (
        "M13_PRODUCTION_EXPECTED_PREVIOUS_STALE"
    )
    assert report["retention"]["deletion_candidate_count"] == 0
    assert report["immutable_evidence"]["overwritten_object_count"] == 0
    assert report["governance"]["real_production_write_performed"] is False
    assert receipt.real_production_pointer_unchanged is True
    assert store.get("channels/production.json") == real_pointer

    replay, replay_receipt = run_isolated_acceptance(
        store,
        run_id="unit-three-batch",
        engine_sha=ENGINE_SHA,
        canonical_source_sha=SOURCE_SHA,
        expected_real_production_pointer_sha256=real_pointer_sha,
    )
    assert replay["idempotent"] is True
    assert replay["acceptance_id"] == report["acceptance_id"]
    assert replay["report_sha256"] == report["report_sha256"]
    assert replay_receipt.report_sha256 == receipt.report_sha256

    store.put(
        receipt.report_key,
        b"{not-json}\n",
        content_type="application/json",
        sha256=sha256_bytes(b"{not-json}\n"),
    )
    with pytest.raises(M13AcceptanceError) as collision:
        run_isolated_acceptance(
            store,
            run_id="unit-three-batch",
            engine_sha=ENGINE_SHA,
            canonical_source_sha=SOURCE_SHA,
            expected_real_production_pointer_sha256=real_pointer_sha,
        )
    assert collision.value.code == "M13_ACCEPTANCE_REPORT_COLLISION"
    assert store.get("channels/production.json") == real_pointer


def test_acceptance_requires_exact_real_pointer(tmp_path: Path) -> None:
    store, _, _ = _base_store(tmp_path)
    with pytest.raises(M13AcceptanceError) as stale:
        run_isolated_acceptance(
            store,
            run_id="stale-real-pointer",
            engine_sha=ENGINE_SHA,
            canonical_source_sha=SOURCE_SHA,
            expected_real_production_pointer_sha256="f" * 64,
        )
    assert stale.value.code == "M13_ACCEPTANCE_REAL_PRODUCTION_STALE"


def test_acceptance_core_requires_isolation(tmp_path: Path) -> None:
    store, _, _ = _base_store(tmp_path)
    with pytest.raises(M13AcceptanceError) as isolated:
        _run_three_batch_acceptance(
            store,  # type: ignore[arg-type]
            engine_sha=ENGINE_SHA,
            canonical_source_sha=SOURCE_SHA,
        )
    assert isolated.value.code == "M13_ACCEPTANCE_ISOLATION_REQUIRED"


def test_isolated_store_prefixes_and_forbids_delete(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    isolated = IsolatedObjectStore(store, "m13/acceptance-runs/unit")
    isolated.put(
        "evidence/item.json",
        b"{}\n",
        content_type="application/json",
    )
    assert store.get(
        "m13/acceptance-runs/unit/evidence/item.json"
    ) == b"{}\n"
    with pytest.raises(M13AcceptanceError) as deletion:
        isolated.delete("evidence/item.json")
    assert deletion.value.code == "M13_ACCEPTANCE_DELETE_FORBIDDEN"
    with pytest.raises(M13AcceptanceError) as escape:
        isolated.get("../channels/production.json")
    assert escape.value.code == "M13_ACCEPTANCE_KEY_INVALID"
