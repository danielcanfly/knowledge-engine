from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

GRAPH_NAVIGATION_SCHEMA = "knowledge-engine-m24-graph-navigation/v1"
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


class GraphNavigationAuthority(BaseModel):
    graph_authority: Literal["read_only"] = "read_only"
    retrieval_authority: Literal["lexical"] = "lexical"
    production_retrieval: Literal["lexical"] = "lexical"
    semantic_serving_enabled: bool = False
    semantic_promotion_enabled: bool = False
    hybrid_retrieval_enabled: bool = False
    renderer_mutation_authorized: bool = False
    source_mutation_authorized: bool = False


class GraphNavigationNode(BaseModel):
    concept_id: str
    title: str
    description: str
    type: str
    audience: str
    tags: list[str]
    selected: bool
    focus_neighbor: bool


class GraphNavigationEdge(BaseModel):
    edge_id: str
    source: str
    target: str
    relation_type: str
    directed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    generated_inverse: bool
    focus_edge: bool


class GraphNavigationState(BaseModel):
    schema_version: str = GRAPH_NAVIGATION_SCHEMA
    release_id: str
    selected_concept_id: str | None
    nodes: list[GraphNavigationNode]
    edges: list[GraphNavigationEdge]
    focus_neighbor_ids: list[str]
    available_actions: list[Literal["select_node", "open_concept", "open_source_viewer"]]
    overview_truncated: bool
    focus_truncated: bool
    authority: GraphNavigationAuthority


def _compact(value: object, *, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _release_id(payload: dict[str, Any]) -> str:
    release = payload.get("release")
    if not isinstance(release, dict) or not isinstance(release.get("release_id"), str):
        raise ValueError("graph payload must include release identity")
    return release["release_id"]


def _require_read_only_graph(payload: dict[str, Any]) -> None:
    if payload.get("read_only") is not True:
        raise ValueError("graph navigation requires read-only graph payloads")
    for collection_name in ("nodes", "edges"):
        values = payload.get(collection_name)
        if not isinstance(values, list):
            raise ValueError(f"graph payload must include {collection_name}")
        for item in values:
            if not isinstance(item, dict) or RENDERER_FIELDS.intersection(item):
                raise ValueError("graph navigation requires renderer-neutral payloads")


def _node(raw: dict[str, Any], *, selected: str | None, focus_neighbors: set[str]):
    concept_id = _compact(raw.get("concept_id"), maximum=300)
    return GraphNavigationNode(
        concept_id=concept_id,
        title=_compact(raw.get("title"), maximum=200) or concept_id,
        description=_compact(raw.get("description"), maximum=400),
        type=_compact(raw.get("type"), maximum=80),
        audience=_compact(raw.get("audience"), maximum=40),
        tags=[
            _compact(item, maximum=80)
            for item in raw.get("tags", [])
            if isinstance(item, str)
        ][:20],
        selected=concept_id == selected,
        focus_neighbor=concept_id in focus_neighbors,
    )


def _edge(raw: dict[str, Any], *, focus_edges: set[str]) -> GraphNavigationEdge:
    confidence = raw.get("confidence")
    edge_id = _compact(raw.get("edge_id"), maximum=100)
    return GraphNavigationEdge(
        edge_id=edge_id,
        source=_compact(raw.get("source"), maximum=300),
        target=_compact(raw.get("target"), maximum=300),
        relation_type=_compact(raw.get("relation_type"), maximum=80),
        directed=raw.get("directed") is True,
        confidence=(
            float(confidence)
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
            else 0.0
        ),
        generated_inverse=raw.get("generated_inverse") is True,
        focus_edge=edge_id in focus_edges,
    )


def build_graph_navigation_state(
    overview: dict[str, Any],
    *,
    selected_concept_id: str | None = None,
    focus_neighborhood: dict[str, Any] | None = None,
) -> GraphNavigationState:
    _require_read_only_graph(overview)
    release_id = _release_id(overview)
    overview_nodes = {
        item["concept_id"]: item
        for item in overview["nodes"]
        if isinstance(item, dict) and isinstance(item.get("concept_id"), str)
    }
    if selected_concept_id is not None and selected_concept_id not in overview_nodes:
        raise ValueError("selected concept must be visible in the graph overview")

    focus_neighbor_ids: set[str] = set()
    focus_edge_ids: set[str] = set()
    focus_truncated = False
    if focus_neighborhood is not None:
        _require_read_only_graph(focus_neighborhood)
        if _release_id(focus_neighborhood) != release_id:
            raise ValueError("focus neighborhood release identity does not match overview")
        focus_truncated = bool(focus_neighborhood.get("truncated", False))
        root = focus_neighborhood.get("root_concept_id")
        for edge in focus_neighborhood["edges"]:
            if not isinstance(edge, dict):
                continue
            edge_id = edge.get("edge_id")
            source = edge.get("source")
            target = edge.get("target")
            if isinstance(edge_id, str):
                focus_edge_ids.add(edge_id)
            if source == root and isinstance(target, str):
                focus_neighbor_ids.add(target)
            elif target == root and isinstance(source, str):
                focus_neighbor_ids.add(source)

    nodes = [
        _node(raw, selected=selected_concept_id, focus_neighbors=focus_neighbor_ids)
        for _, raw in sorted(overview_nodes.items())
    ]
    visible_node_ids = {item.concept_id for item in nodes}
    edges = [
        _edge(raw, focus_edges=focus_edge_ids)
        for raw in overview["edges"]
        if isinstance(raw, dict)
        and raw.get("source") in visible_node_ids
        and raw.get("target") in visible_node_ids
    ]
    edges.sort(key=lambda item: (item.source, item.target, item.relation_type, item.edge_id))
    return GraphNavigationState(
        release_id=release_id,
        selected_concept_id=selected_concept_id,
        nodes=nodes,
        edges=edges,
        focus_neighbor_ids=sorted(focus_neighbor_ids),
        available_actions=["select_node", "open_concept", "open_source_viewer"],
        overview_truncated=bool(overview.get("truncated", False)),
        focus_truncated=focus_truncated,
        authority=GraphNavigationAuthority(),
    )
