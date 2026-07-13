from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m20_embedding_contract import load_json
from knowledge_engine.m20_semantic_artifacts import build_semantic_artifacts
from knowledge_engine.runtime import Runtime
from knowledge_engine.storage import sha256_bytes

ENGINE_SHA = "742b5e76aa5d2b1c29821e5b97b9723b939e309f"
RELEASE_ID = "20260713T000000Z-m203fixture"


class MemoryStore:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def get(self, key: str) -> bytes:
        return self.objects[key]


def _fixture_vectors(
    suite: dict[str, Any],
    dimension: int,
) -> dict[str, list[float]]:
    vectors: dict[str, list[float]] = {}
    documents = sorted(suite["documents"], key=lambda item: item["section_id"])
    for row, document in enumerate(documents):
        vector = [0.0] * dimension
        vector[row] = 1.0
        vectors[document["section_id"]] = vector
    return vectors


def _artifact(
    kind: str,
    key: str,
    data: bytes,
    media_type: str,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "key": key,
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "media_type": media_type,
        "audiences": ["public", "internal"],
        "required": True,
    }


def _release_store(
    tmp_path: Path,
    *,
    semantic_parts: str = "both",
) -> tuple[MemoryStore, dict[str, Any], dict[str, Any]]:
    suite = load_json("benchmarks/m20/bilingual-blog-benchmark-v1.json")
    contract = load_json("benchmarks/m20/provider-contract.fixture.json")
    dimension = contract["model"]["vector_dimension"]
    semantic_dir = tmp_path / "semantic"
    build_semantic_artifacts(
        suite,
        contract,
        _fixture_vectors(suite, dimension),
        semantic_dir,
        builder_engine_sha=ENGINE_SHA,
    )

    sorted_documents = sorted(
        suite["documents"],
        key=lambda item: item["section_id"],
    )
    documents = [
        {
            "concept_id": document["concept_id"],
            "section_id": document["section_id"],
            "audience": document["audience"],
            "path": document["source_path"],
            "body": document["text"],
            "title": document["title"],
            "section_title": document["title"],
            "description": document["text"],
            "excerpt": document["text"],
            "terms": [],
        }
        for document in sorted_documents
    ]
    lexical_bytes = (
        json.dumps({"schema_version": "2.0", "documents": documents}) + "\n"
    ).encode()
    payloads = {
        "lexical_index": (
            "artifacts/lexical-index.json",
            lexical_bytes,
            "application/json",
        ),
        "graph": (
            "artifacts/graph.json",
            b'{"schema_version":"1.1","nodes":[],"edges":[]}\n',
            "application/json",
        ),
        "provenance": (
            "artifacts/provenance.json",
            b'{"schema_version":"1.0","records":[]}\n',
            "application/json",
        ),
    }
    if semantic_parts in {"both", "metadata"}:
        payloads["semantic_metadata"] = (
            "artifacts/semantic-metadata.json",
            (semantic_dir / "semantic-metadata.json").read_bytes(),
            "application/json",
        )
    if semantic_parts in {"both", "vectors"}:
        payloads["semantic_vectors"] = (
            "artifacts/semantic-vectors.f32",
            (semantic_dir / "semantic-vectors.f32").read_bytes(),
            "application/octet-stream",
        )

    objects: dict[str, bytes] = {}
    artifacts: list[dict[str, Any]] = []
    for kind, (relative, data, media_type) in payloads.items():
        key = f"releases/{RELEASE_ID}/{relative}"
        objects[key] = data
        artifacts.append(_artifact(kind, key, data, media_type))
    manifest = {
        "schema_version": "1.0",
        "release_id": RELEASE_ID,
        "created_at": "2026-07-13T00:00:00Z",
        "source": {
            "commit_sha": suite["identities"]["source_commit_sha"],
            "foundation_commit_sha": suite["identities"]["foundation_commit_sha"],
        },
        "artifacts": artifacts,
    }
    manifest_key = f"releases/{RELEASE_ID}/manifest.json"
    manifest_data = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    objects[manifest_key] = manifest_data
    pointer = {
        "release_id": RELEASE_ID,
        "manifest_key": manifest_key,
        "manifest_sha256": sha256_bytes(manifest_data),
    }
    pointer_data = (json.dumps(pointer, sort_keys=True) + "\n").encode()
    objects["channels/staging.json"] = pointer_data
    return MemoryStore(objects), suite, contract


def _rewrite_manifest(
    store: MemoryStore,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    pointer = json.loads(store.objects["channels/staging.json"])
    manifest = json.loads(store.objects[pointer["manifest_key"]])
    mutate(manifest)
    manifest_data = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    store.objects[pointer["manifest_key"]] = manifest_data
    pointer["manifest_sha256"] = sha256_bytes(manifest_data)
    store.objects["channels/staging.json"] = (
        json.dumps(pointer, sort_keys=True) + "\n"
    ).encode()


def test_runtime_loads_verified_semantic_pair_as_memory_map(
    tmp_path: Path,
) -> None:
    store, _, contract = _release_store(tmp_path)
    runtime = Runtime(
        store,
        tmp_path / "cache",
        "staging",
        expected_semantic_model_id=contract["model"]["id"],
        expected_semantic_dimension=contract["model"]["vector_dimension"],
    )

    active = runtime.refresh()

    assert active.semantic_runtime is not None
    assert runtime.semantic_capability() == {
        "status": "ready",
        "memory_mapped": True,
        "diagnostic_enabled": False,
        "artifact_id": active.semantic_runtime.metadata["artifact_id"],
        "row_count": 8,
        "dimension": 64,
        "provider": "deterministic-fixture",
        "model_id": "fixture-token-hash-v1",
    }


def test_semantic_pair_is_optional_but_partial_pair_fails_closed(
    tmp_path: Path,
) -> None:
    no_semantic_store, _, _ = _release_store(
        tmp_path / "none",
        semantic_parts="none",
    )
    runtime = Runtime(no_semantic_store, tmp_path / "none-cache", "staging")
    active = runtime.refresh()
    assert active.semantic_runtime is None
    assert runtime.semantic_capability()["status"] == "unavailable"

    metadata_store, _, _ = _release_store(
        tmp_path / "partial",
        semantic_parts="metadata",
    )
    partial_runtime = Runtime(
        metadata_store,
        tmp_path / "partial-cache",
        "staging",
    )
    with pytest.raises(IntegrityError, match="must be present together"):
        partial_runtime.refresh()
    assert partial_runtime.active is None


def test_vector_diagnostic_is_disabled_by_default(tmp_path: Path) -> None:
    store, _, _ = _release_store(tmp_path)
    runtime = Runtime(store, tmp_path / "cache", "staging")
    runtime.refresh()

    with pytest.raises(IntegrityError, match="diagnostic retrieval is disabled"):
        runtime.query_vector_diagnostic([1.0] + [0.0] * 63, {"public"})


def test_vector_diagnostic_filters_acl_before_serialization(
    tmp_path: Path,
) -> None:
    store, suite, _ = _release_store(tmp_path)
    runtime = Runtime(
        store,
        tmp_path / "cache",
        "staging",
        semantic_diagnostic_enabled=True,
    )
    active = runtime.refresh()
    assert active.semantic_runtime is not None
    documents = active.semantic_runtime.metadata["documents"]
    internal = next(
        document for document in documents if document["audience"] == "internal"
    )
    query = [0.0] * 64
    query[internal["row"]] = 1.0

    public = runtime.query_vector_diagnostic(query, {"public"}, limit=8)
    assert all(result["audience"] == "public" for result in public["results"])
    assert public["retrieval"]["acl_filtered_count"] == 1
    public_sections = {result["section_id"] for result in public["results"]}
    assert internal["section_id"] not in public_sections

    internal_result = runtime.query_vector_diagnostic(
        query,
        {"public", "internal"},
    )
    assert internal_result["results"][0]["section_id"] == internal["section_id"]
    assert internal_result["results"][0]["score"] == 1.0
    assert len(suite["documents"]) == internal_result["retrieval"]["candidate_count"]


def test_semantic_model_policy_mismatch_rejects_refresh(tmp_path: Path) -> None:
    store, _, _ = _release_store(tmp_path)
    runtime = Runtime(
        store,
        tmp_path / "cache",
        "staging",
        expected_semantic_model_id="unexpected-model",
    )

    with pytest.raises(IntegrityError, match="model ID does not match"):
        runtime.refresh()
    assert runtime.active is None


def test_tampered_metadata_preserves_last_known_good(tmp_path: Path) -> None:
    store, _, _ = _release_store(tmp_path)
    runtime = Runtime(store, tmp_path / "cache", "staging")
    active = runtime.refresh()
    metadata_key = f"releases/{RELEASE_ID}/artifacts/semantic-metadata.json"
    tampered = json.loads(store.objects[metadata_key])
    tampered["model"]["model_id"] = "tampered-model"
    tampered_data = (json.dumps(tampered, sort_keys=True) + "\n").encode()
    store.objects[metadata_key] = tampered_data

    def mutate(manifest: dict[str, Any]) -> None:
        entry = next(
            artifact
            for artifact in manifest["artifacts"]
            if artifact["kind"] == "semantic_metadata"
        )
        entry["bytes"] = len(tampered_data)
        entry["sha256"] = sha256_bytes(tampered_data)

    _rewrite_manifest(store, mutate)

    with pytest.raises(IntegrityError, match="metadata digest mismatch"):
        runtime.refresh()
    assert runtime.active is active


def test_query_vector_bounds_are_fail_closed(tmp_path: Path) -> None:
    store, _, _ = _release_store(tmp_path)
    runtime = Runtime(
        store,
        tmp_path / "cache",
        "staging",
        semantic_diagnostic_enabled=True,
    )
    runtime.refresh()

    with pytest.raises(IntegrityError, match="exactly 64"):
        runtime.query_vector_diagnostic([1.0], {"public"})
    with pytest.raises(IntegrityError, match="L2-normalized"):
        runtime.query_vector_diagnostic([0.1] * 64, {"public"})
    with pytest.raises(IntegrityError, match="between 1 and 20"):
        runtime.query_vector_diagnostic(
            [1.0] + [0.0] * 63,
            {"public"},
            limit=21,
        )
