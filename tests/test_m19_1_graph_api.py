from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from knowledge_engine import api
from knowledge_engine.auth import Principal
from knowledge_engine.errors import IntegrityError
from knowledge_engine.m19_graph_api import (
    GRAPH_API_SCHEMA,
    MAX_RESPONSE_BYTES,
    GraphApiNotFoundError,
    GraphApiUnavailableError,
    ReadOnlyGraphService,
)


def _node(concept_id: str, audience: str, title: str) -> dict:
    return {
        "concept_id": concept_id,
        "x_kos_id": f"ko_{concept_id.rsplit('/', 1)[-1]}",
        "title": title,
        "description": f"{title} description",
        "type": "Concept",
        "audience": audience,
        "status": "published",
        "confidence": 0.9,
        "tags": ["agents"],
        "aliases": [title.casefold()],
        "path": f"{concept_id}.md",
        "provenance_record": f"provenance/{concept_id.rsplit('/', 1)[-1]}.json",
    }


def _edge(edge_id: str, source: str, target: str, audience: str) -> dict:
    return {
        "edge_id": edge_id,
        "source": source,
        "target": target,
        "relation_type": "complements",
        "directed": False,
        "audience": audience,
        "confidence": 0.9,
        "review_status": "approved",
        "review_id": "review-secret",
        "provenance_record": "provenance/secret.json",
        "provenance_ref": "claim-secret",
        "generated_inverse": False,
    }


def _active(*, graph_v2: dict | None = None):
    graph = graph_v2
    if graph is None:
        graph = {
            "schema_version": "knowledge-os-graph/v2",
            "release": {
                "release_id": "release-m19",
                "source_commit_sha": "a" * 40,
                "foundation_commit_sha": "b" * 40,
                "content_sha256": "c" * 64,
            },
            "nodes": [
                _node("concepts/public", "public", "Public Agent"),
                _node("concepts/internal", "internal", "Internal Control"),
                _node("concepts/other", "public", "Other Agent"),
            ],
            "edges": [
                _edge("edge-public", "concepts/public", "concepts/other", "public"),
                _edge(
                    "edge-internal",
                    "concepts/public",
                    "concepts/internal",
                    "internal",
                ),
            ],
            "renderer_neutral": True,
        }
    return SimpleNamespace(
        release_id="release-m19",
        manifest_sha256="d" * 64,
        loaded_at="2026-07-13T05:00:00Z",
        manifest={"created_at": "2026-07-13T04:00:00Z"},
        graph_v2=graph,
    )


def _principal(*audiences: str) -> Principal:
    return Principal(
        subject="graph-user",
        audiences=frozenset(audiences),
        claims={},
    )


def test_capabilities_are_read_only_bounded_and_release_exact() -> None:
    payload = ReadOnlyGraphService(_active(), {"public"}).capabilities()
    assert payload["schema_version"] == GRAPH_API_SCHEMA
    assert payload["read_only"] is True
    assert payload["mutation_methods"] == []
    assert payload["maximum_depth"] == 1
    assert payload["cluster_levels"] == ["none"]
    assert payload["release"]["release_id"] == "release-m19"
    assert payload["release"]["manifest_sha256"] == "d" * 64
    assert payload["release"]["source_commit_sha"] == "a" * 40
    assert payload["response_bytes"] <= MAX_RESPONSE_BYTES


def test_search_filters_nodes_before_serialization() -> None:
    service = ReadOnlyGraphService(_active(), {"public"})
    payload = service.search(query="agent", tags=["agents"], types=[], limit=20)
    assert {node["concept_id"] for node in payload["nodes"]} == {
        "concepts/public",
        "concepts/other",
    }
    serialized = str(payload)
    assert "Internal Control" not in serialized
    assert "provenance/" not in serialized
    assert "review-secret" not in serialized


def test_overview_removes_edges_with_unauthorized_endpoints() -> None:
    payload = ReadOnlyGraphService(_active(), {"public"}).overview(
        cluster_level="none",
        max_nodes=100,
        max_edges=100,
    )
    assert {node["concept_id"] for node in payload["nodes"]} == {
        "concepts/public",
        "concepts/other",
    }
    assert [edge["edge_id"] for edge in payload["edges"]] == ["edge-public"]
    assert "concepts/internal" not in str(payload)


def test_node_hides_unauthorized_existence_and_sensitive_metadata() -> None:
    service = ReadOnlyGraphService(_active(), {"public"})
    with pytest.raises(GraphApiNotFoundError, match="authorized graph node"):
        service.node("concepts/internal")
    payload = service.node("concepts/public")
    assert payload["node"]["source_path"] == "concepts/public.md"
    assert "provenance_record" not in payload["node"]


def test_neighborhood_is_single_hop_filtered_and_bounded() -> None:
    public = ReadOnlyGraphService(_active(), {"public"}).neighborhood(
        "concepts/public",
        depth=1,
        relation_types=["complements"],
        max_nodes=2,
        max_edges=1,
    )
    assert public["depth"] == 1
    assert public["node_count"] == 2
    assert public["edge_count"] == 1
    assert {node["concept_id"] for node in public["nodes"]} == {
        "concepts/public",
        "concepts/other",
    }
    internal = ReadOnlyGraphService(_active(), {"public", "internal"}).neighborhood(
        "concepts/public",
        depth=1,
        relation_types=[],
        max_nodes=3,
        max_edges=2,
    )
    assert internal["node_count"] == 3
    assert internal["edge_count"] == 2


def test_graph_api_fails_closed_on_unknown_acl_and_renderer_fields() -> None:
    graph = _active().graph_v2
    graph["nodes"][0]["audience"] = "unknown"
    with pytest.raises(IntegrityError, match="node audience"):
        ReadOnlyGraphService(_active(graph_v2=graph), {"public"})
    graph = _active().graph_v2
    graph["nodes"][0]["color"] = "red"
    with pytest.raises(IntegrityError, match="renderer-specific"):
        ReadOnlyGraphService(_active(graph_v2=graph), {"public"})


def test_legacy_release_advertises_capability_without_graph_data() -> None:
    active = _active()
    active.graph_v2 = None
    service = ReadOnlyGraphService(active, {"public"})
    assert service.capabilities()["graph_v2_available"] is False
    assert service.release()["authorized_node_count"] == 0
    with pytest.raises(GraphApiUnavailableError, match="no graph v2"):
        service.search(query="agent", tags=[], types=[], limit=10)


def test_api_uses_principal_acl_and_maps_unauthorized_node_to_404(monkeypatch) -> None:
    runtime = SimpleNamespace(ensure_loaded=lambda: _active())
    monkeypatch.setattr(api, "get_runtime", lambda: runtime)
    response = api.graph_overview(
        cluster_level="none",
        max_nodes=200,
        max_edges=400,
        principal=_principal("public"),
    )
    assert {node["concept_id"] for node in response["nodes"]} == {
        "concepts/public",
        "concepts/other",
    }
    with pytest.raises(HTTPException) as exc:
        api.graph_node("concepts/internal", _principal("public"))
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "GRAPH-API-404"


def test_openapi_graph_surface_has_only_get_operations() -> None:
    paths = api.app.openapi()["paths"]
    graph_paths = {
        path: operations
        for path, operations in paths.items()
        if path.startswith("/v1/graph")
    }
    assert set(graph_paths) == {
        "/v1/graph/capabilities",
        "/v1/graph/release",
        "/v1/graph/search",
        "/v1/graph/node/{concept_id}",
        "/v1/graph/neighborhood/{concept_id}",
        "/v1/graph/overview",
    }
    assert all(set(operations) == {"get"} for operations in graph_paths.values())
