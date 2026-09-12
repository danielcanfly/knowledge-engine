from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import knowledge_engine.m26_admin_corpus as admin_corpus
from knowledge_engine.m26_admin_contract import AdminActor
from knowledge_engine.m26_admin_control_plane import install_admin_control_plane
from knowledge_engine.m26_admin_ingestion import install_admin_ingestion_routes
from knowledge_engine.m26_ingestion_runtime import build_runtime_ingestion_adapter_from_env
from knowledge_engine.m26_sqlite_ingestion import (
    SQLiteIngestionLedger,
    SQLiteIngestionReadAuthority,
    active_manifest_observer_from_store,
)
from knowledge_engine.storage import FileObjectStore, sha256_bytes

RELEASE_ID = "c2-dynamic-release"
SOURCE_SHA = "1" * 40
ADMISSION_SHA = "2" * 64


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _put(store: FileObjectStore, key: str, value: object) -> dict[str, Any]:
    data = _json_bytes(value)
    store.put(key, data, content_type="application/json", only_if_absent=True)
    return {
        "key": key,
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "media_type": "application/json",
        "required": True,
    }


def _active_store(root: Path) -> FileObjectStore:
    store = FileObjectStore(root)
    concept = {"concept_id": "concepts/c2", "title": "C2", "type": "Concept"}
    artifacts = {
        "graph": {
            "schema_version": "knowledge-engine-document-graph/v1",
            "release_id": RELEASE_ID,
            "nodes": [concept],
            "edges": [],
        },
        "graph_v2": {
            "schema_version": "knowledge-engine-graph-v2/v1",
            "release": {"release_id": RELEASE_ID},
            "nodes": [concept],
            "edges": [],
        },
        "lexical_index": {
            "schema_version": "knowledge-engine-lexical-index/v2",
            "release_id": RELEASE_ID,
            "documents": [
                {
                    "concept_id": "concepts/c2",
                    "section_id": "concepts/c2#overview",
                    "source_id": "doc-c2",
                    "title": "C2",
                    "body": "dynamic active release evidence",
                    "content_sha256": "3" * 64,
                }
            ],
        },
        "provenance": {
            "schema_version": "knowledge-engine-document-provenance/v1",
            "release_id": RELEASE_ID,
            "records": [
                {
                    "subject": {"concept_id": "concepts/c2"},
                    "sources": [
                        {
                            "source_id": "doc-c2",
                            "uri": "https://example.test/c2",
                            "retrieved_at": "2026-09-12T00:00:00Z",
                        }
                    ],
                }
            ],
        },
        "semantic_inputs": {
            "schema_version": "knowledge-engine-semantic-inputs/v1",
            "release_id": RELEASE_ID,
            "documents": [
                {
                    "section_id": "concepts/c2#overview",
                    "source_id": "doc-c2",
                    "text": "dynamic active release evidence",
                }
            ],
        },
        "source_documents": {
            "schema_version": "knowledge-engine-source-documents/v1",
            "release_id": RELEASE_ID,
            "documents": [
                {
                    "document_id": "doc-c2",
                    "source_id": "doc-c2",
                    "origin_path": "src/content/blog/c2/en.md",
                    "canonical_url": "https://example.test/c2",
                    "language": "en",
                    "content_sha256": "3" * 64,
                }
            ],
        },
        "document_source_index": {
            "schema_version": "knowledge-engine-document-source-index/v1",
            "release_id": RELEASE_ID,
            "entries": [
                {
                    "document_id": "doc-c2",
                    "source_id": "doc-c2",
                    "origin_path": "src/content/blog/c2/en.md",
                    "content_sha256": "3" * 64,
                }
            ],
        },
    }
    artifact_entries = []
    for kind, payload in artifacts.items():
        key = f"releases/{RELEASE_ID}/artifacts/{kind.replace('_', '-')}.json"
        artifact_entries.append({"kind": kind, **_put(store, key, payload)})

    candidate_key = f"releases/{RELEASE_ID}/manifest.json"
    candidate = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": RELEASE_ID,
        "status": "candidate",
        "authority": {"production_pointer_authorized": False},
        "identities": {
            "source_commit_sha": SOURCE_SHA,
            "admission_sha256": ADMISSION_SHA,
        },
        "counts": {
            "document_graph_nodes": 1,
            "document_graph_edges": 0,
            "semantic_documents": 1,
        },
        "artifacts": artifact_entries,
    }
    candidate_entry = _put(store, candidate_key, candidate)

    production_key = f"releases/{RELEASE_ID}/promotion/production-manifest.json"
    production = copy.deepcopy(candidate)
    production["status"] = "production"
    production["authority"]["production_pointer_authorized"] = True
    production["production_promotion"] = {
        "production_pointer_authorized": True,
        "source_candidate_manifest_key": candidate_key,
        "source_candidate_manifest_sha256": candidate_entry["sha256"],
        "qdrant_candidate_collection": "c2-dynamic-collection",
    }
    production_entry = _put(store, production_key, production)
    _put(
        store,
        "channels/production.json",
        {
            "schema_version": "1.0",
            "channel": "production",
            "release_id": RELEASE_ID,
            "manifest_key": production_key,
            "manifest_sha256": production_entry["sha256"],
            "production_authority": True,
        },
    )
    return store


class _Authenticator:
    def authenticate(self, _assertion: str | None) -> AdminActor:
        return AdminActor("owner", "owner", None, "human", "issuer", ("aud",))


def _source_observation() -> dict[str, Any]:
    return {
        "source_revision": "git:" + SOURCE_SHA,
        "source_identity_digest": ADMISSION_SHA,
        "documents": [{"document_id": "doc-c2", "digest": "3" * 64}],
    }


def test_index_health_keeps_authoritative_read_evidence_out_of_admin_http_error(
    tmp_path: Path,
) -> None:
    store = _active_store(tmp_path / "objects")
    adapter = SQLiteIngestionReadAuthority(
        SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3"),
        ["candidate_executor"],
        source_observer=_source_observation,
        active_manifest_observer=active_manifest_observer_from_store(store),
    )
    app = FastAPI()
    install_admin_control_plane(app, authenticator=_Authenticator())
    install_admin_ingestion_routes(app, adapter=adapter)

    response = TestClient(app).get(
        "/v1/admin/index/health",
        headers={
            "origin": "https://console.danielcanfly.com",
            "cf-access-jwt-assertion": "owner",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("error", {}).get("code") != "ADMIN_HTTP_ERROR"
    assert payload["data"]["active_production_index"]["release_id"] == RELEASE_ID
    assert payload["data"]["active_production_index"]["status"] == "healthy"


def test_mutation_disabled_runtime_still_composes_valid_read_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _active_store(tmp_path / "objects")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "filesystem")
    monkeypatch.setenv("FILESYSTEM_STORE_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("M26_INGESTION_STATE_DB", str(tmp_path / "ingestion.sqlite3"))
    monkeypatch.setenv("M26_INGESTION_ENABLED", "false")

    adapter = build_runtime_ingestion_adapter_from_env()

    assert isinstance(adapter, SQLiteIngestionReadAuthority)
    assert not hasattr(adapter, "sync_blog")
    observation = adapter.current_index()
    assert observation.reason_code != "ADMIN_INGESTION_ADAPTER_UNQUALIFIED"
    assert observation.data["active"]["release_id"] == RELEASE_ID


def test_p09_versions_uses_valid_active_immutable_release(tmp_path: Path) -> None:
    store = _active_store(tmp_path / "objects")
    adapter = SQLiteIngestionReadAuthority(
        SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3"),
        ["candidate_executor"],
        active_manifest_observer=active_manifest_observer_from_store(store),
    )

    observation = adapter.as_p09_provider().list_versions()

    assert observation.reason_code != "P09_AUTHORITATIVE_EVIDENCE_SOURCE_UNAVAILABLE"
    assert observation.availability_status == "available"
    assert observation.data["versions"][0]["version_id"] == RELEASE_ID
    assert observation.data["versions"][0]["active"] is True
    assert observation.data["versions"][0]["eligibility"] == "unknown"


def test_corpus_uses_valid_canonical_active_store_without_writes(tmp_path: Path) -> None:
    store = _active_store(tmp_path / "objects")
    before = sorted(
        path.relative_to(store.root) for path in store.root.rglob("*") if path.is_file()
    )
    adapter_type = getattr(admin_corpus, "ObjectStoreCorpusAdapter", None)

    assert adapter_type is not None
    snapshot = adapter_type(store).read()
    rows = admin_corpus.reconcile_corpus(snapshot)
    after = sorted(path.relative_to(store.root) for path in store.root.rglob("*") if path.is_file())

    assert snapshot["active_release_marker"] == RELEASE_ID
    assert rows[0]["source_id"] == "doc-c2"
    assert rows[0]["vector_presence"] is True
    assert rows[0]["reasons"] == []
    assert before == after


def test_console_composes_all_read_authorities_while_mutation_stays_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _active_store(tmp_path / "objects")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "filesystem")
    monkeypatch.setenv("FILESYSTEM_STORE_ROOT", str(tmp_path / "objects"))
    monkeypatch.delenv("M26_INGESTION_STATE_DB", raising=False)
    monkeypatch.setenv("M26_ADMIN_CONTROL_DB_PATH", str(tmp_path / "admin-control.sqlite3"))
    monkeypatch.setenv("M26_INGESTION_ENABLED", "false")
    monkeypatch.setenv("M26_L3B_ADMIN_QUALIFIED", "false")

    import knowledge_engine.m26_console_api as console_api

    app = importlib.reload(console_api).app
    ingestion = app.state.m26_durable_ingestion_adapter
    versions = app.state.m26_jobs_rollback_evidence_provider.list_versions()

    assert isinstance(ingestion, SQLiteIngestionReadAuthority)
    assert not hasattr(ingestion, "sync_blog")
    assert versions.data["versions"][0]["version_id"] == RELEASE_ID
    assert isinstance(app.state.admin_corpus_service.adapter, admin_corpus.ObjectStoreCorpusAdapter)
