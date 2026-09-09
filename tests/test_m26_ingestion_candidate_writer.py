from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.m26_ingestion_candidate_writer import (
    CandidateVectorVerification,
    CandidateWriteError,
    build_candidate_release_plan,
    stage_candidate_release,
)
from knowledge_engine.storage import FileObjectStore, ObjectMetadata


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _artifacts(
    *,
    lexical_ids: tuple[str, ...] = ("section-a", "section-b"),
    semantic_ids: tuple[str, ...] = ("section-a", "section-b"),
) -> dict[str, bytes]:
    return {
        "graph": _json_bytes({"nodes": [], "edges": []}),
        "graph_v2": _json_bytes({"nodes": [], "edges": []}),
        "lexical_index": _json_bytes(
            {
                "documents": [
                    {"section_id": section_id, "body": section_id} for section_id in lexical_ids
                ]
            }
        ),
        "provenance": _json_bytes({"records": []}),
        "semantic_inputs": _json_bytes(
            {
                "documents": [
                    {
                        "section_id": section_id,
                        "text": section_id,
                        "payload": {"source_id": "source-1"},
                    }
                    for section_id in semantic_ids
                ]
            }
        ),
    }


def _plan(
    *,
    artifacts: dict[str, bytes] | None = None,
):
    return build_candidate_release_plan(
        release_id="m26blog-test-release-001",
        source_commit_sha="a" * 40,
        source_repository_head_sha="b" * 40,
        admission_sha256="c" * 64,
        source_count=1,
        artifact_bytes=artifacts or _artifacts(),
        created_at="2026-09-07T08:00:00Z",
    )


class RecordingStore(FileObjectStore):
    def __init__(self, root: Path, events: list[str]) -> None:
        super().__init__(root)
        self.events = events

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        sha256: str | None = None,
        expected_etag: str | None = None,
        only_if_absent: bool = False,
    ) -> ObjectMetadata:
        self.events.append(f"r2:{key}")
        return super().put(
            key,
            data,
            content_type=content_type,
            sha256=sha256,
            expected_etag=expected_etag,
            only_if_absent=only_if_absent,
        )


class FakeVectorMaterializer:
    def __init__(
        self,
        events: list[str],
        *,
        section_ids: tuple[str, ...] | None = None,
        fail: bool = False,
    ) -> None:
        self.events = events
        self.section_ids = section_ids
        self.fail = fail
        self.calls = 0

    def materialize_and_verify(
        self,
        *,
        collection_name: str,
        release_id: str,
        semantic_documents: tuple[dict[str, Any], ...],
    ) -> CandidateVectorVerification:
        self.calls += 1
        self.events.append(f"qdrant:{collection_name}")
        if self.fail:
            raise RuntimeError("simulated vector failure")
        section_ids = self.section_ids or tuple(
            str(document["section_id"]) for document in semantic_documents
        )
        return CandidateVectorVerification(
            collection_name=collection_name,
            release_id=release_id,
            point_count=len(section_ids),
            section_ids=section_ids,
            detail={"verified": True},
        )


def test_plan_requires_exact_lexical_semantic_section_parity() -> None:
    with pytest.raises(CandidateWriteError, match="exactly equal"):
        _plan(
            artifacts=_artifacts(
                lexical_ids=("section-a", "section-b"),
                semantic_ids=("section-a", "section-c"),
            )
        )


def test_plan_derives_release_scoped_candidate_collection() -> None:
    plan = _plan()

    assert plan.qdrant_collection == "m26_blog_m26blog_test_release_001"
    assert plan.manifest_key == ("releases/m26blog-test-release-001/manifest.json")
    assert not plan.manifest_key.startswith("channels/")


def test_manifest_is_written_only_after_artifacts_and_vector_verify(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plan = _plan()
    store = RecordingStore(tmp_path, events)
    vector = FakeVectorMaterializer(events)

    receipt = stage_candidate_release(
        store=store,
        vector_materializer=vector,
        plan=plan,
    )

    assert receipt["status"] == "candidate_release_finalized"
    assert receipt["authority"]["production_pointer_writes"] == 0
    assert events[-2] == f"qdrant:{plan.qdrant_collection}"
    assert events[-1] == f"r2:{plan.manifest_key}"
    assert all("channels/production.json" not in event for event in events)


def test_vector_failure_leaves_only_unfinalized_candidate_objects(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plan = _plan()
    store = RecordingStore(tmp_path, events)
    vector = FakeVectorMaterializer(events, fail=True)

    with pytest.raises(RuntimeError, match="simulated vector failure"):
        stage_candidate_release(
            store=store,
            vector_materializer=vector,
            plan=plan,
        )

    assert store.head(plan.manifest_key) is None
    assert all(store.head(key) is not None for key in plan.artifact_keys.values())
    assert all("channels/" not in event for event in events)


def test_artifact_collision_fails_before_vector_write(tmp_path: Path) -> None:
    events: list[str] = []
    plan = _plan()
    store = RecordingStore(tmp_path, events)
    vector = FakeVectorMaterializer(events)
    first_key = plan.artifact_keys[sorted(plan.artifact_keys)[0]]
    store.put(
        first_key,
        b'{"drift":true}\n',
        content_type="application/json",
        only_if_absent=True,
    )

    with pytest.raises(CandidateWriteError, match="digest mismatch"):
        stage_candidate_release(
            store=store,
            vector_materializer=vector,
            plan=plan,
        )

    assert vector.calls == 0
    assert store.head(plan.manifest_key) is None


def test_vector_section_drift_fails_closed_before_manifest(tmp_path: Path) -> None:
    events: list[str] = []
    plan = _plan()
    store = RecordingStore(tmp_path, events)
    vector = FakeVectorMaterializer(
        events,
        section_ids=("section-a", "section-c"),
    )

    with pytest.raises(CandidateWriteError, match="section_id set"):
        stage_candidate_release(
            store=store,
            vector_materializer=vector,
            plan=plan,
        )

    assert store.head(plan.manifest_key) is None


def test_exact_replay_reuses_immutable_objects_and_manifest(tmp_path: Path) -> None:
    events: list[str] = []
    plan = _plan()
    store = RecordingStore(tmp_path, events)
    vector = FakeVectorMaterializer(events)

    first = stage_candidate_release(
        store=store,
        vector_materializer=vector,
        plan=plan,
    )
    first_event_count = len(events)
    second = stage_candidate_release(
        store=store,
        vector_materializer=vector,
        plan=plan,
    )

    assert first["manifest_created"] is True
    assert second["manifest_created"] is False
    assert second["artifacts_created"] == []
    assert sorted(second["artifacts_reused_exact"]) == sorted(plan.artifact_keys)
    assert vector.calls == 2
    assert len(events) == first_event_count + 1
    assert events[-1] == f"qdrant:{plan.qdrant_collection}"


def test_missing_runtime_artifact_fails_before_any_write() -> None:
    artifacts = _artifacts()
    artifacts.pop("provenance")

    with pytest.raises(CandidateWriteError, match="missing"):
        _plan(artifacts=artifacts)


def test_preexisting_manifest_collision_is_fail_closed(tmp_path: Path) -> None:
    events: list[str] = []
    plan = _plan()
    store = RecordingStore(tmp_path, events)
    vector = FakeVectorMaterializer(events)
    store.put(
        plan.manifest_key,
        b'{"wrong":"manifest"}\n',
        content_type="application/json",
        only_if_absent=True,
    )

    with pytest.raises(CandidateWriteError, match="digest mismatch"):
        stage_candidate_release(
            store=store,
            vector_materializer=vector,
            plan=plan,
        )

    assert vector.calls == 0
