from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.config import Settings
from knowledge_engine.errors import ConfigurationError, IntegrityError
from knowledge_engine.m14_retrieval import retrieve_wiki_first
from knowledge_engine.runtime import Runtime
from knowledge_engine.storage import sha256_bytes


def _document(concept_id: str, title: str, audience: str = "public") -> dict:
    return {
        "concept_id": concept_id,
        "section_id": f"{concept_id}#overview",
        "title": title,
        "section_title": "Overview",
        "description": title,
        "body": title,
        "excerpt": title,
        "audience": audience,
        "terms": title.casefold().split(),
    }


def _provenance(*concept_ids: str) -> dict:
    return {
        "records": [
            {
                "subject": {"concept_id": concept_id},
                "sources": [
                    {
                        "source_id": f"source-{index}",
                        "uri": f"https://example.com/{index}",
                        "retrieved_at": "2026-07-13T00:00:00Z",
                    }
                ],
            }
            for index, concept_id in enumerate(concept_ids, start=1)
        ]
    }


def _relation_graph(nodes: list[dict], edges: list[dict]) -> dict:
    return {
        "schema_version": "knowledge-os-graph/v2",
        "release": {"release_id": "release-test"},
        "nodes": nodes,
        "edges": edges,
        "renderer_neutral": True,
    }


def _edge(
    edge_id: str,
    source: str,
    target: str,
    *,
    audience: str = "public",
    relation_type: str = "complements",
    directed: bool = False,
) -> dict:
    return {
        "edge_id": edge_id,
        "source": source,
        "target": target,
        "relation_type": relation_type,
        "directed": directed,
        "audience": audience,
        "confidence": 0.9,
        "review_status": "approved",
        "review_id": f"review-{edge_id}",
        "provenance_record": "provenance/test.json",
        "provenance_ref": "claim-test",
        "generated_inverse": False,
    }


def _replace_manifest(store, compiled, transform) -> str:
    pointer_key = "channels/staging.json"
    pointer = json.loads(store.get(pointer_key))
    manifest_key = pointer["manifest_key"]
    manifest = json.loads(store.get(manifest_key))
    transform(manifest)
    manifest_data = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_metadata = store.head(manifest_key)
    assert manifest_metadata is not None
    store.put(
        manifest_key,
        manifest_data,
        content_type="application/json",
        expected_etag=manifest_metadata.etag,
    )
    manifest_sha = sha256_bytes(manifest_data)
    pointer["manifest_sha256"] = manifest_sha
    pointer_metadata = store.head(pointer_key)
    assert pointer_metadata is not None
    store.put(
        pointer_key,
        (json.dumps(pointer, sort_keys=True) + "\n").encode(),
        content_type="application/json",
        expected_etag=pointer_metadata.etag,
    )
    assert manifest["release_id"] == compiled.release_id
    return manifest_sha


def test_relation_aware_flag_defaults_off_and_parses_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "filesystem")
    assert Settings.from_env().relation_aware_expansion_enabled is False
    monkeypatch.setenv("RELATION_AWARE_EXPANSION_ENABLED", "true")
    assert Settings.from_env().relation_aware_expansion_enabled is True
    monkeypatch.setenv("RELATION_AWARE_EXPANSION_ENABLED", "sometimes")
    with pytest.raises(ConfigurationError, match="must be a boolean"):
        Settings.from_env()


def test_runtime_loads_graph_v2_but_keeps_expansion_disabled(
    tmp_path: Path,
    built_store,
) -> None:
    store, compiled, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")
    active = runtime.refresh()
    assert active.release_id == compiled.release_id
    assert active.graph_v2 is not None
    assert active.graph_v2["schema_version"] == "knowledge-os-graph/v2"
    result = runtime.query("knowledge compiler", {"public", "internal"})
    assert result["retrieval"]["relation_graph_available"] is True
    assert result["retrieval"]["relation_aware_expansion_enabled"] is False
    assert result["retrieval"]["relation_aware_expansion_used"] is False


def test_runtime_accepts_legacy_release_without_graph_v2(
    tmp_path: Path,
    built_store,
) -> None:
    store, compiled, _ = built_store

    def remove_graph_v2(manifest: dict) -> None:
        manifest["artifacts"] = [
            item for item in manifest["artifacts"] if item["kind"] != "graph_v2"
        ]

    manifest_sha = _replace_manifest(store, compiled, remove_graph_v2)
    runtime = Runtime(store, tmp_path / "legacy-cache", "staging")
    active = runtime.refresh(expected_manifest_sha256=manifest_sha)
    assert active.graph_v2 is None
    result = runtime.query("knowledge compiler", {"public", "internal"})
    assert result["status"] == "answered"
    assert result["retrieval"]["relation_graph_available"] is False


def test_invalid_graph_v2_preserves_last_known_good(
    tmp_path: Path,
    built_store,
) -> None:
    store, compiled, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")
    active = runtime.refresh()
    graph_item = next(
        item for item in compiled.manifest["artifacts"] if item["kind"] == "graph_v2"
    )
    graph = json.loads(store.get(graph_item["key"]))
    graph["renderer_neutral"] = False
    graph_data = (json.dumps(graph, sort_keys=True) + "\n").encode()
    graph_metadata = store.head(graph_item["key"])
    assert graph_metadata is not None
    store.put(
        graph_item["key"],
        graph_data,
        content_type="application/json",
        expected_etag=graph_metadata.etag,
    )

    def update_graph_artifact(manifest: dict) -> None:
        item = next(value for value in manifest["artifacts"] if value["kind"] == "graph_v2")
        item["sha256"] = sha256_bytes(graph_data)
        item["bytes"] = len(graph_data)

    _replace_manifest(store, compiled, update_graph_artifact)
    with pytest.raises(IntegrityError, match="renderer neutral"):
        runtime.refresh()
    assert runtime.active is active


def test_disabled_relation_hook_preserves_lexical_and_generic_baseline() -> None:
    concepts = ("concepts/seed", "concepts/generic", "concepts/typed")
    documents = [
        _document("concepts/seed", "Seed topic"),
        _document("concepts/generic", "Generic neighbor"),
        _document("concepts/typed", "Typed neighbor"),
    ]
    graph = {
        "nodes": [
            {"concept_id": concept_id, "audience": "public"}
            for concept_id in concepts
        ],
        "edges": [
            {
                "from_concept_id": "concepts/seed",
                "to_concept_id": "concepts/generic",
            }
        ],
    }
    graph_v2 = _relation_graph(
        [{"concept_id": concept_id, "audience": "public"} for concept_id in concepts],
        [_edge("edge-typed", "concepts/seed", "concepts/typed")],
    )
    common = {
        "query": "seed",
        "allowed_audiences": {"public"},
        "lexical_index": {"documents": documents},
        "graph": graph,
        "provenance": _provenance(*concepts),
    }
    baseline = retrieve_wiki_first(**common)
    disabled = retrieve_wiki_first(
        **common,
        relation_graph=graph_v2,
        relation_aware_expansion=False,
    )
    assert disabled["results"] == baseline["results"]
    assert disabled["retrieval"]["graph_expanded_count"] == 1
    assert disabled["retrieval"]["relation_expanded_count"] == 0
    assert {item["concept_id"] for item in disabled["results"]} == {
        "concepts/seed",
        "concepts/generic",
    }


def test_enabled_relation_expansion_is_single_hop_acl_safe_and_exposes_evidence() -> None:
    concepts = (
        "concepts/seed",
        "concepts/generic",
        "concepts/typed",
        "concepts/internal",
    )
    audiences = {
        "concepts/seed": "public",
        "concepts/generic": "public",
        "concepts/typed": "public",
        "concepts/internal": "internal",
    }
    documents = [
        _document(concept_id, concept_id.rsplit("/", 1)[-1], audiences[concept_id])
        for concept_id in concepts
    ]
    graph = {
        "nodes": [
            {"concept_id": concept_id, "audience": audiences[concept_id]}
            for concept_id in concepts
        ],
        "edges": [
            {
                "from_concept_id": "concepts/seed",
                "to_concept_id": "concepts/generic",
            }
        ],
    }
    graph_v2 = _relation_graph(
        [
            {"concept_id": concept_id, "audience": audiences[concept_id]}
            for concept_id in concepts
        ],
        [
            _edge("edge-public", "concepts/seed", "concepts/typed"),
            _edge(
                "edge-internal",
                "concepts/seed",
                "concepts/internal",
                audience="internal",
            ),
        ],
    )
    result = retrieve_wiki_first(
        query="seed",
        allowed_audiences={"public"},
        lexical_index={"documents": documents},
        graph=graph,
        relation_graph=graph_v2,
        relation_aware_expansion=True,
        provenance=_provenance(*concepts),
    )
    by_id = {item["concept_id"]: item for item in result["results"]}
    assert set(by_id) == {"concepts/seed", "concepts/generic", "concepts/typed"}
    assert by_id["concepts/generic"]["score_components"]["graph"] == 1
    assert by_id["concepts/typed"]["score_components"]["relation_graph"] == 1
    assert by_id["concepts/typed"]["relation_expansions"] == [
        {
            "edge_id": "edge-public",
            "source": "concepts/seed",
            "target": "concepts/typed",
            "relation_type": "complements",
            "directed": False,
            "generated_inverse": False,
            "confidence": 0.9,
            "review_id": "review-edge-public",
            "provenance_record": "provenance/test.json",
            "provenance_ref": "claim-test",
        }
    ]
    assert result["retrieval"]["relation_aware_expansion_used"] is True
    assert result["retrieval"]["relation_expanded_count"] == 1
    assert result["retrieval"]["relation_types_used"] == ["complements"]
    assert result["retrieval"]["acl_filtered_count"] == 1


def test_graph_v2_acl_mismatch_fails_closed() -> None:
    graph_v2 = _relation_graph(
        [
            {"concept_id": "concepts/public", "audience": "public"},
            {"concept_id": "concepts/internal", "audience": "internal"},
        ],
        [
            _edge(
                "edge-broadened",
                "concepts/public",
                "concepts/internal",
                audience="public",
            )
        ],
    )
    with pytest.raises(IntegrityError, match="audience mismatch"):
        retrieve_wiki_first(
            query="public",
            allowed_audiences={"public"},
            lexical_index={
                "documents": [
                    _document("concepts/public", "public"),
                    _document("concepts/internal", "internal", "internal"),
                ]
            },
            graph={
                "nodes": [
                    {"concept_id": "concepts/public", "audience": "public"},
                    {"concept_id": "concepts/internal", "audience": "internal"},
                ],
                "edges": [],
            },
            relation_graph=graph_v2,
            relation_aware_expansion=False,
            provenance=_provenance("concepts/public", "concepts/internal"),
        )
