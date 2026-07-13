from __future__ import annotations

import json
from time import monotonic
from typing import Any

from .errors import IntegrityError
from .runtime import ActiveRelease

GRAPH_API_SCHEMA = "knowledge-engine-graph-api/v1"
GRAPH_SCHEMA = "knowledge-os-graph/v2"
KNOWN_AUDIENCES = {"public", "internal", "confidential", "restricted"}
RENDERER_FIELDS = {
    "color",
    "coordinates",
    "hidden",
    "label_color",
    "size",
    "sigma_color",
    "x",
    "y",
}
MAX_SEARCH_RESULTS = 50
MAX_NEIGHBORHOOD_NODES = 100
MAX_NEIGHBORHOOD_EDGES = 200
MAX_OVERVIEW_NODES = 400
MAX_OVERVIEW_EDGES = 800
MAX_RESPONSE_BYTES = 512_000
MAX_EXECUTION_SECONDS = 1.0


class GraphApiNotFoundError(LookupError):
    pass


class GraphApiUnavailableError(RuntimeError):
    pass


class GraphApiRequestError(ValueError):
    pass


class GraphApiLimitError(RuntimeError):
    pass


def _bounded_text(value: Any, *, maximum: int) -> str:
    normalized = " ".join(str(value or "").split())
    return normalized[:maximum]


def _bounded_strings(value: Any, *, count: int, length: int) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise IntegrityError("graph string attributes must be lists of strings")
    return sorted({_bounded_text(item, maximum=length) for item in value if item})[:count]


class ReadOnlyGraphService:
    def __init__(self, active: ActiveRelease, allowed_audiences: set[str]) -> None:
        if not allowed_audiences or not allowed_audiences.issubset(KNOWN_AUDIENCES):
            raise IntegrityError("request has unknown or empty graph audiences")
        self.active = active
        self.allowed_audiences = frozenset(allowed_audiences)
        self.graph = active.graph_v2
        self._all_nodes: dict[str, dict[str, Any]] = {}
        self._all_edges: list[dict[str, Any]] = []
        if self.graph is not None:
            self._validate_graph()

    def _validate_graph(self) -> None:
        assert self.graph is not None
        if self.graph.get("schema_version") != GRAPH_SCHEMA:
            raise IntegrityError("unsupported graph API schema")
        if self.graph.get("renderer_neutral") is not True:
            raise IntegrityError("graph API requires a renderer-neutral graph")
        release = self.graph.get("release")
        if not isinstance(release, dict) or release.get("release_id") != self.active.release_id:
            raise IntegrityError("graph API release identity mismatch")
        nodes = self.graph.get("nodes")
        edges = self.graph.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise IntegrityError("graph API nodes and edges must be lists")
        for node in nodes:
            if not isinstance(node, dict) or RENDERER_FIELDS.intersection(node):
                raise IntegrityError("invalid or renderer-specific graph API node")
            concept_id = node.get("concept_id")
            audience = node.get("audience")
            if not isinstance(concept_id, str) or not concept_id:
                raise IntegrityError("graph API node identity is invalid")
            if audience not in KNOWN_AUDIENCES:
                raise IntegrityError("graph API node audience is invalid")
            if concept_id in self._all_nodes:
                raise IntegrityError("duplicate graph API node identity")
            _bounded_strings(node.get("tags", []), count=20, length=80)
            _bounded_strings(node.get("aliases", []), count=20, length=120)
            self._all_nodes[concept_id] = node
        edge_ids: set[str] = set()
        for edge in edges:
            if not isinstance(edge, dict) or RENDERER_FIELDS.intersection(edge):
                raise IntegrityError("invalid or renderer-specific graph API edge")
            edge_id = edge.get("edge_id")
            source = edge.get("source")
            target = edge.get("target")
            audience = edge.get("audience")
            if not isinstance(edge_id, str) or not edge_id or edge_id in edge_ids:
                raise IntegrityError("duplicate or invalid graph API edge identity")
            if source not in self._all_nodes or target not in self._all_nodes:
                raise IntegrityError("graph API edge endpoint is missing")
            if audience not in KNOWN_AUDIENCES:
                raise IntegrityError("graph API edge audience is invalid")
            edge_ids.add(edge_id)
            self._all_edges.append(edge)
        self._all_edges.sort(key=lambda item: item["edge_id"])

    def _release_identity(self) -> dict[str, Any]:
        identity: dict[str, Any] = {
            "release_id": self.active.release_id,
            "manifest_sha256": self.active.manifest_sha256,
            "loaded_at": self.active.loaded_at,
            "created_at": self.active.manifest.get("created_at"),
        }
        if self.graph is not None:
            release = self.graph["release"]
            identity.update(
                {
                    "source_commit_sha": release.get("source_commit_sha"),
                    "foundation_commit_sha": release.get("foundation_commit_sha"),
                    "content_sha256": release.get("content_sha256"),
                }
            )
        return identity

    def _authorized_nodes(self) -> dict[str, dict[str, Any]]:
        return {
            concept_id: node
            for concept_id, node in self._all_nodes.items()
            if node["audience"] in self.allowed_audiences
        }

    def _authorized_edges(
        self,
        nodes: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            edge
            for edge in self._all_edges
            if edge["audience"] in self.allowed_audiences
            and edge["source"] in nodes
            and edge["target"] in nodes
        ]

    def _node_payload(self, node: dict[str, Any]) -> dict[str, Any]:
        return {
            "concept_id": _bounded_text(node["concept_id"], maximum=300),
            "x_kos_id": _bounded_text(node.get("x_kos_id"), maximum=80),
            "title": _bounded_text(node.get("title"), maximum=200),
            "description": _bounded_text(node.get("description"), maximum=400),
            "type": _bounded_text(node.get("type"), maximum=80),
            "audience": node["audience"],
            "status": _bounded_text(node.get("status"), maximum=40),
            "confidence": float(node.get("confidence", 0.0)),
            "tags": _bounded_strings(node.get("tags", []), count=20, length=80),
            "aliases": _bounded_strings(node.get("aliases", []), count=20, length=120),
            "source_path": _bounded_text(node.get("path"), maximum=300),
        }

    def _edge_payload(self, edge: dict[str, Any]) -> dict[str, Any]:
        return {
            "edge_id": _bounded_text(edge["edge_id"], maximum=100),
            "source": _bounded_text(edge["source"], maximum=300),
            "target": _bounded_text(edge["target"], maximum=300),
            "relation_type": _bounded_text(edge.get("relation_type"), maximum=80),
            "directed": edge.get("directed") is True,
            "audience": edge["audience"],
            "confidence": float(edge.get("confidence", 0.0)),
            "generated_inverse": edge.get("generated_inverse") is True,
        }

    def _base(self) -> dict[str, Any]:
        return {
            "schema_version": GRAPH_API_SCHEMA,
            "release": self._release_identity(),
            "read_only": True,
        }

    def _finish(self, payload: dict[str, Any], started: float) -> dict[str, Any]:
        payload["response_bytes"] = 0
        payload["response_limit_bytes"] = MAX_RESPONSE_BYTES
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payload["response_bytes"] = len(encoded)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payload["response_bytes"] = len(encoded)
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise GraphApiLimitError("graph API response exceeds the byte limit")
        if monotonic() - started > MAX_EXECUTION_SECONDS:
            raise GraphApiLimitError("graph API execution exceeds the time limit")
        return payload

    def capabilities(self) -> dict[str, Any]:
        started = monotonic()
        payload = {
            **self._base(),
            "graph_v2_available": self.graph is not None,
            "mutation_methods": [],
            "maximum_depth": 1,
            "maximum_search_results": MAX_SEARCH_RESULTS,
            "maximum_neighborhood_nodes": MAX_NEIGHBORHOOD_NODES,
            "maximum_neighborhood_edges": MAX_NEIGHBORHOOD_EDGES,
            "maximum_overview_nodes": MAX_OVERVIEW_NODES,
            "maximum_overview_edges": MAX_OVERVIEW_EDGES,
            "maximum_execution_seconds": MAX_EXECUTION_SECONDS,
            "cluster_levels": ["none"],
        }
        return self._finish(payload, started)

    def release(self) -> dict[str, Any]:
        started = monotonic()
        nodes = self._authorized_nodes()
        edges = self._authorized_edges(nodes)
        payload = {
            **self._base(),
            "graph_v2_available": self.graph is not None,
            "authorized_node_count": len(nodes),
            "authorized_edge_count": len(edges),
        }
        return self._finish(payload, started)

    def _require_graph(self) -> None:
        if self.graph is None:
            raise GraphApiUnavailableError("current release has no graph v2 capability")

    def search(
        self,
        *,
        query: str,
        tags: list[str],
        types: list[str],
        limit: int,
    ) -> dict[str, Any]:
        started = monotonic()
        self._require_graph()
        normalized_query = _bounded_text(query, maximum=200).casefold()
        if not normalized_query:
            raise GraphApiRequestError("graph search query is required")
        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise GraphApiRequestError("graph search limit is out of bounds")
        if len(tags) > 10 or len(types) > 10:
            raise GraphApiRequestError("graph search filters are out of bounds")
        tag_filter = {_bounded_text(value, maximum=80) for value in tags if value}
        type_filter = {_bounded_text(value, maximum=80) for value in types if value}
        matches: list[tuple[int, str, dict[str, Any]]] = []
        for concept_id, node in self._authorized_nodes().items():
            node_tags = set(node.get("tags", []))
            if tag_filter and not tag_filter.issubset(node_tags):
                continue
            if type_filter and node.get("type") not in type_filter:
                continue
            fields = [
                concept_id,
                str(node.get("title", "")),
                str(node.get("description", "")),
                *node.get("aliases", []),
                *node.get("tags", []),
            ]
            normalized_fields = [" ".join(value.casefold().split()) for value in fields]
            if not any(normalized_query in value for value in normalized_fields):
                continue
            score = 0
            if normalized_query == normalized_fields[0]:
                score += 100
            if normalized_query == normalized_fields[1]:
                score += 80
            score += sum(normalized_query in value for value in normalized_fields)
            matches.append((-score, concept_id, node))
        matches.sort(key=lambda item: (item[0], item[1]))
        selected = [self._node_payload(item[2]) for item in matches[:limit]]
        payload = {
            **self._base(),
            "query": normalized_query,
            "tags": sorted(tag_filter),
            "types": sorted(type_filter),
            "nodes": selected,
            "result_count": len(selected),
            "truncated": len(matches) > limit,
        }
        return self._finish(payload, started)

    def node(self, concept_id: str) -> dict[str, Any]:
        started = monotonic()
        self._require_graph()
        node = self._authorized_nodes().get(concept_id)
        if node is None:
            raise GraphApiNotFoundError("authorized graph node was not found")
        payload = {**self._base(), "node": self._node_payload(node)}
        return self._finish(payload, started)

    def neighborhood(
        self,
        concept_id: str,
        *,
        depth: int,
        relation_types: list[str],
        max_nodes: int,
        max_edges: int,
    ) -> dict[str, Any]:
        started = monotonic()
        self._require_graph()
        if depth != 1:
            raise GraphApiRequestError("graph neighborhood depth must be exactly one")
        if not 1 <= max_nodes <= MAX_NEIGHBORHOOD_NODES:
            raise GraphApiRequestError("graph neighborhood node limit is out of bounds")
        if not 1 <= max_edges <= MAX_NEIGHBORHOOD_EDGES:
            raise GraphApiRequestError("graph neighborhood edge limit is out of bounds")
        if len(relation_types) > 10:
            raise GraphApiRequestError("relation type filters are out of bounds")
        nodes = self._authorized_nodes()
        if concept_id not in nodes:
            raise GraphApiNotFoundError("authorized graph node was not found")
        relation_filter = {
            _bounded_text(value, maximum=80) for value in relation_types if value
        }
        incident = [
            edge
            for edge in self._authorized_edges(nodes)
            if concept_id in {edge["source"], edge["target"]}
            and (not relation_filter or edge["relation_type"] in relation_filter)
        ]
        selected_ids = {concept_id}
        selected_edges: list[dict[str, Any]] = []
        for edge in incident:
            neighbor = edge["target"] if edge["source"] == concept_id else edge["source"]
            if neighbor not in selected_ids and len(selected_ids) >= max_nodes:
                continue
            selected_ids.add(neighbor)
            selected_edges.append(edge)
            if len(selected_edges) >= max_edges:
                break
        payload = {
            **self._base(),
            "root_concept_id": concept_id,
            "depth": 1,
            "relation_types": sorted(relation_filter),
            "nodes": [self._node_payload(nodes[item]) for item in sorted(selected_ids)],
            "edges": [self._edge_payload(edge) for edge in selected_edges],
            "node_count": len(selected_ids),
            "edge_count": len(selected_edges),
            "truncated": len(selected_edges) < len(incident),
        }
        return self._finish(payload, started)

    def overview(
        self,
        *,
        cluster_level: str,
        max_nodes: int,
        max_edges: int,
    ) -> dict[str, Any]:
        started = monotonic()
        self._require_graph()
        if cluster_level != "none":
            raise GraphApiRequestError("only the renderer-neutral 'none' cluster level exists")
        if not 1 <= max_nodes <= MAX_OVERVIEW_NODES:
            raise GraphApiRequestError("graph overview node limit is out of bounds")
        if not 1 <= max_edges <= MAX_OVERVIEW_EDGES:
            raise GraphApiRequestError("graph overview edge limit is out of bounds")
        authorized_nodes = self._authorized_nodes()
        selected_ids = sorted(authorized_nodes)[:max_nodes]
        selected_nodes = {item: authorized_nodes[item] for item in selected_ids}
        authorized_edges = self._authorized_edges(authorized_nodes)
        selected_edges = [
            edge
            for edge in authorized_edges
            if edge["source"] in selected_nodes and edge["target"] in selected_nodes
        ][:max_edges]
        payload = {
            **self._base(),
            "cluster_level": "none",
            "nodes": [self._node_payload(selected_nodes[item]) for item in selected_ids],
            "edges": [self._edge_payload(edge) for edge in selected_edges],
            "node_count": len(selected_nodes),
            "edge_count": len(selected_edges),
            "truncated": len(authorized_nodes) > len(selected_nodes)
            or len(authorized_edges) > len(selected_edges),
        }
        return self._finish(payload, started)
