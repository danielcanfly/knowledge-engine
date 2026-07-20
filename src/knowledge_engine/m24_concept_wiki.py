from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .m14_public_contracts import PublicSearchResponse, PublicSourceViewer

CONCEPT_WIKI_SCHEMA = "knowledge-engine-m24-concept-wiki/v1"


class ConceptWikiAuthority(BaseModel):
    retrieval_authority: Literal["lexical"] = "lexical"
    graph_authority: Literal["read_only"] = "read_only"
    production_retrieval: Literal["lexical"] = "lexical"
    semantic_serving_enabled: bool = False
    semantic_promotion_enabled: bool = False
    hybrid_retrieval_enabled: bool = False
    source_mutation_authorized: bool = False
    raw_evidence_exposed: bool = False


class ConceptWikiSection(BaseModel):
    section_id: str
    title: str
    excerpt: str
    rank: int = Field(ge=1)
    score: float | None
    source_card_ids: list[str]
    source_viewer_ids: list[str]


class ConceptWikiRelationship(BaseModel):
    edge_id: str
    relation_type: str
    direction: Literal["outbound", "inbound", "undirected"]
    neighbor_concept_id: str
    neighbor_title: str
    confidence: float = Field(ge=0.0, le=1.0)
    generated_inverse: bool


class ConceptWikiPage(BaseModel):
    schema_version: str = CONCEPT_WIKI_SCHEMA
    release_id: str
    request_id: str
    concept_id: str
    title: str
    description: str | None
    sections: list[ConceptWikiSection]
    relationships: list[ConceptWikiRelationship]
    source_viewers: list[PublicSourceViewer]
    relationship_truncated: bool
    authority: ConceptWikiAuthority


def _compact(value: object, *, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _node_title(node: dict[str, Any] | None, concept_id: str) -> str:
    if not isinstance(node, dict):
        return concept_id
    title = _compact(node.get("title"), maximum=200)
    return title or concept_id


def _graph_release_id(neighborhood: dict[str, Any]) -> str | None:
    release = neighborhood.get("release")
    if not isinstance(release, dict):
        return None
    value = release.get("release_id")
    return value if isinstance(value, str) else None


def _relationships(
    *,
    concept_id: str,
    neighborhood: dict[str, Any] | None,
) -> tuple[list[ConceptWikiRelationship], bool, str | None, str | None]:
    if neighborhood is None:
        return [], False, None, None
    nodes_raw = neighborhood.get("nodes")
    edges_raw = neighborhood.get("edges")
    if not isinstance(nodes_raw, list) or not isinstance(edges_raw, list):
        raise ValueError("graph neighborhood must include nodes and edges")
    nodes = {
        item["concept_id"]: item
        for item in nodes_raw
        if isinstance(item, dict) and isinstance(item.get("concept_id"), str)
    }
    root = nodes.get(concept_id)
    root_title = _node_title(root, concept_id) if root is not None else None
    root_description = (
        _compact(root.get("description"), maximum=400) if isinstance(root, dict) else None
    )
    output: list[ConceptWikiRelationship] = []
    for edge in edges_raw:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source")
        target = edge.get("target")
        if source != concept_id and target != concept_id:
            continue
        neighbor_id = target if source == concept_id else source
        if not isinstance(neighbor_id, str):
            continue
        neighbor = nodes.get(neighbor_id)
        if neighbor is None:
            continue
        directed = edge.get("directed") is True
        if not directed:
            direction: Literal["outbound", "inbound", "undirected"] = "undirected"
        elif source == concept_id:
            direction = "outbound"
        else:
            direction = "inbound"
        confidence = edge.get("confidence")
        output.append(
            ConceptWikiRelationship(
                edge_id=_compact(edge.get("edge_id"), maximum=100),
                relation_type=_compact(edge.get("relation_type"), maximum=80),
                direction=direction,
                neighbor_concept_id=neighbor_id,
                neighbor_title=_node_title(neighbor, neighbor_id),
                confidence=(
                    float(confidence)
                    if isinstance(confidence, (int, float))
                    and not isinstance(confidence, bool)
                    else 0.0
                ),
                generated_inverse=edge.get("generated_inverse") is True,
            )
        )
    output.sort(
        key=lambda item: (
            item.direction,
            item.relation_type,
            item.neighbor_title.casefold(),
            item.edge_id,
        )
    )
    truncated = bool(neighborhood.get("truncated", False))
    return output[:20], truncated or len(output) > 20, root_title, root_description


def build_concept_wiki_page(
    response: PublicSearchResponse,
    *,
    concept_id: str,
    graph_neighborhood: dict[str, Any] | None = None,
) -> ConceptWikiPage:
    if graph_neighborhood is not None and _graph_release_id(graph_neighborhood) not in {
        None,
        response.release_id,
    }:
        raise ValueError("graph neighborhood release identity does not match search response")

    results = [item for item in response.results if item.concept_id == concept_id]
    if not results:
        raise ValueError("concept is not present in the public search response")

    viewer_by_card = {
        viewer.source_card.source_card_id: viewer for viewer in response.source_viewers
    }
    used_viewer_ids: set[str] = set()
    sections: list[ConceptWikiSection] = []
    for result in results:
        viewer_ids = [
            viewer_by_card[card_id].viewer_id
            for card_id in result.source_card_ids
            if card_id in viewer_by_card
        ]
        used_viewer_ids.update(viewer_ids)
        sections.append(
            ConceptWikiSection(
                section_id=result.section_id,
                title=result.section_title,
                excerpt=result.excerpt,
                rank=result.rank,
                score=result.score,
                source_card_ids=result.source_card_ids,
                source_viewer_ids=viewer_ids,
            )
        )

    relationships, truncated, graph_title, graph_description = _relationships(
        concept_id=concept_id,
        neighborhood=graph_neighborhood,
    )
    title = graph_title or results[0].title
    source_viewers = [
        viewer for viewer in response.source_viewers if viewer.viewer_id in used_viewer_ids
    ]
    return ConceptWikiPage(
        release_id=response.release_id,
        request_id=response.request_id,
        concept_id=concept_id,
        title=title,
        description=graph_description,
        sections=sections,
        relationships=relationships,
        source_viewers=source_viewers,
        relationship_truncated=truncated,
        authority=ConceptWikiAuthority(),
    )
