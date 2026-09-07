from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

import pytest

from knowledge_engine.m26_active_production_release import (
    PRODUCTION_POINTER_KEY,
    ActiveProductionReleaseError,
    resolve_active_production_release,
)
from knowledge_engine.storage import sha256_bytes

RELEASE_ID = "successor-release"
SOURCE_SHA = "1" * 40
ADMISSION_SHA = "2" * 64
QDRANT_COLLECTION = "qdrant-successor"
RUNTIME_KINDS = ("graph", "graph_v2", "lexical_index", "provenance")


@dataclass
class FakeStore:
    objects: dict[str, bytes]

    def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _artifact(kind: str, release_id: str) -> dict[str, Any]:
    payload = f"{kind}-payload".encode()
    filename = kind.replace("_", "-")
    return {
        "kind": kind,
        "key": f"releases/{release_id}/artifacts/{filename}.json",
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
        "media_type": "application/json",
        "required": True,
    }


def _fixture(*, release_id: str = RELEASE_ID) -> tuple[FakeStore, dict[str, str]]:
    candidate_key = f"releases/{release_id}/manifest.json"
    production_key = f"releases/{release_id}/promotion/production-manifest.json"
    artifacts = [_artifact(kind, release_id) for kind in RUNTIME_KINDS]
    artifacts.append(_artifact("semantic_inputs", release_id))
    candidate = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": release_id,
        "status": "candidate",
        "authority": {
            "production_pointer_authorized": False,
        },
        "identities": {
            "source_commit_sha": SOURCE_SHA,
            "admission_sha256": ADMISSION_SHA,
        },
        "counts": {
            "document_graph_nodes": 4500,
            "document_graph_edges": 9000,
            "semantic_documents": 4424,
        },
        "artifacts": artifacts,
    }
    candidate_bytes = _json_bytes(candidate)
    candidate_sha = sha256_bytes(candidate_bytes)

    production = copy.deepcopy(candidate)
    production["status"] = "production"
    production["authority"]["production_pointer_authorized"] = True
    production["production_promotion"] = {
        "production_pointer_authorized": True,
        "source_candidate_manifest_key": candidate_key,
        "source_candidate_manifest_sha256": candidate_sha,
        "qdrant_candidate_collection": QDRANT_COLLECTION,
    }
    production_bytes = _json_bytes(production)
    production_sha = sha256_bytes(production_bytes)

    pointer = {
        "schema_version": "1.0",
        "channel": "production",
        "release_id": release_id,
        "manifest_key": production_key,
        "manifest_sha256": production_sha,
        "production_authority": True,
    }
    objects = {
        candidate_key: candidate_bytes,
        production_key: production_bytes,
        PRODUCTION_POINTER_KEY: _json_bytes(pointer),
    }
    return FakeStore(objects), {
        "release_id": release_id,
        "candidate_key": candidate_key,
        "production_key": production_key,
    }


def _replace_json(store: FakeStore, key: str, mutate) -> None:
    value = json.loads(store.objects[key])
    mutate(value)
    store.objects[key] = _json_bytes(value)


def _rebind_candidate(store: FakeStore, expected: dict[str, str]) -> None:
    candidate_sha = sha256_bytes(store.objects[expected["candidate_key"]])
    production = json.loads(store.objects[expected["production_key"]])
    production["production_promotion"]["source_candidate_manifest_sha256"] = candidate_sha
    production_bytes = _json_bytes(production)
    store.objects[expected["production_key"]] = production_bytes
    pointer = json.loads(store.objects[PRODUCTION_POINTER_KEY])
    pointer["manifest_sha256"] = sha256_bytes(production_bytes)
    store.objects[PRODUCTION_POINTER_KEY] = _json_bytes(pointer)


def _rebind_production(store: FakeStore, expected: dict[str, str]) -> None:
    pointer = json.loads(store.objects[PRODUCTION_POINTER_KEY])
    pointer["manifest_sha256"] = sha256_bytes(store.objects[expected["production_key"]])
    store.objects[PRODUCTION_POINTER_KEY] = _json_bytes(pointer)


def test_resolves_successor_from_pointer_chain() -> None:
    store, expected = _fixture()

    active = resolve_active_production_release(store)

    assert active.release_id == expected["release_id"]
    assert active.production_manifest_key == expected["production_key"]
    assert active.candidate_manifest_key == expected["candidate_key"]
    assert active.qdrant_collection == QDRANT_COLLECTION
    assert active.source_commit_sha == SOURCE_SHA
    assert active.admission_sha256 == ADMISSION_SHA
    assert active.semantic_point_count == 4424


def test_missing_pointer_fails_closed_without_legacy_fallback() -> None:
    store, _ = _fixture()
    del store.objects[PRODUCTION_POINTER_KEY]

    with pytest.raises(ActiveProductionReleaseError, match="production pointer missing"):
        resolve_active_production_release(store)


def test_tampered_pointer_authority_fails_closed() -> None:
    store, _ = _fixture()
    _replace_json(
        store,
        PRODUCTION_POINTER_KEY,
        lambda pointer: pointer.__setitem__("production_authority", False),
    )

    with pytest.raises(ActiveProductionReleaseError, match="pointer authority"):
        resolve_active_production_release(store)


def test_pointer_manifest_digest_mismatch_fails_closed() -> None:
    store, expected = _fixture()
    _replace_json(
        store,
        expected["production_key"],
        lambda manifest: manifest.__setitem__("extra", "tampered"),
    )

    with pytest.raises(ActiveProductionReleaseError, match="production manifest digest"):
        resolve_active_production_release(store)


def test_pointer_release_mismatch_fails_closed() -> None:
    store, _ = _fixture()
    _replace_json(
        store,
        PRODUCTION_POINTER_KEY,
        lambda pointer: pointer.__setitem__("release_id", "other-release"),
    )

    with pytest.raises(ActiveProductionReleaseError, match="escapes release namespace"):
        resolve_active_production_release(store)


def test_production_manifest_must_be_in_promotion_namespace() -> None:
    store, expected = _fixture()
    production_bytes = store.objects.pop(expected["production_key"])
    bad_key = f"releases/{expected['release_id']}/production-manifest.json"
    store.objects[bad_key] = production_bytes
    pointer = json.loads(store.objects[PRODUCTION_POINTER_KEY])
    pointer["manifest_key"] = bad_key
    store.objects[PRODUCTION_POINTER_KEY] = _json_bytes(pointer)

    with pytest.raises(ActiveProductionReleaseError, match="promotion namespace"):
        resolve_active_production_release(store)


def test_candidate_manifest_digest_mismatch_fails_closed() -> None:
    store, expected = _fixture()
    _replace_json(
        store,
        expected["candidate_key"],
        lambda manifest: manifest.__setitem__("extra", "tampered"),
    )

    with pytest.raises(ActiveProductionReleaseError, match="candidate manifest digest"):
        resolve_active_production_release(store)


def test_candidate_manifest_path_escape_fails_closed() -> None:
    store, expected = _fixture()
    production = json.loads(store.objects[expected["production_key"]])
    production["production_promotion"]["source_candidate_manifest_key"] = (
        f"releases/{expected['release_id']}/../other/manifest.json"
    )
    production_bytes = _json_bytes(production)
    store.objects[expected["production_key"]] = production_bytes
    _rebind_production(store, expected)

    with pytest.raises(ActiveProductionReleaseError, match="key is not canonical"):
        resolve_active_production_release(store)


def test_candidate_manifest_noncanonical_same_release_path_fails_closed() -> None:
    store, expected = _fixture()
    candidate_bytes = store.objects[expected["candidate_key"]]
    alternate_key = f"releases/{expected['release_id']}/candidate/manifest.json"
    store.objects[alternate_key] = candidate_bytes
    production = json.loads(store.objects[expected["production_key"]])
    production["production_promotion"]["source_candidate_manifest_key"] = alternate_key
    production_bytes = _json_bytes(production)
    store.objects[expected["production_key"]] = production_bytes
    _rebind_production(store, expected)

    with pytest.raises(ActiveProductionReleaseError, match="path is not canonical"):
        resolve_active_production_release(store)


def test_artifact_path_escape_fails_closed() -> None:
    store, expected = _fixture()
    candidate = json.loads(store.objects[expected["candidate_key"]])
    candidate["artifacts"][0]["key"] = "releases/elsewhere/artifact.json"
    store.objects[expected["candidate_key"]] = _json_bytes(candidate)

    production = json.loads(store.objects[expected["production_key"]])
    production["artifacts"][0]["key"] = "releases/elsewhere/artifact.json"
    store.objects[expected["production_key"]] = _json_bytes(production)
    _rebind_candidate(store, expected)

    with pytest.raises(ActiveProductionReleaseError, match="escapes release namespace"):
        resolve_active_production_release(store)


def test_production_candidate_artifact_drift_fails_closed() -> None:
    store, expected = _fixture()
    production = json.loads(store.objects[expected["production_key"]])
    production["artifacts"][0]["sha256"] = "3" * 64
    store.objects[expected["production_key"]] = _json_bytes(production)
    _rebind_production(store, expected)

    with pytest.raises(ActiveProductionReleaseError, match="artifact mismatch"):
        resolve_active_production_release(store)


def test_missing_runtime_artifact_fails_closed() -> None:
    store, expected = _fixture()
    candidate = json.loads(store.objects[expected["candidate_key"]])
    candidate["artifacts"] = [
        entry for entry in candidate["artifacts"] if entry["kind"] != "graph_v2"
    ]
    store.objects[expected["candidate_key"]] = _json_bytes(candidate)

    production = json.loads(store.objects[expected["production_key"]])
    production["artifacts"] = [
        entry for entry in production["artifacts"] if entry["kind"] != "graph_v2"
    ]
    store.objects[expected["production_key"]] = _json_bytes(production)
    _rebind_candidate(store, expected)

    with pytest.raises(ActiveProductionReleaseError, match="required runtime artifacts missing"):
        resolve_active_production_release(store)


def test_invalid_source_git_sha_fails_closed() -> None:
    store, expected = _fixture()
    candidate = json.loads(store.objects[expected["candidate_key"]])
    candidate["identities"]["source_commit_sha"] = "not-a-git-sha"
    store.objects[expected["candidate_key"]] = _json_bytes(candidate)

    production = json.loads(store.objects[expected["production_key"]])
    production["identities"]["source_commit_sha"] = "not-a-git-sha"
    store.objects[expected["production_key"]] = _json_bytes(production)
    _rebind_candidate(store, expected)

    with pytest.raises(ActiveProductionReleaseError, match="lowercase git sha"):
        resolve_active_production_release(store)


def test_zero_semantic_point_count_fails_closed() -> None:
    store, expected = _fixture()
    candidate = json.loads(store.objects[expected["candidate_key"]])
    candidate["counts"]["semantic_documents"] = 0
    store.objects[expected["candidate_key"]] = _json_bytes(candidate)

    production = json.loads(store.objects[expected["production_key"]])
    production["counts"]["semantic_documents"] = 0
    store.objects[expected["production_key"]] = _json_bytes(production)
    _rebind_candidate(store, expected)

    with pytest.raises(ActiveProductionReleaseError, match="positive integer"):
        resolve_active_production_release(store)
