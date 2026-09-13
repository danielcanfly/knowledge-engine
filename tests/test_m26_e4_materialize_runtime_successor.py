from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest
from scripts.m26_e4_build_runtime_bundle import (
    canonical_json_bytes,
    section_identity_evidence,
    sha256_bytes,
)

from knowledge_engine.storage import FileObjectStore

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "m26_e4_materialize_runtime_successor",
    SCRIPTS / "m26_e4_materialize_runtime_successor.py",
)
assert SPEC is not None and SPEC.loader is not None
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def _bundle(tmp_path: Path) -> tuple[Path, str]:
    bundle = tmp_path / "bundle"
    release = "candidate-test-release"
    artifact = bundle / "releases" / release / "artifacts" / "lexical.json"
    manifest = bundle / "releases" / release / "manifest.json"
    artifact.parent.mkdir(parents=True)
    artifact_data = b'{"documents":[]}\n'
    artifact.write_bytes(artifact_data)
    manifest.write_bytes(
        canonical_json_bytes(
            {
                "release_id": release,
                "status": "candidate",
                "artifacts": [
                    {
                        "kind": "lexical_index",
                        "key": artifact.relative_to(bundle).as_posix(),
                        "sha256": sha256_bytes(artifact_data),
                        "bytes": len(artifact_data),
                    }
                ],
            }
        )
    )
    fixture_pointer = bundle / "channels/production.json"
    fixture_promotion = bundle / "releases" / release / "promotion/fixture.json"
    sidecar = bundle / "releases" / release / "unlisted-sidecar.json"
    fixture_pointer.parent.mkdir(parents=True)
    fixture_pointer.write_bytes(b'{"validation_fixture_only":true}\n')
    fixture_promotion.parent.mkdir(parents=True)
    fixture_promotion.write_bytes(b'{"validation_fixture_only":true}\n')
    sidecar.write_bytes(b'{"unlisted":true}\n')
    return bundle, manifest.relative_to(bundle).as_posix()


def test_manifest_is_deferred_until_explicit_finalization(tmp_path: Path) -> None:
    bundle, manifest_key = _bundle(tmp_path)
    store = FileObjectStore(tmp_path / "store")

    artifacts = subject.stage_bundle_artifacts_to_r2(
        store,
        bundle,
        manifest_key,
    )

    assert artifacts["manifest_deferred"] is True
    assert store.head(manifest_key) is None
    assert len(artifacts["uploaded"]) == 1
    assert store.head("channels/production.json") is None
    assert store.head("releases/candidate-test-release/promotion/fixture.json") is None
    assert store.head("releases/candidate-test-release/unlisted-sidecar.json") is None

    finalized = subject.finalize_candidate_manifest(store, bundle, manifest_key)
    assert finalized["created"] is True
    assert finalized["verified_exact"] is True
    assert store.head(manifest_key) is not None


def test_exact_replay_reuses_artifacts_and_manifest(tmp_path: Path) -> None:
    bundle, manifest_key = _bundle(tmp_path)
    store = FileObjectStore(tmp_path / "store")
    subject.stage_bundle_artifacts_to_r2(store, bundle, manifest_key)
    subject.finalize_candidate_manifest(store, bundle, manifest_key)

    artifacts = subject.stage_bundle_artifacts_to_r2(store, bundle, manifest_key)
    finalized = subject.finalize_candidate_manifest(store, bundle, manifest_key)

    assert artifacts["uploaded"] == []
    assert len(artifacts["skipped_exact"]) == 1
    assert finalized["created"] is False


def test_manifest_collision_fails_before_artifact_write(tmp_path: Path) -> None:
    bundle, manifest_key = _bundle(tmp_path)
    store = FileObjectStore(tmp_path / "store")
    store.put(
        manifest_key,
        b'{"status":"foreign"}\n',
        content_type="application/json",
        only_if_absent=True,
    )

    with pytest.raises(SystemExit, match="different digest"):
        subject.stage_bundle_artifacts_to_r2(store, bundle, manifest_key)

    artifact_key = manifest_key.replace("manifest.json", "artifacts/lexical.json")
    assert store.head(artifact_key) is None


def test_source_digest_parser_rejects_duplicates_and_missing_digest() -> None:
    assert subject._source_digests(
        {
            "entries": [
                {"source_id": "a", "content_sha256": "a" * 64},
                {"source_id": "b", "content_sha256": "b" * 64},
            ]
        }
    ) == {"a": "a" * 64, "b": "b" * 64}

    with pytest.raises(SystemExit, match="duplicate"):
        subject._source_digests(
            {
                "entries": [
                    {"source_id": "a", "content_sha256": "a" * 64},
                    {"source_id": "a", "content_sha256": "a" * 64},
                ]
            }
        )
    with pytest.raises(SystemExit, match="digest missing"):
        subject._source_digests({"entries": [{"source_id": "a"}]})


def test_section_identity_evidence_requires_exact_unique_parity() -> None:
    evidence = section_identity_evidence(
        [{"section_id": "b"}, {"section_id": "a"}],
        [{"section_id": "a"}, {"section_id": "b"}],
    )
    assert evidence["lexical_semantic_exact_set_equal"] is True
    assert evidence["lexical_duplicate_count"] == 0
    assert evidence["semantic_missing_count"] == 0

    with pytest.raises(SystemExit, match="duplicated"):
        section_identity_evidence(
            [{"section_id": "a"}, {"section_id": "a"}],
            [{"section_id": "a"}, {"section_id": "b"}],
        )
    with pytest.raises(SystemExit, match="sets differ"):
        section_identity_evidence(
            [{"section_id": "a"}],
            [{"section_id": "b"}],
        )


class FakeIndexedQdrant(subject.Qdrant):
    def __init__(self, schema=None, fail_field=None):
        self.schema = dict(schema or {})
        self.fail_field = fail_field
        self.index_requests = []

    def snapshot(self, collection_name=subject.QDRANT_COLLECTION):
        return {
            "status": "green",
            "points_count": 0,
            "indexed_vectors_count": 0,
            "vector_name": subject.QDRANT_VECTOR_NAME,
            "vector_dimension": subject.VECTOR_DIMENSION,
            "distance": subject.QDRANT_DISTANCE,
            "sparse_vectors": None,
            "payload_schema": dict(self.schema),
        }

    def request(self, method, path, body=None):
        assert method == "PUT"
        assert path.endswith("/index?wait=true")
        field = body["field_name"]
        if field == self.fail_field:
            return {"status": "ok", "result": {"status": "failed"}}
        self.index_requests.append(field)
        self.schema[field] = body["field_schema"]
        return {
            "status": "ok",
            "result": {"status": "completed", "operation_id": len(self.index_requests)},
        }


def test_payload_indexes_are_created_and_exact_replay_writes_zero() -> None:
    qdrant = FakeIndexedQdrant()

    operations, after = qdrant.ensure_payload_indexes(qdrant.snapshot())
    replay_operations, replay_after = qdrant.ensure_payload_indexes(after)

    assert [row["field"] for row in operations] == list(subject.CANDIDATE_PAYLOAD_INDEX_SCHEMA)
    assert after["payload_schema"] == subject.CANDIDATE_PAYLOAD_INDEX_SCHEMA
    assert replay_operations == []
    assert replay_after["payload_schema"] == subject.CANDIDATE_PAYLOAD_INDEX_SCHEMA


def test_wrong_payload_index_type_fails_before_any_index_write() -> None:
    qdrant = FakeIndexedQdrant({"release_id": "integer"})

    with pytest.raises(SystemExit, match="index type mismatch"):
        qdrant.ensure_payload_indexes(qdrant.snapshot())

    assert qdrant.index_requests == []


def test_payload_index_failure_is_fail_closed() -> None:
    qdrant = FakeIndexedQdrant(fail_field="source_commit_sha")

    with pytest.raises(SystemExit, match="index creation failed"):
        qdrant.ensure_payload_indexes(qdrant.snapshot())

    assert qdrant.schema == {"release_id": "keyword"}


def test_reused_vector_writes_raw_and_embedding_input_identities(monkeypatch) -> None:
    raw_text = "raw fullwidth dash － preserved"
    normalized_text = "raw fullwidth dash - preserved"
    raw_sha = hashlib.sha256(raw_text.encode()).hexdigest()
    normalized_sha = hashlib.sha256(normalized_text.encode()).hexdigest()
    section = subject.SectionInput(
        section_id="section-a",
        text=normalized_text,
        payload={
            "source_id": "source-1",
            "text_sha256": raw_sha,
            "embedding_input_sha256": normalized_sha,
        },
    )
    point_id = subject.deterministic_point_id(section.section_id)

    class ReuseQdrant:
        def retrieve_points(self, ids, collection_name):
            assert ids == [point_id]
            return [
                {
                    "id": point_id,
                    "vector": {subject.QDRANT_VECTOR_NAME: [1.0] * subject.VECTOR_DIMENSION},
                    "payload": {
                        "section_id": "section-a",
                        "source_id": "source-1",
                        "text_sha256": normalized_sha,
                        "embedding_provider": subject.CLOUDFLARE_PROVIDER,
                        "embedding_model": subject.CLOUDFLARE_MODEL,
                        "vector_dimension": subject.VECTOR_DIMENSION,
                        "vector_name": subject.QDRANT_VECTOR_NAME,
                        "release_id": subject.FAILED_CANDIDATE_RELEASE_ID,
                        "source_commit_sha": subject.EXPECTED_BLOG_SOURCE_SHA,
                        "source_repository_head_sha": subject.EXPECTED_SOURCE_HEAD_SHA,
                        "admission_sha256": subject.EXPECTED_ADMISSION_SHA256,
                        "candidate_release_eligible": True,
                        "production_authority": False,
                    },
                }
            ]

    monkeypatch.setenv("VECTOR_REUSE_COLLECTION", subject.FAILED_CANDIDATE_COLLECTION)
    monkeypatch.setenv("VECTOR_REUSE_RELEASE_ID", subject.FAILED_CANDIDATE_RELEASE_ID)
    points, _, _, lineage = subject.build_points([section], ReuseQdrant())

    assert points[0]["payload"]["text_sha256"] == raw_sha
    assert points[0]["payload"]["embedding_input_sha256"] == normalized_sha
    assert lineage["normalized_embedding_input_identity_verified_count"] == 1
