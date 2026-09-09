from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_contract import (
    AdminActor,
    AdminAPIError,
    IdempotencyCoordinator,
    StatefulIdempotencyLease,
)
from knowledge_engine.m26_admin_control_plane import install_admin_control_plane
from knowledge_engine.m26_admin_ingestion import install_admin_ingestion_routes
from knowledge_engine.m26_admin_ingestion_sync import SyncBlogRequest, build_sync_plan
from knowledge_engine.m26_ingestion_candidate_writer import CandidateVectorVerification
from knowledge_engine.m26_sqlite_ingestion import (
    SQLiteIngestionAdapter,
    SQLiteIngestionLedger,
    active_manifest_observer_from_store,
    candidate_executor_from_primitives,
    dynamic_source_observer_from_path,
)
from knowledge_engine.storage import FileObjectStore, ObjectMetadata, sha256_bytes


class _Authenticator:
    def authenticate(self, assertion: str | None) -> AdminActor:
        if assertion != "valid":
            raise AdminAPIError(status_code=403, code="AUTH_INVALID", message="invalid")
        return AdminActor("owner", "owner", None, "human", "issuer", ("aud",))


class _Capabilities:
    def get_capability(self, capability_id: str) -> object:
        del capability_id
        return type(
            "Gate",
            (),
            {"effective_state": "enabled", "mutation_authorized": True, "reason_code": "TEST"},
        )()


class _Audit:
    def append(self, event: object) -> None:
        del event


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _write_source(root: Path, count: int) -> None:
    for index in range(count):
        path = root / "src/content/blog" / f"article-{index:03d}" / "en.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Article {index}\n\nbody {index}\n", encoding="utf-8")


def _lease(
    ledger: SQLiteIngestionLedger,
    key: str,
    request: SyncBlogRequest,
) -> StatefulIdempotencyLease:
    return IdempotencyCoordinator(ledger).begin_stateful(
        actor_id="owner",
        method="POST",
        path="/v1/admin/ingestion/sync",
        idempotency_key=key,
        request_payload=request.model_dump(exclude_none=True),
    )


def _job_id(lease: StatefulIdempotencyLease) -> str:
    return "syncjob_" + lease.operation_id.removeprefix("admop_")


class RecordingStore(FileObjectStore):
    def __init__(
        self,
        root: Path,
        events: list[str],
        *,
        fail_kind: str | None = None,
    ) -> None:
        super().__init__(root)
        self.events = events
        self.fail_kind = fail_kind

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
        self.events.append("r2:" + key)
        if self.fail_kind == "artifact" and "/artifacts/" in key:
            raise RuntimeError("injected candidate artifact write failure")
        if self.fail_kind == "manifest" and key.endswith("/manifest.json"):
            raise RuntimeError("injected candidate manifest interruption")
        return super().put(
            key,
            data,
            content_type=content_type,
            sha256=sha256,
            expected_etag=expected_etag,
            only_if_absent=only_if_absent,
        )


class InventoryVectorMaterializer:
    def __init__(
        self,
        events: list[str],
        *,
        failures: int = 0,
    ) -> None:
        self.events = events
        self.failures = failures
        self.calls = 0
        self.collections: dict[str, dict[str, dict[str, Any]]] = {}
        self.active_qdrant_mutations = 0

    def materialize_and_verify(
        self,
        *,
        collection_name: str,
        release_id: str,
        semantic_documents: Sequence[Mapping[str, Any]],
    ) -> CandidateVectorVerification:
        self.calls += 1
        self.events.append("qdrant:" + collection_name)
        assert collection_name.startswith("m26_blog_m26blog_bp5r1_")
        if self.failures:
            self.failures -= 1
            raise RuntimeError("injected candidate vector failure")
        points = {
            str(document["section_id"]): {
                "section_id": str(document["section_id"]),
                "release_id": release_id,
                "candidate_release_eligible": True,
                "production_authority": False,
                "text_sha256": hashlib.sha256(str(document["text"]).encode()).hexdigest(),
            }
            for document in semantic_documents
        }
        self.collections[collection_name] = points
        readback_ids = tuple(sorted(self.collections[collection_name]))
        inventory_sha256 = hashlib.sha256(_json_bytes(readback_ids)).hexdigest()
        return CandidateVectorVerification(
            collection_name=collection_name,
            release_id=release_id,
            point_count=len(readback_ids),
            section_ids=readback_ids,
            detail={
                "full_readback": True,
                "inventory_sha256": inventory_sha256,
                "production_authority": False,
            },
        )


def _artifact_builder(
    source_root: Path,
    release_id: str,
) -> Any:
    def build(context: Mapping[str, Any]) -> Mapping[str, Any]:
        source = context["source"]
        lexical: list[dict[str, Any]] = []
        semantic: list[dict[str, Any]] = []
        source_rows: list[dict[str, Any]] = []
        for document in source["documents"]:
            document_id = str(document["document_id"])
            text = (source_root / str(document["origin_path"])).read_text(encoding="utf-8")
            section_id = document_id + "::body"
            lexical.append({"document_id": document_id, "section_id": section_id, "body": text})
            semantic.append(
                {
                    "document_id": document_id,
                    "section_id": section_id,
                    "text": text,
                    "payload": {"source_id": document_id},
                }
            )
            source_rows.append(dict(document))
        artifacts = {
            "document_pack_admission": _json_bytes(
                {"source_identity_digest": source["source_identity_digest"]}
            ),
            "document_source_index": _json_bytes({"entries": source_rows}),
            "graph": _json_bytes({"nodes": [], "edges": []}),
            "graph_v2": _json_bytes({"nodes": [], "edges": []}),
            "lexical_index": _json_bytes({"documents": lexical}),
            "provenance": _json_bytes(
                {"records": [{"source_id": row["document_id"]} for row in source_rows]}
            ),
            "semantic_inputs": _json_bytes({"documents": semantic}),
            "source_documents": _json_bytes({"documents": source_rows}),
        }
        source_sha = hashlib.sha256(str(source["source_revision"]).encode()).hexdigest()
        return {
            "release_id": release_id,
            "source_commit_sha": source_sha[:40],
            "source_repository_head_sha": source_sha[24:],
            "admission_sha256": str(source["source_identity_digest"]),
            "source_count": len(source_rows),
            "artifact_bytes": artifacts,
            "created_at": "2026-09-09T00:00:00Z",
        }

    return build


def _pipeline(
    tmp_path: Path,
    *,
    source_root: Path,
    active: Mapping[str, Any] | Any,
    release_id: str,
    store: RecordingStore | None = None,
    vector: InventoryVectorMaterializer | None = None,
) -> tuple[
    SQLiteIngestionAdapter, SQLiteIngestionLedger, RecordingStore, InventoryVectorMaterializer
]:
    events: list[str] = []
    candidate_store = store or RecordingStore(tmp_path / "candidate-objects", events)
    vector_store = vector or InventoryVectorMaterializer(events)
    ledger = SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3")
    active_observer = active if callable(active) else lambda: dict(active)
    executor = candidate_executor_from_primitives(
        store=candidate_store,
        vector_materializer=vector_store,
        artifact_builder=_artifact_builder(source_root, release_id),
    )
    return (
        SQLiteIngestionAdapter(
            ledger,
            source_observer=dynamic_source_observer_from_path(source_root),
            active_manifest_observer=active_observer,
            candidate_executor=executor,
        ),
        ledger,
        candidate_store,
        vector_store,
    )


def _active(document_digests: Mapping[str, str]) -> dict[str, Any]:
    return {
        "manifest_key": "releases/active-production/promotion/manifest.json",
        "manifest_sha256": "a" * 64,
        "document_digests": dict(document_digests),
    }


def test_active_observer_uses_read_only_production_pointer_resolver(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "active-store")
    release_id = "active-production-fixture"
    lexical = _json_bytes({"documents": [{"document_id": "article", "digest": "d" * 64}]})
    payloads = {
        "graph": _json_bytes({"nodes": []}),
        "graph_v2": _json_bytes({"nodes": []}),
        "lexical_index": lexical,
        "provenance": _json_bytes({"records": []}),
    }
    artifacts = []
    for kind, data in payloads.items():
        key = f"releases/{release_id}/artifacts/{kind}.json"
        store.put(key, data, content_type="application/json", only_if_absent=True)
        artifacts.append(
            {"kind": kind, "key": key, "sha256": sha256_bytes(data), "bytes": len(data)}
        )
    candidate = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": release_id,
        "status": "candidate",
        "authority": {"production_pointer_authorized": False},
        "identities": {"source_commit_sha": "1" * 40, "admission_sha256": "2" * 64},
        "counts": {"semantic_documents": 1},
        "artifacts": artifacts,
    }
    candidate_key = f"releases/{release_id}/manifest.json"
    candidate_bytes = _json_bytes(candidate)
    store.put(candidate_key, candidate_bytes, content_type="application/json")
    production = deepcopy(candidate)
    production["status"] = "production"
    production["authority"]["production_pointer_authorized"] = True
    production["production_promotion"] = {
        "production_pointer_authorized": True,
        "source_candidate_manifest_key": candidate_key,
        "source_candidate_manifest_sha256": sha256_bytes(candidate_bytes),
        "qdrant_candidate_collection": "m26_blog_active_production_fixture",
    }
    production_key = f"releases/{release_id}/promotion/production-manifest.json"
    production_bytes = _json_bytes(production)
    store.put(production_key, production_bytes, content_type="application/json")
    pointer = _json_bytes(
        {
            "schema_version": "1.0",
            "channel": "production",
            "production_authority": True,
            "release_id": release_id,
            "manifest_key": production_key,
            "manifest_sha256": sha256_bytes(production_bytes),
        }
    )
    store.put("channels/production.json", pointer, content_type="application/json")

    observed = active_manifest_observer_from_store(store)()

    assert observed == {
        "manifest_key": candidate_key,
        "manifest_sha256": sha256_bytes(candidate_bytes),
        "document_digests": {"article": "d" * 64},
    }


def test_noop_is_durable_reconnectable_and_has_zero_candidate_mutation(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_source(source_root, 2)
    observed = dynamic_source_observer_from_path(source_root)()
    active = _active({row["document_id"]: row["digest"] for row in observed["documents"]})
    ledger = SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3")
    calls = 0

    def forbidden_executor(*_args: Any) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        raise AssertionError("no-op must not execute candidate work")

    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=dynamic_source_observer_from_path(source_root),
        active_manifest_observer=lambda: active,
        candidate_executor=forbidden_executor,
    )
    request = SyncBlogRequest()
    lease = _lease(ledger, "bp5r1-noop-key-0001", request)
    result = adapter.sync_blog_with_lease(lease.operation_id, request, lease)

    assert result["status"] == "SUCCEEDED"
    assert result["result"]["status"] == "noop"
    assert calls == 0
    reopened = SQLiteIngestionLedger(ledger.path)
    assert reopened.get_job(_job_id(lease)) == result
    assert reopened.list_jobs() == [result]


def test_http_one_click_binds_durable_controller_and_candidate_primitives(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_source(source_root, 1)
    adapter, ledger, store, vector = _pipeline(
        tmp_path,
        source_root=source_root,
        active=_active({}),
        release_id="m26blog-bp5r1-http-e2e",
    )
    app = FastAPI()
    install_admin_control_plane(
        app,
        authenticator=_Authenticator(),
        capability_provider=_Capabilities(),
        audit_sink=_Audit(),
        idempotency_store=ledger,
    )
    install_admin_ingestion_routes(app, adapter=adapter, include_job_reads=True)
    client = TestClient(app)
    headers = {
        "origin": "https://console.danielcanfly.com",
        "cf-access-jwt-assertion": "valid",
        "idempotency-key": "bp5r1-http-one-click",
    }

    response = client.post("/v1/admin/ingestion/sync", headers=headers, json={})

    assert response.status_code == 202
    job_id = response.json()["result"]["job_id"]
    reconnected = client.get(
        "/v1/admin/ingestion/jobs/" + job_id,
        headers={**headers, "idempotency-key": "bp5r1-http-get-job1"},
    )
    job = reconnected.json()["data"]
    assert reconnected.status_code == 200
    assert job["status"] == "SUCCEEDED"
    assert job["candidate_release_id"] == "m26blog-bp5r1-http-e2e"
    assert store.head(job["candidate_manifest_key"]) is not None
    assert vector.calls == 1
    assert vector.active_qdrant_mutations == 0


def test_dynamic_181st_article_runs_real_candidate_writer_and_full_vector_readback(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_source(source_root, 181)
    observed = dynamic_source_observer_from_path(source_root)()
    active = _active(
        {
            row["document_id"]: row["digest"]
            for row in observed["documents"]
            if row["document_id"] != "daniel_blog_en__article-180"
        }
    )
    events: list[str] = []
    store = RecordingStore(tmp_path / "candidate-objects", events)
    vector = InventoryVectorMaterializer(events)
    adapter, ledger, _, _ = _pipeline(
        tmp_path,
        source_root=source_root,
        active=active,
        release_id="m26blog-bp5r1-article-181",
        store=store,
        vector=vector,
    )
    request = SyncBlogRequest()
    lease = _lease(ledger, "bp5r1-add-181-key1", request)

    result = adapter.sync_blog_with_lease(lease.operation_id, request, lease)
    receipt = result["result"]
    manifest_key = receipt["manifest_key"]
    lexical_key = manifest_key.replace("manifest.json", "artifacts/lexical_index.json")
    lexical_ids = {row["section_id"] for row in json.loads(store.get(lexical_key))["documents"]}
    vector_ids = set(vector.collections[receipt["qdrant_collection"]])

    assert result["status"] == "SUCCEEDED"
    assert receipt["source_count"] == 181
    assert receipt["vector"]["point_count"] == 181
    assert receipt["vector"]["detail"]["full_readback"] is True
    assert lexical_ids == vector_ids
    assert events[-1] == "r2:" + manifest_key
    assert all("channels/" not in event for event in events)
    assert result["candidate_release_id"] == receipt["release_id"]
    assert result["candidate_manifest_key"] == manifest_key
    assert result["candidate_manifest_sha256"] == receipt["manifest_sha256"]
    assert result["source_identity_digest"] == observed["source_identity_digest"]
    assert vector.active_qdrant_mutations == 0


def test_modified_article_builds_candidate_artifacts_with_exact_parity(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_source(source_root, 1)
    before = dynamic_source_observer_from_path(source_root)()
    path = source_root / "src/content/blog/article-000/en.md"
    path.write_text("# Article 0\n\nmodified body\n", encoding="utf-8")
    adapter, ledger, store, vector = _pipeline(
        tmp_path,
        source_root=source_root,
        active=_active({before["documents"][0]["document_id"]: before["documents"][0]["digest"]}),
        release_id="m26blog-bp5r1-modified",
    )
    request = SyncBlogRequest()
    lease = _lease(ledger, "bp5r1-modified-key1", request)

    result = adapter.sync_blog_with_lease(lease.operation_id, request, lease)

    assert result["manifest_diff"]["changed"] == ["daniel_blog_en__article-000"]
    assert result["result"]["lexical_document_count"] == 1
    assert result["result"]["semantic_document_count"] == 1
    assert store.head(result["candidate_manifest_key"]) is not None
    assert vector.calls == 1


def test_removed_source_requires_confirmation_then_exact_digest_builds_candidate_only(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_source(source_root, 2)
    observed = dynamic_source_observer_from_path(source_root)()
    digests = {row["document_id"]: row["digest"] for row in observed["documents"]}
    digests["daniel_blog_en__article-removed"] = "f" * 64
    active = _active(digests)

    denied_events: list[str] = []
    denied_store = RecordingStore(tmp_path / "denied-objects", denied_events)
    denied_vector = InventoryVectorMaterializer(denied_events)
    denied, denied_ledger, _, _ = _pipeline(
        tmp_path / "denied",
        source_root=source_root,
        active=active,
        release_id="m26blog-bp5r1-remove-denied",
        store=denied_store,
        vector=denied_vector,
    )
    denied_request = SyncBlogRequest()
    denied_lease = _lease(denied_ledger, "bp5r1-remove-deny1", denied_request)
    with pytest.raises(AdminAPIError) as denied_error:
        denied.sync_blog_with_lease(denied_lease.operation_id, denied_request, denied_lease)
    assert denied_error.value.code == "ADMIN_INGESTION_DESTRUCTIVE_CONFIRMATION_REQUIRED"
    assert denied_events == []

    plan = build_sync_plan(
        source_revision=str(observed["source_revision"]),
        documents=observed["documents"],
        active_document_digests=active["document_digests"],
    )
    allowed, ledger, store, vector = _pipeline(
        tmp_path / "allowed",
        source_root=source_root,
        active=active,
        release_id="m26blog-bp5r1-remove-confirmed",
    )
    request = SyncBlogRequest(confirmation=True, expected_plan_digest=plan["plan_digest"])
    lease = _lease(ledger, "bp5r1-remove-allow", request)
    result = allowed.sync_blog_with_lease(lease.operation_id, request, lease)

    assert result["status"] == "SUCCEEDED"
    assert result["manifest_diff"]["removed"] == ["daniel_blog_en__article-removed"]
    assert result["result"]["authority"]["production_pointer_writes"] == 0
    assert store.head(result["candidate_manifest_key"]) is not None
    assert vector.active_qdrant_mutations == 0


@pytest.mark.parametrize("drift", ["source", "active"])
def test_reviewed_state_drift_fails_before_candidate_work(tmp_path: Path, drift: str) -> None:
    source = {
        "source_revision": "source-r1",
        "source_identity_digest": "1" * 64,
        "documents": [{"document_id": "article", "digest": "1" * 64}],
    }
    active = _active({"removed-article": "f" * 64})
    source_calls = 0
    active_calls = 0
    candidate_calls = 0

    def source_observer() -> Mapping[str, Any]:
        nonlocal source_calls
        source_calls += 1
        if drift == "source" and source_calls == 2:
            return {**source, "source_revision": "source-r2"}
        return dict(source)

    def active_observer() -> Mapping[str, Any]:
        nonlocal active_calls
        active_calls += 1
        if drift == "active" and active_calls == 2:
            return {**active, "manifest_sha256": "b" * 64}
        return dict(active)

    def candidate(*_args: Any) -> Mapping[str, Any]:
        nonlocal candidate_calls
        candidate_calls += 1
        return {}

    ledger = SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3")
    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=source_observer,
        active_manifest_observer=active_observer,
        candidate_executor=candidate,
    )
    reviewed = build_sync_plan(
        source_revision=str(source["source_revision"]),
        documents=source["documents"],
        active_document_digests=active["document_digests"],
    )
    request = SyncBlogRequest(
        confirmation=True,
        expected_plan_digest=reviewed["plan_digest"],
    )
    lease = _lease(ledger, f"bp5r1-{drift}-drift1", request)
    with pytest.raises(AdminAPIError) as failure:
        adapter.sync_blog_with_lease(lease.operation_id, request, lease)

    assert failure.value.code == "ADMIN_INGESTION_STALE_PLAN"
    assert candidate_calls == 0
    assert ledger.get_job(_job_id(lease))["status"] == "FAILED"


@pytest.mark.parametrize("observer", ["source", "active"])
def test_observer_failure_is_a_visible_durable_failed_job(tmp_path: Path, observer: str) -> None:
    def fail() -> Mapping[str, Any]:
        raise RuntimeError("credential detail must not persist")

    valid_source = {
        "source_revision": "source-r1",
        "documents": [{"document_id": "article", "digest": "a" * 64}],
    }
    ledger = SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3")
    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=fail if observer == "source" else lambda: valid_source,
        active_manifest_observer=fail if observer == "active" else lambda: _active({}),
        candidate_executor=lambda *_args: {},
    )
    request = SyncBlogRequest()
    lease = _lease(ledger, f"bp5r1-{observer}-failure", request)
    with pytest.raises(RuntimeError):
        adapter.sync_blog_with_lease(lease.operation_id, request, lease)

    job = SQLiteIngestionLedger(ledger.path).get_job(_job_id(lease))
    assert job["status"] == "FAILED"
    assert job["error_code"] == "ADMIN_INGESTION_EXECUTION_FAILED"
    assert "credential detail" not in job["error_detail"]


@pytest.mark.parametrize("failure", ["artifact", "vector", "manifest"])
def test_candidate_failure_is_durable_and_never_finalizes_manifest(
    tmp_path: Path,
    failure: str,
) -> None:
    source_root = tmp_path / "source"
    _write_source(source_root, 1)
    events: list[str] = []
    store = RecordingStore(
        tmp_path / "candidate-objects",
        events,
        fail_kind=failure if failure in {"artifact", "manifest"} else None,
    )
    vector = InventoryVectorMaterializer(events, failures=1 if failure == "vector" else 0)
    adapter, ledger, _, _ = _pipeline(
        tmp_path,
        source_root=source_root,
        active=_active({}),
        release_id=f"m26blog-bp5r1-failure-{failure}",
        store=store,
        vector=vector,
    )
    request = SyncBlogRequest()
    lease = _lease(ledger, f"bp5r1-{failure}-fail1", request)
    with pytest.raises(RuntimeError):
        adapter.sync_blog_with_lease(lease.operation_id, request, lease)

    manifest_key = f"releases/m26blog-bp5r1-failure-{failure}/manifest.json"
    job = ledger.get_job(_job_id(lease))
    assert job["status"] == "FAILED"
    assert job["candidate_manifest_key"] is None
    assert store.head(manifest_key) is None
    assert all("channels/" not in event for event in events)


def test_failed_destructive_candidate_retry_reuses_artifacts_and_advances_once(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_source(source_root, 1)
    observed = dynamic_source_observer_from_path(source_root)()
    active = _active(
        {
            observed["documents"][0]["document_id"]: observed["documents"][0]["digest"],
            "daniel_blog_en__removed": "f" * 64,
        }
    )
    plan = build_sync_plan(
        source_revision=str(observed["source_revision"]),
        documents=observed["documents"],
        active_document_digests=active["document_digests"],
    )
    events: list[str] = []
    store = RecordingStore(tmp_path / "candidate-objects", events)
    vector = InventoryVectorMaterializer(events, failures=1)
    adapter, ledger, _, _ = _pipeline(
        tmp_path,
        source_root=source_root,
        active=active,
        release_id="m26blog-bp5r1-retry",
        store=store,
        vector=vector,
    )
    request = SyncBlogRequest(confirmation=True, expected_plan_digest=plan["plan_digest"])
    lease = _lease(ledger, "bp5r1-retry-key001", request)
    with pytest.raises(RuntimeError, match="vector"):
        adapter.sync_blog_with_lease(lease.operation_id, request, lease)
    first = ledger.get_job(_job_id(lease))
    first_artifact_writes = len([event for event in events if "/artifacts/" in event])

    result = adapter.retry_job(_job_id(lease), owner="retry-owner")

    assert first["attempt"] == 1 and first["status"] == "FAILED"
    assert result["attempt"] == 2 and result["status"] == "SUCCEEDED"
    assert result["request_payload"] == request.model_dump(exclude_none=True)
    assert len([event for event in events if "/artifacts/" in event]) == first_artifact_writes
    assert vector.calls == 2
    assert store.head(result["candidate_manifest_key"]) is not None


def test_succeeded_replay_and_two_connection_duplicate_race_run_candidate_once(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_source(source_root, 1)
    events: list[str] = []
    store = RecordingStore(tmp_path / "candidate-objects", events)
    vector = InventoryVectorMaterializer(events)
    adapter, ledger, _, _ = _pipeline(
        tmp_path,
        source_root=source_root,
        active=_active({}),
        release_id="m26blog-bp5r1-idempotent",
        store=store,
        vector=vector,
    )
    request = SyncBlogRequest()
    key = "bp5r1-duplicate-key"
    lease = _lease(ledger, key, request)
    first = adapter.sync_blog_with_lease(lease.operation_id, request, lease)
    replay = _lease(SQLiteIngestionLedger(ledger.path), key, request)
    second = adapter.sync_blog_with_lease(replay.operation_id, request, replay)

    assert replay.replayed is True
    assert second == first
    assert vector.calls == 1

    race_path = tmp_path / "race.sqlite3"
    coordinators = [
        IdempotencyCoordinator(SQLiteIngestionLedger(race_path)),
        IdempotencyCoordinator(SQLiteIngestionLedger(race_path)),
    ]
    leases: list[StatefulIdempotencyLease] = []
    errors: list[str] = []

    def begin(coordinator: IdempotencyCoordinator) -> None:
        try:
            leases.append(
                coordinator.begin_stateful(
                    actor_id="owner",
                    method="POST",
                    path="/v1/admin/ingestion/sync",
                    idempotency_key="bp5r1-two-browser-race",
                    request_payload=request.model_dump(exclude_none=True),
                )
            )
        except AdminAPIError as exc:
            errors.append(exc.code)

    threads = [threading.Thread(target=begin, args=(coordinator,)) for coordinator in coordinators]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(leases) == 1
    assert errors == ["ADMIN_IDEMPOTENCY_IN_PROGRESS"]
