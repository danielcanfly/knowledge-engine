from __future__ import annotations

from knowledge_engine import m26_ingestion_read_runtime as read_runtime
from knowledge_engine.m26_sqlite_ingestion import (
    SQLiteIngestionLedger,
    SQLiteIngestionReadAuthority,
)


def test_read_authority_is_enriched_without_restoring_mutation_seams(monkeypatch, tmp_path):
    ledger = SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3")
    original = SQLiteIngestionReadAuthority(
        ledger,
        [
            "M26_INGESTION_ENABLED",
            "M26_INGESTION_PRODUCTION_ACTIVATION_ENABLED",
            "M26_INGESTION_OWNER_AUTHORIZATION",
        ],
    )

    source_observer = lambda: {  # noqa: E731
        "source_revision": "git:" + "a" * 40,
        "source_identity_digest": "b" * 64,
        "documents": [],
    }
    active_observer = lambda: {  # noqa: E731
        "release_id": "release-active",
        "manifest_key": "releases/release-active/manifest.json",
        "manifest_sha256": "c" * 64,
        "document_digests": {},
    }
    candidate_observer = lambda key, digest: {  # noqa: E731, ARG005
        "release_id": "candidate"
    }

    monkeypatch.setattr(
        read_runtime,
        "_read_source_observer",
        lambda: (source_observer, []),
    )
    monkeypatch.setattr(read_runtime.Settings, "from_env", lambda: object())
    monkeypatch.setattr(read_runtime, "create_object_store", lambda settings: object())
    monkeypatch.setattr(
        read_runtime,
        "active_manifest_observer_from_store",
        lambda store: active_observer,
    )
    monkeypatch.setattr(
        read_runtime,
        "candidate_manifest_observer_from_store",
        lambda store: candidate_observer,
    )

    enriched = read_runtime.enrich_read_authority_from_env(original)

    assert isinstance(enriched, SQLiteIngestionReadAuthority)
    assert enriched.missing_seams == ()
    assert enriched.source_observer is source_observer
    assert enriched.active_manifest_observer is active_observer
    assert enriched.candidate_manifest_observer is candidate_observer
    assert enriched.production_activation_authorized is False
    assert not hasattr(enriched, "candidate_executor")

    observation = enriched.current_index()
    assert observation.availability == "available"
    assert observation.data["source"]["source_revision"] == "git:" + "a" * 40
    assert observation.data["active"]["release_id"] == "release-active"
    assert observation.data["finalization_authorized"] is False
