import json
import time

from knowledge_engine.m26_console_health_runtime import MaterializedConsoleHealthObserver
from knowledge_engine.m26_runtime_read_cache import materialized_cache_path


def test_materialized_health_projects_active_cache_without_remote_reads(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    now = time.time()
    path = materialized_cache_path("active")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "m26-runtime-read-cache/v1",
                "role": "active",
                "cached_at_epoch": now,
                "payload": {
                    "release_id": "release-1",
                    "production_manifest_sha256": "manifest-1",
                    "pointer_sha256": "pointer-1",
                    "qdrant_collection": "collection-1",
                    "lexical_chunk_count": 4828,
                    "vector_chunk_count": 4828,
                    "document_count": 223,
                },
            }
        ),
        encoding="utf-8",
    )

    observer = MaterializedConsoleHealthObserver()
    rows = observer.collect(None)

    assert rows["production"]["status"] == "healthy"
    assert rows["r2"]["status"] == "healthy"
    assert rows["qdrant"]["status"] == "healthy"
    assert rows["qdrant"]["expected"] == 4828
    assert rows["qdrant"]["observed"] == 4828
    assert rows["metadata"]["status"] == "healthy"
    assert observer.production_observation()["source"] == "materialized_active_release_cache"


def test_materialized_health_never_calls_provider(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("MINIMAX_API_KEY", "configured-but-never-exposed")
    path = materialized_cache_path("active")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "m26-runtime-read-cache/v1",
                "role": "active",
                "cached_at_epoch": time.time(),
                "payload": {
                    "release_id": "release-1",
                    "production_manifest_sha256": "manifest-1",
                    "pointer_sha256": "pointer-1",
                    "qdrant_collection": "collection-1",
                    "lexical_chunk_count": 1,
                    "vector_chunk_count": 1,
                    "document_count": 1,
                },
            }
        ),
        encoding="utf-8",
    )

    provider = MaterializedConsoleHealthObserver().collect(None)["provider"]
    assert provider["status"] == "read_only"
    assert provider["observed"] == "configured"
    assert "configured-but-never-exposed" not in json.dumps(provider)
