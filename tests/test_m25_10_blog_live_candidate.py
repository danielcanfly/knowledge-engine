from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from knowledge_engine import m25_blog_live_candidate as subject
from knowledge_engine.errors import IntegrityError


def test_live_authority_is_exact_and_production_denied() -> None:
    path = Path("pilot/m25/m25-10-live-candidate-authority.json")
    value = json.loads(path.read_text())
    claimed = value.pop("self_sha256")
    actual = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert claimed == actual
    assert claimed == "a263f37de3728b7ef6112a4b32e2ff246fe7e2c304f84d8316be1c35796c1ef3"
    assert all(item is True for item in value["candidate_authority"].values())
    assert all(item is False for item in value["denied_authority"].values())


def test_admission_reproduces_merged_source_authority() -> None:
    value = subject._admission()
    assert value["admission_sha256"] == subject.ADMISSION_SHA
    assert value["source_write_authorized"] is True
    assert value["candidate_release_authorized"] is True
    assert value["production_pointer_authorized"] is False
    assert value["public_production_traffic_authorized"] is False


def test_vector_fingerprint_is_deterministic() -> None:
    vector = [0.0] * subject.VECTOR_DIMENSION
    vector[0] = 1.0
    point = {
        "id": "example",
        "vector": {subject.QDRANT_VECTOR_NAME: vector},
        "payload": {
            "release_id": "candidate",
            "production_authority": False,
        },
    }
    assert subject._point_fingerprint(point) == subject._point_fingerprint(point)
    assert len(subject._point_fingerprint(point)) == 64


def test_vector_fingerprint_rejects_wrong_dimension() -> None:
    with pytest.raises(IntegrityError, match="dimension"):
        subject._f32_sha([0.0])


def test_prepare_requires_candidate_channel(tmp_path: Path) -> None:
    with pytest.raises(IntegrityError, match="candidate channel"):
        subject.prepare(
            work_dir=tmp_path,
            engine_sha="a" * 40,
            channel="production",
            live=False,
        )


def test_semantic_population_contract() -> None:
    assert subject.COUNTS["semantic_documents"] == 4197
    assert subject.COUNTS["sources"] == 156
    assert subject.COUNTS["nodes"] == 4222
    assert subject.COUNTS["edges"] == 8525
