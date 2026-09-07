from __future__ import annotations

import copy
import json
from dataclasses import dataclass

import pytest

from knowledge_engine.m26_active_production_release import (
    PRODUCTION_POINTER_KEY,
    ActiveProductionReleaseError,
    resolve_active_production_release,
)
from knowledge_engine.storage import sha256_bytes


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


def _fixture(*, release_id: str = "successor-release") -> tuple[FakeStore, dict[str, str]]:
    candidate_key = f"releases/{release_id}/manifest.json"
    production_key = f"releases/{release_id}/promotion/production-manifest.json"
    artifact_key = f"releases/{release_id}/artifacts/lexical.json"
    artifact_digest = "1" * 64
    candidate = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": release_id,
        "status": "candidate",
        "authority": {
            "production_pointer_authorized": False,
        },
        "identities": {
            "source_commit_sha": "source-sha",
            "admission_sha256": "2" * 64,
        },
        "counts": {"semantic_documents": 4424},
        "artifacts": [
            {
                "kind": "lexical_index",
                "key": artifact_key,
                "sha256": artifact_digest,
                "bytes": 123,
            }
        ],
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
        "qdrant_candidate_collection": "qdrant-successor",
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
        "artifact_key": artifact_key,
    }


def _replace_json(store: FakeStore, key: str, mutate) -> None:
    value = json.loads(store.objects[key])
    mutate(value)
    store.objects[key] = _json_bytes(value)


def test_resolves_successor_from_pointer_chain() -> None:
    store, expected = _fixture()

    active = resolve_active_production_release(store)

    assert active.release_id == expected["release_id"]
    assert active.production_manifest_key == expected["production_key"]
    assert active.candidate_manifest_key == expected["candidate_key"]
    assert active.qdrant_collection == "qdrant-successor"
    assert active.source_commit_sha == "source-sha"
    assert active.admission_sha256 == "2" * 64
    assert active.semantic_point_count == 4424


def test_missing_pointer_fails_closed() -> None:
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
    pointer = json.loads(store.objects[PRODUCTION_POINTER_KEY])
    pointer["manifest_sha256"] = sha256_bytes(production_bytes)
    store.objects[PRODUCTION_POINTER_KEY] = _json_bytes(pointer)

    with pytest.raises(ActiveProductionReleaseError, match="key is not canonical"):
        resolve_active_production_release(store)


def test_artifact_path_escape_fails_closed() -> None:
    store, expected = _fixture()
    candidate = json.loads(store.objects[expected["candidate_key"]])
    candidate["artifacts"][0]["key"] = "releases/elsewhere/artifact.json"
    candidate_bytes = _json_bytes(candidate)
    candidate_sha = sha256_bytes(candidate_bytes)
    store.objects[expected["candidate_key"]] = candidate_bytes

    production = json.loads(store.objects[expected["production_key"]])
    production["artifacts"][0]["key"] = "releases/elsewhere/artifact.json"
    production["production_promotion"]["source_candidate_manifest_sha256"] = candidate_sha
    production_bytes = _json_bytes(production)
    store.objects[expected["production_key"]] = production_bytes

    pointer = json.loads(store.objects[PRODUCTION_POINTER_KEY])
    pointer["manifest_sha256"] = sha256_bytes(production_bytes)
    store.objects[PRODUCTION_POINTER_KEY] = _json_bytes(pointer)

    with pytest.raises(ActiveProductionReleaseError, match="escapes release namespace"):
        resolve_active_production_release(store)


def test_production_candidate_artifact_drift_fails_closed() -> None:
    store, expected = _fixture()
    production = json.loads(store.objects[expected["production_key"]])
    production["artifacts"][0]["sha256"] = "3" * 64
    production_bytes = _json_bytes(production)
    store.objects[expected["production_key"]] = production_bytes
    pointer = json.loads(store.objects[PRODUCTION_POINTER_KEY])
    pointer["manifest_sha256"] = sha256_bytes(production_bytes)
    store.objects[PRODUCTION_POINTER_KEY] = _json_bytes(pointer)

    with pytest.raises(ActiveProductionReleaseError, match="artifact mismatch"):
        resolve_active_production_release(store)
