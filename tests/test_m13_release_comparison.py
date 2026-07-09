from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.m13_contracts import (
    M13BatchRecord,
    M13BatchSeed,
    ProductionIdentity,
    stable_json_bytes,
)
from knowledge_engine.m13_release_comparison import (
    M13ReleaseComparisonError,
    ReleaseComparisonRequest,
    create_release_comparison,
)
from knowledge_engine.m13_release_inventory import INVENTORY_SCHEMA, ReleaseReference
from knowledge_engine.m13_retention import RetentionReferenceSnapshot, classify_artifact
from knowledge_engine.storage import FileObjectStore, sha256_bytes

BASE_RELEASE = "20260708T040116Z-69a9f445699a"
TARGET_RELEASE = "20260709T100000Z-bbbbbbbbbbbb"
BASE_SOURCE_SHA = "1" * 40
TARGET_SOURCE_SHA = "2" * 40
FOUNDATION_SHA = "3" * 64
BATCH_ID = "mbatch_" + "a" * 32
CHANNEL = "candidate-m13-comparison"


def _put_bytes(
    store: FileObjectStore, key: str, data: bytes
) -> tuple[str, int]:
    digest = sha256_bytes(data)
    store.put(key, data, content_type="application/json", sha256=digest)
    return digest, len(data)


def _put_json(
    store: FileObjectStore, key: str, value: dict[str, Any]
) -> tuple[str, int]:
    return _put_bytes(store, key, stable_json_bytes(value))


def _default_entries() -> dict[str, list[dict[str, Any]]]:
    return {
        "concepts": [{"concept_id": "concept-1", "title": "Original"}],
        "claims": [
            {
                "claim_id": "claim-1",
                "text": "Supported claim",
                "citation_ids": ["citation-1"],
            }
        ],
        "audience": [
            {
                "audience_id": "concept-1",
                "audience": "internal",
                "principals": ["team-a"],
            }
        ],
        "citations": [
            {
                "citation_id": "citation-1",
                "target": "source://one",
                "supports_claim_ids": ["claim-1"],
            }
        ],
        "registry": [
            {
                "registry_id": "registry-1",
                "concept_id": "concept-1",
                "alias": "original",
            }
        ],
        "indexes": [
            {
                "index_id": "index-1",
                "inputs": ["concept-1"],
                "count": 1,
                "digest": "4" * 64,
            }
        ],
    }


def _release(
    store: FileObjectStore,
    *,
    release_id: str,
    prefix: str,
    source_sha: str,
    entries: dict[str, list[dict[str, Any]]] | None = None,
    builder_id: str = "knowledge-builder/1",
    foundation_sha: str = FOUNDATION_SHA,
    canonical_manifest: bool = True,
    artifact_order: list[str] | None = None,
) -> ReleaseReference:
    values = entries or _default_entries()
    artifacts: list[dict[str, Any]] = []
    for artifact_type in artifact_order or sorted(values):
        key = f"{prefix}/{artifact_type}.json"
        schema = f"test-{artifact_type}/v1"
        digest, size = _put_json(
            store,
            key,
            {
                "schema_version": schema,
                "release_id": release_id,
                "entries": values[artifact_type],
            },
        )
        artifacts.append(
            {
                "artifact_type": artifact_type,
                "key": key,
                "sha256": digest,
                "bytes": size,
                "schema_version": schema,
            }
        )
    manifest = {
        "schema_version": f"{INVENTORY_SCHEMA}/manifest",
        "release_id": release_id,
        "source_repository": "danielcanfly/knowledge-source",
        "source_commit_sha": source_sha,
        "builder_id": builder_id,
        "foundation_sha256": foundation_sha,
        "artifacts": artifacts,
    }
    manifest_key = f"{prefix}/manifest.json"
    data = (
        stable_json_bytes(manifest)
        if canonical_manifest
        else (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    )
    manifest_sha, _ = _put_bytes(store, manifest_key, data)
    return ReleaseReference(
        release_id=release_id,
        manifest_key=manifest_key,
        manifest_sha256=manifest_sha,
        source_repository="danielcanfly/knowledge-source",
        source_commit_sha=source_sha,
        builder_id=builder_id,
        foundation_sha256=foundation_sha,
    )


def _request(
    base: ReleaseReference,
    target: ReleaseReference,
    production: ProductionIdentity,
) -> ReleaseComparisonRequest:
    return ReleaseComparisonRequest(
        batch_id=BATCH_ID,
        base_release=base,
        target_release=target,
        expected_previous_production=production,
        requested_by="operator@example.com",
        requested_at="2026-07-09T10:00:00Z",
        generated_at="2026-07-09T10:01:00Z",
        candidate_channel=CHANNEL,
    )


def _fixture(
    tmp_path: Path,
    *,
    target_entries: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[
    FileObjectStore,
    ReleaseReference,
    ReleaseReference,
    ProductionIdentity,
    ReleaseComparisonRequest,
]:
    store = FileObjectStore(tmp_path / "store")
    base = _release(
        store,
        release_id=BASE_RELEASE,
        prefix="releases/base",
        source_sha=BASE_SOURCE_SHA,
    )
    target = _release(
        store,
        release_id=TARGET_RELEASE,
        prefix="candidates/target",
        source_sha=TARGET_SOURCE_SHA,
        entries=target_entries,
    )
    production = ProductionIdentity(
        release_id=BASE_RELEASE,
        manifest_sha256=base.manifest_sha256,
        pointer_sha256="5" * 64,
    )
    return store, base, target, production, _request(base, target, production)


def test_exact_comparison_is_replayable_and_operation_compatible(
    tmp_path: Path,
) -> None:
    entries = _default_entries()
    entries["concepts"] = [
        {"concept_id": "concept-1", "title": "Changed"},
        {"concept_id": "concept-2", "title": "Added"},
    ]
    store, _, _, production, request = _fixture(
        tmp_path, target_entries=entries
    )

    first = create_release_comparison(
        store, request, observed_production=production
    )
    replay = create_release_comparison(
        store, request, observed_production=production
    )

    assert first.added_concepts == ("concept-2",)
    assert first.changed_concepts[0]["stable_id"] == "concept-1"
    assert first.idempotent is False
    assert replay.idempotent is True
    assert replay.comparison_id == first.comparison_id
    assert replay.canonical_bytes() == first.canonical_bytes()
    assert replay.artifact_key == first.artifact_key
    assert replay.canonical_sha256 == first.canonical_sha256

    operation = first.operation_result()
    assert operation.request.kind == "release_comparison"
    assert operation.state == "completed"
    assert operation.evidence_refs == (first.artifact_key,)
    assert operation.request.requires_production_slot is False


def test_audience_narrowing_is_reported_without_blocker(
    tmp_path: Path,
) -> None:
    entries = _default_entries()
    entries["audience"] = [
        {
            "audience_id": "concept-1",
            "audience": "restricted",
            "principals": ["team-a", "team-b"],
        }
    ]
    store, _, _, production, request = _fixture(
        tmp_path, target_entries=entries
    )
    result = create_release_comparison(
        store, request, observed_production=production
    )
    assert result.audience_changes[0]["classification"] == "narrowed"
    assert not any(
        item.startswith("audience_broadening:")
        for item in result.release_blockers
    )


def test_audience_broadening_is_a_release_blocker(tmp_path: Path) -> None:
    entries = _default_entries()
    entries["audience"] = [
        {
            "audience_id": "concept-1",
            "audience": "public",
            "principals": [],
        }
    ]
    store, _, _, production, request = _fixture(
        tmp_path, target_entries=entries
    )
    result = create_release_comparison(
        store, request, observed_production=production
    )
    assert result.audience_changes[0]["classification"] == "broadened"
    assert result.release_blockers == ("audience_broadening:concept-1",)
    assert result.risk_summary["release_blocked"] is True


def test_added_uncited_claim_is_a_release_blocker(tmp_path: Path) -> None:
    entries = _default_entries()
    entries["claims"] = [
        *entries["claims"],
        {
            "claim_id": "claim-2",
            "text": "No support",
            "citation_ids": [],
        },
    ]
    store, _, _, production, request = _fixture(
        tmp_path, target_entries=entries
    )
    result = create_release_comparison(
        store, request, observed_production=production
    )
    assert result.added_claims == ("claim-2",)
    assert "uncited_claim:claim-2" in result.release_blockers


def test_citation_target_substitution_is_reported(tmp_path: Path) -> None:
    entries = _default_entries()
    entries["citations"] = [
        {
            "citation_id": "citation-1",
            "target": "source://substituted",
            "supports_claim_ids": ["claim-1"],
        }
    ]
    store, _, _, production, request = _fixture(
        tmp_path, target_entries=entries
    )
    result = create_release_comparison(
        store, request, observed_production=production
    )
    assert result.citation_changes[0]["stable_id"] == "citation-1"
    assert "target" in result.citation_changes[0]["changed_fields"]


def test_removed_claim_support_is_a_release_blocker(tmp_path: Path) -> None:
    entries = _default_entries()
    entries["claims"] = [
        {
            "claim_id": "claim-1",
            "text": "Supported claim",
            "citation_ids": [],
        }
    ]
    store, _, _, production, request = _fixture(
        tmp_path, target_entries=entries
    )
    result = create_release_comparison(
        store, request, observed_production=production
    )
    assert "claim_support_removed:claim-1" in result.release_blockers


def test_registry_and_index_drift_are_reported(tmp_path: Path) -> None:
    entries = _default_entries()
    entries["registry"] = [
        {
            "registry_id": "registry-1",
            "concept_id": "concept-1",
            "alias": "changed",
        }
    ]
    entries["indexes"] = [
        {
            "index_id": "index-1",
            "inputs": ["concept-1"],
            "count": 2,
            "digest": "6" * 64,
        }
    ]
    store, _, _, production, request = _fixture(
        tmp_path, target_entries=entries
    )
    result = create_release_comparison(
        store, request, observed_production=production
    )
    assert result.registry_changes[0]["change_type"] == "changed"
    assert result.index_changes[0]["change_type"] == "changed"


def test_stale_expected_production_fails_closed(tmp_path: Path) -> None:
    store, _, _, production, request = _fixture(tmp_path)
    observed = ProductionIdentity(
        release_id=production.release_id,
        manifest_sha256=production.manifest_sha256,
        pointer_sha256="7" * 64,
    )
    with pytest.raises(M13ReleaseComparisonError) as stale:
        create_release_comparison(
            store, request, observed_production=observed
        )
    assert stale.value.code == "M13_COMPARISON_EXPECTED_PRODUCTION_STALE"


def test_manifest_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    store, base, target, production, _ = _fixture(tmp_path)
    bad = ReleaseReference(
        **{**target.to_identity(), "manifest_sha256": "8" * 64}
    )
    with pytest.raises(M13ReleaseComparisonError) as mismatch:
        create_release_comparison(
            store,
            _request(base, bad, production),
            observed_production=production,
        )
    assert mismatch.value.code == "M13_RELEASE_HASH_MISMATCH"


def test_source_builder_and_foundation_drift_fail_closed(
    tmp_path: Path,
) -> None:
    store, base, target, production, _ = _fixture(tmp_path)
    cases = (
        (
            {"source_commit_sha": "9" * 40},
            "M13_RELEASE_SOURCE_IDENTITY_DRIFT",
        ),
        (
            {"builder_id": "other-builder/1"},
            "M13_RELEASE_BUILDER_IDENTITY_DRIFT",
        ),
        (
            {"foundation_sha256": "a" * 64},
            "M13_RELEASE_FOUNDATION_IDENTITY_DRIFT",
        ),
    )
    for overrides, code in cases:
        changed = ReleaseReference(**{**target.to_identity(), **overrides})
        with pytest.raises(M13ReleaseComparisonError) as drift:
            create_release_comparison(
                store,
                _request(base, changed, production),
                observed_production=production,
            )
        assert drift.value.code == code


def test_duplicate_claim_id_fails_closed(tmp_path: Path) -> None:
    entries = _default_entries()
    entries["claims"] = [entries["claims"][0], entries["claims"][0]]
    store, _, _, production, request = _fixture(
        tmp_path, target_entries=entries
    )
    with pytest.raises(M13ReleaseComparisonError) as duplicate:
        create_release_comparison(
            store, request, observed_production=production
        )
    assert duplicate.value.code == "M13_COMPARISON_STABLE_ID_DUPLICATE"


def test_unsorted_entries_fail_closed(tmp_path: Path) -> None:
    entries = _default_entries()
    entries["concepts"] = [
        {"concept_id": "concept-2", "title": "Second"},
        {"concept_id": "concept-1", "title": "First"},
    ]
    store, _, _, production, request = _fixture(
        tmp_path, target_entries=entries
    )
    with pytest.raises(M13ReleaseComparisonError) as unsorted:
        create_release_comparison(
            store, request, observed_production=production
        )
    assert unsorted.value.code == "M13_COMPARISON_ENTRIES_UNSORTED"


def test_unsorted_inventory_fails_closed(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    base = _release(
        store,
        release_id=BASE_RELEASE,
        prefix="releases/base",
        source_sha=BASE_SOURCE_SHA,
    )
    target = _release(
        store,
        release_id=TARGET_RELEASE,
        prefix="candidates/target",
        source_sha=TARGET_SOURCE_SHA,
        artifact_order=[
            "registry",
            "concepts",
            "claims",
            "citations",
            "indexes",
            "audience",
        ],
    )
    production = ProductionIdentity(
        BASE_RELEASE, base.manifest_sha256, "5" * 64
    )
    with pytest.raises(M13ReleaseComparisonError) as unsorted:
        create_release_comparison(
            store,
            _request(base, target, production),
            observed_production=production,
        )
    assert unsorted.value.code == "M13_RELEASE_INVENTORY_UNSORTED"


def test_noncanonical_manifest_fails_closed(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    base = _release(
        store,
        release_id=BASE_RELEASE,
        prefix="releases/base",
        source_sha=BASE_SOURCE_SHA,
    )
    target = _release(
        store,
        release_id=TARGET_RELEASE,
        prefix="candidates/target",
        source_sha=TARGET_SOURCE_SHA,
        canonical_manifest=False,
    )
    production = ProductionIdentity(
        BASE_RELEASE, base.manifest_sha256, "5" * 64
    )
    with pytest.raises(M13ReleaseComparisonError) as noncanonical:
        create_release_comparison(
            store,
            _request(base, target, production),
            observed_production=production,
        )
    assert noncanonical.value.code == "M13_RELEASE_JSON_NONCANONICAL"


def test_missing_artifact_fails_closed(tmp_path: Path) -> None:
    store, _, target, production, request = _fixture(tmp_path)
    target_manifest = json.loads(store.get(target.manifest_key))
    missing_key = next(
        item["key"]
        for item in target_manifest["artifacts"]
        if item["artifact_type"] == "claims"
    )
    store.delete(missing_key)
    with pytest.raises(M13ReleaseComparisonError) as missing:
        create_release_comparison(
            store, request, observed_production=production
        )
    assert missing.value.code == "M13_RELEASE_OBJECT_MISSING"


def test_batch_scope_mismatch_fails_closed(tmp_path: Path) -> None:
    store, _, _, production, request = _fixture(tmp_path)
    seed = M13BatchSeed(
        source_repository="danielcanfly/knowledge-source",
        source_commit_sha=TARGET_SOURCE_SHA,
        production=production,
        requested_by="operator@example.com",
        requested_at="2026-07-09T09:00:00Z",
        purpose="M13.5 fixture",
    )
    batch = M13BatchRecord.from_seed(
        seed,
        state="candidate_ready",
        candidate_channel="candidate-other-channel",
    )
    with pytest.raises(M13ReleaseComparisonError) as mismatch:
        create_release_comparison(
            store,
            request,
            observed_production=production,
            batch=batch,
        )
    assert mismatch.value.code in {
        "M13_COMPARISON_BATCH_MISMATCH",
        "M13_COMPARISON_BATCH_CHANNEL_MISMATCH",
    }


def test_existing_divergent_comparison_bytes_are_an_immutable_collision(
    tmp_path: Path,
) -> None:
    store, _, _, production, request = _fixture(tmp_path)
    first = create_release_comparison(
        store, request, observed_production=production
    )
    store.put(
        first.artifact_key,
        b"divergent\n",
        content_type="application/json",
        sha256=sha256_bytes(b"divergent\n"),
    )
    with pytest.raises(M13ReleaseComparisonError) as collision:
        create_release_comparison(
            store, request, observed_production=production
        )
    assert collision.value.code == "M13_COMPARISON_IMMUTABLE_COLLISION"


def test_comparison_evidence_is_permanently_retained(tmp_path: Path) -> None:
    store, _, _, production, request = _fixture(tmp_path)
    result = create_release_comparison(
        store, request, observed_production=production
    )
    artifact = result.retention_artifact()
    references = RetentionReferenceSnapshot(
        observed_at="2026-07-09T10:02:00Z",
        production=production,
    )
    decision = classify_artifact(
        artifact,
        references=references,
        generated_at="2026-07-09T10:03:00Z",
    )
    assert decision.disposition == "permanent"
    assert decision.physical_delete_permitted is False
