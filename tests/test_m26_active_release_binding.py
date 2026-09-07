from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from knowledge_engine.m26_active_release_binding import (
    ActiveReleaseBindingError,
    load_active_release_binding,
)

RELEASE_ID = "m26blog-successor-test-001"
SOURCE_SHA = "1" * 40
ADMISSION_SHA = "2" * 64
QDRANT_COLLECTION = "m26_blog_successor_test_001"


class FakeStore:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)

    def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]


def _pretty(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _artifact(kind: str) -> dict[str, Any]:
    payload = f"{kind}-payload".encode()
    return {
        "kind": kind,
        "key": f"releases/{RELEASE_ID}/artifacts/{kind}.json",
        "sha256": _sha(payload),
        "bytes": len(payload),
        "media_type": "application/json",
        "required": True,
    }


def _valid_objects() -> dict[str, bytes]:
    artifacts = [
        _artifact("graph"),
        _artifact("graph_v2"),
        _artifact("lexical_index"),
        _artifact("provenance"),
        _artifact("semantic_inputs"),
    ]
    candidate = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": RELEASE_ID,
        "status": "candidate",
        "authority": {
            "source_admitted": True,
            "candidate_release_authorized": True,
            "semantic_serving_authorized": True,
            "production_pointer_authorized": False,
            "public_production_traffic_authorized": False,
        },
        "identities": {
            "source_commit_sha": SOURCE_SHA,
            "admission_sha256": ADMISSION_SHA,
        },
        "counts": {
            "document_sources": 181,
            "document_graph_nodes": 4500,
            "document_graph_edges": 9000,
            "semantic_documents": 4501,
        },
        "artifacts": artifacts,
    }
    candidate_bytes = _pretty(candidate)
    candidate_sha = _sha(candidate_bytes)

    production = deepcopy(candidate)
    production["status"] = "production"
    production["authority"]["production_pointer_authorized"] = True
    production["production_promotion"] = {
        "schema_version": "knowledge-engine-m26-blog-sync-production-promotion/v1",
        "status": "production_pointer_authorized",
        "source_candidate_channel": "candidate-blog-sync",
        "source_candidate_manifest_key": f"releases/{RELEASE_ID}/manifest.json",
        "source_candidate_manifest_sha256": candidate_sha,
        "production_pointer_authorized": True,
        "public_production_traffic_authorized": False,
        "qdrant_candidate_collection": QDRANT_COLLECTION,
    }
    production_bytes = _pretty(production)
    pointer = {
        "schema_version": "1.0",
        "channel": "production",
        "release_id": RELEASE_ID,
        "manifest_key": f"releases/{RELEASE_ID}/promotion/production-manifest.json",
        "manifest_sha256": _sha(production_bytes),
        "promoted_at": "2026-09-07T00:00:00Z",
        "production_authority": True,
        "public_production_traffic_mutated": False,
    }
    return {
        "channels/production.json": _pretty(pointer),
        f"releases/{RELEASE_ID}/promotion/production-manifest.json": production_bytes,
        f"releases/{RELEASE_ID}/manifest.json": candidate_bytes,
    }


def _rewrite_json(objects: dict[str, bytes], key: str, mutate: Any) -> None:
    value = json.loads(objects[key])
    mutate(value)
    objects[key] = _pretty(value)


def test_active_release_binding_follows_pointer_instead_of_legacy_constants() -> None:
    binding = load_active_release_binding(FakeStore(_valid_objects()))

    assert binding.release_id == RELEASE_ID
    assert binding.qdrant_collection == QDRANT_COLLECTION
    assert binding.qdrant_point_count == 4501
    assert binding.source_commit_sha == SOURCE_SHA
    assert binding.admission_sha256 == ADMISSION_SHA
    assert binding.production_manifest_key == (
        f"releases/{RELEASE_ID}/promotion/production-manifest.json"
    )
    assert binding.candidate_manifest_key == f"releases/{RELEASE_ID}/manifest.json"
    assert len(binding.identity_sha256) == 64


def test_missing_production_pointer_fails_closed_without_legacy_fallback() -> None:
    objects = _valid_objects()
    objects.pop("channels/production.json")

    with pytest.raises(ActiveReleaseBindingError, match="ACTIVE_RELEASE_POINTER_MISSING"):
        load_active_release_binding(FakeStore(objects))


def test_pointer_manifest_digest_mismatch_fails_closed() -> None:
    objects = _valid_objects()
    _rewrite_json(
        objects,
        "channels/production.json",
        lambda pointer: pointer.__setitem__("manifest_sha256", "f" * 64),
    )

    with pytest.raises(
        ActiveReleaseBindingError,
        match="ACTIVE_RELEASE_PRODUCTION_MANIFEST_DIGEST_MISMATCH",
    ):
        load_active_release_binding(FakeStore(objects))


def test_pointer_release_path_escape_fails_closed_before_fetch() -> None:
    objects = _valid_objects()
    _rewrite_json(
        objects,
        "channels/production.json",
        lambda pointer: pointer.__setitem__(
            "manifest_key", f"releases/{RELEASE_ID}/../other/production.json"
        ),
    )

    with pytest.raises(ActiveReleaseBindingError, match="ACTIVE_RELEASE_PATH_ESCAPE"):
        load_active_release_binding(FakeStore(objects))


def test_production_manifest_release_mismatch_fails_closed() -> None:
    objects = _valid_objects()
    production_key = f"releases/{RELEASE_ID}/promotion/production-manifest.json"
    _rewrite_json(
        objects,
        production_key,
        lambda manifest: manifest.__setitem__("release_id", "different-release"),
    )
    production_sha = _sha(objects[production_key])
    _rewrite_json(
        objects,
        "channels/production.json",
        lambda pointer: pointer.__setitem__("manifest_sha256", production_sha),
    )

    with pytest.raises(
        ActiveReleaseBindingError,
        match="ACTIVE_RELEASE_PRODUCTION_MANIFEST_RELEASE_MISMATCH",
    ):
        load_active_release_binding(FakeStore(objects))


def test_candidate_manifest_digest_mismatch_fails_closed() -> None:
    objects = _valid_objects()
    candidate_key = f"releases/{RELEASE_ID}/manifest.json"
    _rewrite_json(
        objects,
        candidate_key,
        lambda manifest: manifest["counts"].__setitem__("semantic_documents", 9999),
    )

    with pytest.raises(
        ActiveReleaseBindingError,
        match="ACTIVE_RELEASE_CANDIDATE_MANIFEST_DIGEST_MISMATCH",
    ):
        load_active_release_binding(FakeStore(objects))


def test_runtime_artifact_path_escape_fails_closed() -> None:
    objects = _valid_objects()
    candidate_key = f"releases/{RELEASE_ID}/manifest.json"
    production_key = f"releases/{RELEASE_ID}/promotion/production-manifest.json"

    def mutate_candidate(manifest: dict[str, Any]) -> None:
        manifest["artifacts"][0]["key"] = f"releases/{RELEASE_ID}/../foreign/graph.json"

    _rewrite_json(objects, candidate_key, mutate_candidate)
    candidate_sha = _sha(objects[candidate_key])

    def mutate_production(manifest: dict[str, Any]) -> None:
        manifest["production_promotion"]["source_candidate_manifest_sha256"] = candidate_sha

    _rewrite_json(objects, production_key, mutate_production)
    production_sha = _sha(objects[production_key])
    _rewrite_json(
        objects,
        "channels/production.json",
        lambda pointer: pointer.__setitem__("manifest_sha256", production_sha),
    )

    with pytest.raises(ActiveReleaseBindingError, match="ACTIVE_RELEASE_PATH_ESCAPE"):
        load_active_release_binding(FakeStore(objects))


def test_production_and_candidate_runtime_artifact_family_must_match() -> None:
    objects = _valid_objects()
    production_key = f"releases/{RELEASE_ID}/promotion/production-manifest.json"

    def mutate_production(manifest: dict[str, Any]) -> None:
        for artifact in manifest["artifacts"]:
            if artifact["kind"] == "graph_v2":
                artifact["sha256"] = "e" * 64

    _rewrite_json(objects, production_key, mutate_production)
    production_sha = _sha(objects[production_key])
    _rewrite_json(
        objects,
        "channels/production.json",
        lambda pointer: pointer.__setitem__("manifest_sha256", production_sha),
    )

    with pytest.raises(
        ActiveReleaseBindingError,
        match="ACTIVE_RELEASE_ARTIFACT_FAMILY_MISMATCH: graph_v2",
    ):
        load_active_release_binding(FakeStore(objects))
