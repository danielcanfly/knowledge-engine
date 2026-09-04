from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_contract import AdminAPIError
from knowledge_engine.m26_admin_corpus import (
    CORPUS_SOURCE,
    CorpusReadService,
    install_admin_corpus,
    reconcile_corpus,
)


def snapshot(
    *,
    sources: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    vectors: list[dict[str, Any]] | None = None,
    active: str = "release-2",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "sources": sources or [],
        "artifacts": artifacts or [],
        "vectors": vectors or [],
        "active_release_marker": active,
        "warnings": warnings or [],
    }


def healthy_snapshot(*, source_id: str = "s1", language: str | None = None):
    source: dict[str, Any] = {
        "source_id": source_id,
        "source_path": f"posts/{source_id}.md",
        "canonical_url": f"https://example/{source_id}",
    }
    if language:
        source["language"] = language
    return snapshot(
        sources=[source],
        artifacts=[
            {
                "source_id": source_id,
                "artifact_markdown": f"{source_id}.md",
                "embedding_text": f"{source_id}.txt",
                "manifest_record": f"m:{source_id}",
                "release_marker": "release-2",
            }
        ],
        vectors=[
            {
                "source_id": source_id,
                "vector_presence": True,
                "release_marker": "release-2",
            }
        ],
    )


def test_corpus_happy_path_preserves_source_and_active_release_identity():
    rows = reconcile_corpus(
        snapshot(
            sources=[
                {
                    "source_id": "s1",
                    "source_path": "posts/a.md",
                    "canonical_url": "https://example/a",
                    "source_revision": "r2",
                }
            ],
            artifacts=[
                {
                    "source_id": "s1",
                    "artifact_markdown": "r2/a.md",
                    "embedding_text": "r2/a.txt",
                    "manifest_record": "m:s1",
                    "release_marker": "release-2",
                    "source_revision": "r2",
                    "materialized_at": "2026-09-04T00:00:00Z",
                }
            ],
            vectors=[
                {
                    "source_id": "s1",
                    "vector_presence": True,
                    "vector_backend": "qdrant",
                    "release_marker": "release-2",
                    "indexed_at": "2026-09-04T00:01:00Z",
                }
            ],
        )
    )

    assert rows[0]["source_id"] == "s1"
    assert rows[0]["missing"] == []
    assert rows[0]["reasons"] == []
    assert rows[0]["active_release_marker"] == "release-2"


def test_missing_semantic_payload_is_materialize_failure_not_vector_success():
    row = reconcile_corpus(
        snapshot(
            sources=[{"source_id": "s1", "source_path": "posts/a.md"}],
            artifacts=[
                {
                    "source_id": "s1",
                    "artifact_markdown": "a.md",
                    "manifest_record": "m:s1",
                    "release_marker": "release-2",
                }
            ],
            vectors=[
                {
                    "source_id": "s1",
                    "vector_presence": True,
                    "release_marker": "release-2",
                }
            ],
        )
    )[0]

    assert "embedding_text" in row["missing"]
    assert "CORPUS_MATERIALIZE_SEMANTIC_PAYLOAD_MISSING" in row["reasons"]
    assert row["vector_presence"] is True


def test_release_mismatch_is_stale_and_explainable():
    row = reconcile_corpus(
        snapshot(
            sources=[{"source_id": "s1", "source_path": "posts/a.md"}],
            artifacts=[
                {
                    "source_id": "s1",
                    "artifact_markdown": "a.md",
                    "embedding_text": "a.txt",
                    "manifest_record": "m:s1",
                    "release_marker": "release-1",
                }
            ],
            vectors=[
                {
                    "source_id": "s1",
                    "vector_presence": True,
                    "release_marker": "release-1",
                }
            ],
        )
    )[0]

    assert row["stale"] is True
    assert "CORPUS_ACTIVE_RELEASE_MISMATCH" in row["reasons"]


def test_deleted_source_leaves_explicit_orphan_identity():
    row = reconcile_corpus(
        snapshot(
            artifacts=[
                {
                    "source_id": "deleted",
                    "source_path": "posts/deleted.md",
                    "artifact_markdown": "deleted.md",
                    "embedding_text": "deleted.txt",
                    "manifest_record": "m:deleted",
                }
            ],
            vectors=[{"source_id": "deleted", "vector_presence": True}],
        )
    )[0]

    assert "source" in row["missing"]
    assert "CORPUS_ORPHANED_ARTIFACT" in row["reasons"]


def test_duplicate_slug_is_visible_for_both_source_rows():
    rows = reconcile_corpus(
        snapshot(
            sources=[
                {"source_id": "old", "source_path": "posts/a.md"},
                {"source_id": "new", "source_path": "drafts/a.md"},
            ]
        )
    )

    assert all("CORPUS_DUPLICATE_SLUG" in row["reasons"] for row in rows)


def test_rename_does_not_silently_collapse_old_artifact_into_new_source():
    rows = reconcile_corpus(
        snapshot(
            sources=[
                {
                    "source_id": "new",
                    "source_path": "posts/new-name.md",
                }
            ],
            artifacts=[
                {
                    "source_id": "old",
                    "source_path": "posts/old-name.md",
                    "artifact_markdown": "old.md",
                    "embedding_text": "old.txt",
                    "manifest_record": "m:old",
                }
            ],
        )
    )

    assert {row["source_id"] for row in rows} == {"new", "old"}
    old_row = next(row for row in rows if row["source_id"] == "old")
    assert "CORPUS_ORPHANED_ARTIFACT" in old_row["reasons"]


class BoomAdapter:
    def read(self) -> Mapping[str, Any]:
        raise RuntimeError("r2 down")


class MalformedAdapter:
    def read(self) -> Any:
        return []


class FixtureAdapter:
    def __init__(self, value: Mapping[str, Any]) -> None:
        self.value = value

    def read(self) -> Mapping[str, Any]:
        return self.value


def test_adapter_failure_is_unavailable_not_empty_success():
    with pytest.raises(AdminAPIError) as exc:
        CorpusReadService(BoomAdapter()).read()

    assert exc.value.status_code == 503
    assert exc.value.code == "ADMIN_CORPUS_ADAPTER_FAILURE"


def test_malformed_adapter_is_unavailable_not_empty_success():
    with pytest.raises(AdminAPIError) as exc:
        CorpusReadService(MalformedAdapter()).read()

    assert exc.value.status_code == 503
    assert exc.value.code == "ADMIN_CORPUS_ADAPTER_MALFORMED"


def test_route_returns_repair_a_envelope_with_nullable_observation():
    value = snapshot(
        sources=[{"source_id": "s1", "source_path": "posts/a.md"}],
    )
    value["freshness"] = "snapshot"

    app = FastAPI()
    install_admin_corpus(app, adapter=FixtureAdapter(value))
    response = TestClient(app).get("/v1/admin/corpus")

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"].startswith("admreq_")
    assert payload["availability"]["status"] == "partial"
    assert payload["availability"]["reason_code"] == "CORPUS_PARTIAL_EVIDENCE"
    assert payload["provenance"]["source"] == CORPUS_SOURCE
    assert payload["provenance"]["resource_identity"] == {
        "contract_version": "1.1.0-gate-a-repair-a"
    }
    assert payload["observed_at"] is None
    assert payload["freshness"] == "snapshot"
    assert payload["data"][0]["source_id"] == "s1"


def test_route_available_happy_path_has_no_fabricated_observed_at():
    app = FastAPI()
    install_admin_corpus(app, adapter=FixtureAdapter(healthy_snapshot()))
    payload = TestClient(app).get("/v1/admin/corpus").json()

    assert payload["availability"] == {
        "status": "available",
        "reason_code": None,
        "detail": None,
    }
    assert payload["observed_at"] is None


def test_list_route_exposes_only_canonical_query_parameters():
    app = FastAPI()
    install_admin_corpus(app, adapter=FixtureAdapter(healthy_snapshot()))
    operation = app.openapi()["paths"]["/v1/admin/corpus"]["get"]
    parameters = {
        item["name"]: item for item in operation["parameters"] if item["in"] == "query"
    }

    assert set(parameters) == {"q", "state", "language"}
    assert parameters["q"]["schema"]["maxLength"] == 200
    assert operation["operationId"] == "listCorpus"


def test_list_route_applies_q_filter_to_source_identity_fields():
    value = snapshot(
        sources=[
            {"source_id": "alpha", "source_path": "posts/alpha.md"},
            {"source_id": "beta", "source_path": "posts/beta.md"},
        ]
    )
    app = FastAPI()
    install_admin_corpus(app, adapter=FixtureAdapter(value))

    payload = TestClient(app).get("/v1/admin/corpus?q=alpha").json()

    assert [row["source_id"] for row in payload["data"]] == ["alpha"]


def test_list_route_state_filter_uses_observed_reconciliation_state():
    value = healthy_snapshot(source_id="fresh")
    value["sources"].append({"source_id": "stale", "source_path": "posts/stale.md"})
    value["artifacts"].append(
        {
            "source_id": "stale",
            "artifact_markdown": "stale.md",
            "embedding_text": "stale.txt",
            "manifest_record": "m:stale",
            "release_marker": "release-1",
        }
    )
    value["vectors"].append(
        {
            "source_id": "stale",
            "vector_presence": True,
            "release_marker": "release-1",
        }
    )
    app = FastAPI()
    install_admin_corpus(app, adapter=FixtureAdapter(value))

    payload = TestClient(app).get("/v1/admin/corpus?state=stale").json()

    assert [row["source_id"] for row in payload["data"]] == ["stale"]


def test_list_route_language_filter_requires_observed_language_evidence():
    value = healthy_snapshot(source_id="english", language="en")
    other = healthy_snapshot(source_id="unknown")
    value["sources"].extend(other["sources"])
    value["artifacts"].extend(other["artifacts"])
    value["vectors"].extend(other["vectors"])
    app = FastAPI()
    install_admin_corpus(app, adapter=FixtureAdapter(value))

    payload = TestClient(app).get("/v1/admin/corpus?language=en").json()

    assert [row["source_id"] for row in payload["data"]] == ["english"]
    assert payload["data"][0]["language"] == "en"


def test_list_route_rejects_q_longer_than_canonical_maximum():
    app = FastAPI()
    install_admin_corpus(app, adapter=FixtureAdapter(healthy_snapshot()))

    response = TestClient(app).get(f"/v1/admin/corpus?q={'x' * 201}")

    assert response.status_code == 422


def test_detail_route_materializes_canonical_document_read():
    app = FastAPI()
    install_admin_corpus(
        app,
        adapter=FixtureAdapter(healthy_snapshot(source_id="document-1", language="en")),
    )
    operation = app.openapi()["paths"]["/v1/admin/corpus/{document_id}"]["get"]

    response = TestClient(app).get("/v1/admin/corpus/document-1")

    assert operation["operationId"] == "getCorpusDocument"
    assert response.status_code == 200
    assert response.json()["availability"]["status"] == "available"
    assert response.json()["data"]["source_id"] == "document-1"


def test_detail_route_missing_document_is_explicit_unavailable_not_fake_empty():
    app = FastAPI()
    install_admin_corpus(app, adapter=FixtureAdapter(healthy_snapshot()))

    payload = TestClient(app).get("/v1/admin/corpus/missing").json()

    assert payload["availability"]["status"] == "unavailable"
    assert payload["availability"]["reason_code"] == "CORPUS_DOCUMENT_NOT_OBSERVED"
    assert payload["data"] is None
