from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

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


class _Response:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.value


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
    ) -> _Response:
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "json": json}
        )
        return _Response({"status": "ok", "result": {"points": [{"payload": {}}]}})


def test_qdrant_payload_indexes_cover_runtime_authority_filter() -> None:
    client = _Client()
    qdrant = subject.QdrantConfig(
        base_url="https://qdrant.example",
        api_key="secret",
        collection_name="collection",
    )
    created = subject._create_qdrant_payload_indexes(client, qdrant, "collection")
    assert created == [
        {"field_name": "release_id", "field_schema": "keyword"},
        {"field_name": "source_commit_sha", "field_schema": "keyword"},
        {"field_name": "admission_sha256", "field_schema": "keyword"},
        {"field_name": "candidate_release_eligible", "field_schema": "bool"},
        {"field_name": "production_authority", "field_schema": "bool"},
    ]
    assert all(call["method"] == "PUT" for call in client.calls)
    assert all(
        call["url"].endswith("/collections/collection/index?wait=true")
        for call in client.calls
    )
    assert {call["json"]["field_name"] for call in client.calls} == {
        condition["key"]
        for condition in subject._qdrant_authority_filter("release")["must"]
    }


def test_qdrant_query_body_matches_runtime_authority_boundary() -> None:
    vector = [0.0] * subject.VECTOR_DIMENSION
    body = subject._qdrant_query_body(vector, "release", limit=3)
    assert body["query"] == vector
    assert body["using"] == subject.QDRANT_VECTOR_NAME
    assert body["limit"] == 3
    assert body["with_payload"] is True
    assert body["with_vector"] is False
    assert body["filter"] == subject._qdrant_authority_filter("release")


def test_qdrant_collection_name_is_engine_scoped() -> None:
    assert subject._qdrant_collection_name(
        "m25blog-5250f8422f4f-f5f01d82c7a1",
        "6ab3b6baa9bac48cf8a25fe95fd282c5b895c2fa",
    ) == "m25_blog_m25blog_5250f8422f4f_f5f01d82c7a1_6ab3b6baa9ba"
    with pytest.raises(IntegrityError, match="engine SHA"):
        subject._qdrant_collection_name("release", "not-a-sha")


def test_candidate_release_id_is_engine_scoped_for_immutable_r2_namespace() -> None:
    assert subject._candidate_release_id(
        "d9787ebb1400b1e908292642ae33138938ccac97"
    ) == "m25blog-5250f8422f4f-f5f01d82c7a1-d9787ebb1400"
    with pytest.raises(IntegrityError, match="engine SHA"):
        subject._candidate_release_id("not-a-sha")


def test_m25_obsidian_vault_zip_manifest_is_downloadable_candidate(
    tmp_path: Path,
) -> None:
    context = {
        "pack": {
            "article_by_id": {
                "source_alpha": {
                    "title": "Alpha Article",
                    "series_id": "series_one",
                    "series_title": "Series One",
                }
            },
            "source_bytes": {"source_alpha": b"## Alpha\n\nFull source body.\n"},
        }
    }
    manifest = subject._build_obsidian_vault_zip(tmp_path, "release", context)
    zip_path = tmp_path / manifest["vault_zip_path"]
    assert manifest["status"] == "candidate_vault_zip_ready"
    assert manifest["download_href"] == subject.OBSIDIAN_VAULT_ZIP_RELATIVE
    assert manifest["source_note_count"] == 1
    assert manifest["concept_note_count"] == 1
    assert manifest["write_back_authorized"] is False
    assert manifest["production_authority"] is False
    assert zip_path.is_file()
    assert manifest["vault_zip_sha256"] == subject.sha256_bytes(zip_path.read_bytes())
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        assert ".obsidian/app.json" in names
        assert "README.md" in names
        assert any(name.startswith("Sources/source_alpha") for name in names)
        assert any(name.startswith("Series/series_one") for name in names)
