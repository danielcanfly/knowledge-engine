from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .errors import IntegrityError

AUDIENCE_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")
SEMANTIC_SCHEMA = "knowledge-engine-semantic-index/v1"
RELATION_GRAPH_SCHEMA = "knowledge-os-graph/v2"
MAX_RELATION_NEIGHBORS_PER_SEED = 20
RENDERER_FIELDS = {
    "color",
    "coordinates",
    "hidden",
    "label_color",
    "sigma_color",
    "size",
    "x",
    "y",
}


def _tokens(value: str) -> list[str]:
    return [item.lower() for item in TOKEN_RE.findall(value)]


def _term_score(query_terms: list[str], value: str, weight: int) -> int:
    counts = Counter(_tokens(value))
    return weight * sum(counts[term] for term in query_terms)


def _citation_uri(source: dict[str, Any]) -> str:
    uri = source.get("uri") or source.get("locator")
    if not isinstance(uri, str) or not uri:
        raise IntegrityError(
            "provenance source is missing uri: "
            f"{source.get('source_id', 'unknown')}"
        )
    return uri


def _allowed_rank(allowed_audiences: set[str]) -> tuple[set[str], int]:
    allowed = {item for item in allowed_audiences if item in AUDIENCE_RANK}
    if not allowed:
        allowed = {"public"}
    return allowed, max(AUDIENCE_RANK[item] for item in allowed)


def _normalize_document(
    document: dict[str, Any],
    *,
    node_audiences: dict[str, str],
) -> dict[str, Any]:
    concept_id = document.get("concept_id")
    if not isinstance(concept_id, str) or not concept_id:
        raise IntegrityError("lexical document is missing concept_id")
    audience = document.get("audience") or node_audiences.get(concept_id)
    if audience not in AUDIENCE_RANK:
        raise IntegrityError(f"lexical document has invalid audience: {concept_id}")
    title = str(document.get("title") or concept_id)
    description = str(document.get("description") or "")
    section_id = str(document.get("section_id") or f"{concept_id}#overview")
    section_title = str(document.get("section_title") or title)
    body = str(document.get("body") or document.get("excerpt") or description)
    excerpt = str(document.get("excerpt") or body[:320] or description)
    terms = document.get("terms")
    if not isinstance(terms, list) or not all(isinstance(item, str) for item in terms):
        terms = _tokens(" ".join((title, section_title, description, body)))
    return {
        **document,
        "concept_id": concept_id,
        "audience": audience,
        "title": title,
        "description": description,
        "section_id": section_id,
        "section_title": section_title,
        "body": body,
        "excerpt": excerpt,
        "terms": terms,
    }


def _semantic_boosts(
    semantic_index: dict[str, Any] | None,
    *,
    query_terms: list[str],
) -> tuple[dict[str, int], bool]:
    if semantic_index is None:
        return {}, False
    if semantic_index.get("schema_version") != SEMANTIC_SCHEMA:
        return {}, False
    documents = semantic_index.get("documents")
    if not isinstance(documents, list):
        raise IntegrityError("semantic index documents must be a list")
    boosts: dict[str, int] = {}
    query_set = set(query_terms)
    for document in documents:
        if not isinstance(document, dict):
            raise IntegrityError("semantic document must be an object")
        identity = document.get("section_id") or document.get("concept_id")
        if not isinstance(identity, str) or not identity:
            raise IntegrityError("semantic document identity is missing")
        terms = document.get("terms") or document.get("keywords") or []
        if not isinstance(terms, list) or not all(isinstance(item, str) for item in terms):
            raise IntegrityError("semantic document terms must be strings")
        overlap = len(query_set & {item.lower() for item in terms})
        if overlap:
            boosts[identity] = 2 * overlap
    return boosts, True


def _graph_adjacency(
    graph: dict[str, Any],
) -> tuple[dict[str, set[str]], dict[str, str]]:
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise IntegrityError("graph nodes and edges must be lists")
    audiences: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            raise IntegrityError("graph node must be an object")
        concept_id = node.get("concept_id")
        audience = node.get("audience")
        if not isinstance(concept_id, str) or audience not in AUDIENCE_RANK:
            raise IntegrityError("graph node identity or audience is invalid")
        audiences[concept_id] = str(audience)
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if not isinstance(edge, dict):
            raise IntegrityError("graph edge must be an object")
        source = edge.get("from_concept_id") or edge.get("source")
        target = edge.get("to_concept_id") or edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            raise IntegrityError("graph edge endpoints are invalid")
        adjacency[source].add(target)
        adjacency[target].add(source)
    return adjacency, audiences


def validate_relation_graph_v2(
    graph: dict[str, Any],
    *,
    expected_release_id: str | None = None,
    compatibility_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the renderer-neutral typed graph before Runtime activation."""
    if graph.get("schema_version") != RELATION_GRAPH_SCHEMA:
        raise IntegrityError("graph v2 schema is incompatible")
    if graph.get("renderer_neutral") is not True:
        raise IntegrityError("graph v2 must be renderer neutral")
    release = graph.get("release")
    if not isinstance(release, dict):
        raise IntegrityError("graph v2 release identity is missing")
    release_id = release.get("release_id")
    if not isinstance(release_id, str) or not release_id:
        raise IntegrityError("graph v2 release ID is missing")
    if expected_release_id is not None and release_id != expected_release_id:
        raise IntegrityError("graph v2 release ID does not match the manifest")

    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise IntegrityError("graph v2 nodes and edges must be lists")
    node_audiences: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict) or RENDERER_FIELDS.intersection(node):
            raise IntegrityError("graph v2 node is invalid or renderer-specific")
        concept_id = node.get("concept_id")
        audience = node.get("audience")
        if not isinstance(concept_id, str) or not concept_id:
            raise IntegrityError("graph v2 node identity is invalid")
        if concept_id in node_audiences:
            raise IntegrityError(f"duplicate graph v2 node: {concept_id}")
        if audience not in AUDIENCE_RANK:
            raise IntegrityError(f"graph v2 node audience is invalid: {concept_id}")
        node_audiences[concept_id] = str(audience)

    if compatibility_graph is not None:
        compatibility_nodes = compatibility_graph.get("nodes")
        if not isinstance(compatibility_nodes, list):
            raise IntegrityError("compatibility graph nodes must be a list")
        compatibility_audiences: dict[str, str] = {}
        for node in compatibility_nodes:
            if not isinstance(node, dict):
                raise IntegrityError("compatibility graph node must be an object")
            concept_id = node.get("concept_id")
            audience = node.get("audience")
            if not isinstance(concept_id, str) or audience not in AUDIENCE_RANK:
                raise IntegrityError("compatibility graph node identity or audience is invalid")
            if concept_id in compatibility_audiences:
                raise IntegrityError(f"duplicate compatibility graph node: {concept_id}")
            compatibility_audiences[concept_id] = str(audience)
        if compatibility_audiences != node_audiences:
            raise IntegrityError("graph v2 node identities or audiences mismatch graph v1")

    edge_ids: set[str] = set()
    relation_types: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict) or RENDERER_FIELDS.intersection(edge):
            raise IntegrityError("graph v2 edge is invalid or renderer-specific")
        edge_id = edge.get("edge_id")
        source = edge.get("source")
        target = edge.get("target")
        relation_type = edge.get("relation_type")
        audience = edge.get("audience")
        if not isinstance(edge_id, str) or not edge_id or edge_id in edge_ids:
            raise IntegrityError("graph v2 edge identity is invalid or duplicated")
        if source not in node_audiences or target not in node_audiences:
            raise IntegrityError(f"graph v2 edge endpoint is missing: {edge_id}")
        if not isinstance(relation_type, str) or not relation_type:
            raise IntegrityError(f"graph v2 relation type is invalid: {edge_id}")
        if audience not in AUDIENCE_RANK:
            raise IntegrityError(f"graph v2 edge audience is invalid: {edge_id}")
        endpoint_audience = max(
            (node_audiences[str(source)], node_audiences[str(target)]),
            key=AUDIENCE_RANK.__getitem__,
        )
        if audience != endpoint_audience:
            raise IntegrityError(f"graph v2 edge audience mismatch: {edge_id}")
        if not isinstance(edge.get("directed"), bool):
            raise IntegrityError(f"graph v2 edge direction is invalid: {edge_id}")
        if not isinstance(edge.get("generated_inverse"), bool):
            raise IntegrityError(f"graph v2 inverse marker is invalid: {edge_id}")
        if edge.get("review_status") != "approved":
            raise IntegrityError(f"graph v2 relation is not approved: {edge_id}")
        confidence = edge.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise IntegrityError(f"graph v2 edge confidence is invalid: {edge_id}")
        if not 0 <= float(confidence) <= 1:
            raise IntegrityError(f"graph v2 edge confidence is invalid: {edge_id}")
        edge_ids.add(edge_id)
        relation_types.add(relation_type)
    return {
        "node_audiences": node_audiences,
        "edge_count": len(edge_ids),
        "relation_types": sorted(relation_types),
    }


def _relation_adjacency(
    graph: dict[str, Any] | None,
    *,
    compatibility_graph: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    if graph is None:
        return {}, {"edge_count": 0, "relation_types": []}
    metadata = validate_relation_graph_v2(
        graph,
        compatibility_graph=compatibility_graph,
    )
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph["edges"]:
        adjacency[edge["source"]].append(edge)
        if not edge["directed"]:
            reverse = dict(edge)
            reverse["source"], reverse["target"] = edge["target"], edge["source"]
            adjacency[reverse["source"]].append(reverse)
    for source, values in adjacency.items():
        adjacency[source] = sorted(
            values,
            key=lambda item: (
                item["target"],
                item["relation_type"],
                item["edge_id"],
            ),
        )
    return adjacency, metadata


def _relation_evidence(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_id": edge["edge_id"],
        "source": edge["source"],
        "target": edge["target"],
        "relation_type": edge["relation_type"],
        "directed": edge["directed"],
        "generated_inverse": edge["generated_inverse"],
        "confidence": edge["confidence"],
        "review_id": edge.get("review_id"),
        "provenance_record": edge.get("provenance_record"),
        "provenance_ref": edge.get("provenance_ref"),
    }


def _score_document(
    document: dict[str, Any],
    *,
    query_terms: list[str],
    semantic_boosts: dict[str, int],
) -> dict[str, Any] | None:
    title_score = _term_score(query_terms, document["title"], 4)
    section_title_score = _term_score(
        query_terms,
        document["section_title"],
        3,
    )
    description_score = _term_score(
        query_terms,
        document["description"],
        2,
    )
    body_score = _term_score(query_terms, document["body"], 1)
    explicit_score = title_score + section_title_score + description_score + body_score
    legacy_score = 0
    if explicit_score == 0:
        term_counts = Counter(item.lower() for item in document["terms"])
        legacy_score = sum(term_counts[term] for term in query_terms)
    semantic_score = semantic_boosts.get(
        document["section_id"],
        semantic_boosts.get(document["concept_id"], 0),
    )
    lexical_score = explicit_score or legacy_score
    total = lexical_score + semantic_score
    if total <= 0:
        return None
    return {
        "document": document,
        "score_components": {
            "concept_title": title_score,
            "section_title": section_title_score,
            "description": description_score,
            "body": body_score,
            "legacy_terms": legacy_score,
            "semantic": semantic_score,
            "graph": 0,
            "relation_graph": 0,
        },
        "score": total,
        "expanded_from": [],
        "relation_expansions": [],
    }


def _ordered(items: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items.values(),
        key=lambda item: (
            -item["score"],
            item["document"]["concept_id"],
            item["document"]["section_id"],
        ),
    )


def retrieve_wiki_first(
    *,
    query: str,
    allowed_audiences: set[str],
    lexical_index: dict[str, Any],
    graph: dict[str, Any],
    relation_graph: dict[str, Any] | None = None,
    relation_aware_expansion: bool = False,
    provenance: dict[str, Any],
    semantic_index: dict[str, Any] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("query must not be empty")
    if limit < 1 or limit > 20:
        raise ValueError("limit must be between 1 and 20")
    _, maximum_rank = _allowed_rank(allowed_audiences)
    query_terms = _tokens(query)
    adjacency, node_audiences = _graph_adjacency(graph)
    relation_adjacency, relation_metadata = _relation_adjacency(
        relation_graph,
        compatibility_graph=graph,
    )
    records = {
        record["subject"]["concept_id"]: record
        for record in provenance.get("records", [])
        if isinstance(record, dict)
        and isinstance(record.get("subject"), dict)
        and isinstance(record["subject"].get("concept_id"), str)
    }
    documents = lexical_index.get("documents")
    if not isinstance(documents, list):
        raise IntegrityError("lexical index documents must be a list")
    semantic_boosts, semantic_available = _semantic_boosts(
        semantic_index,
        query_terms=query_terms,
    )

    normalized: list[dict[str, Any]] = []
    filtered_concepts: set[str] = set()
    filtered_sections = 0
    for raw_document in documents:
        if not isinstance(raw_document, dict):
            raise IntegrityError("lexical document must be an object")
        document = _normalize_document(
            raw_document,
            node_audiences=node_audiences,
        )
        if AUDIENCE_RANK[document["audience"]] > maximum_rank:
            filtered_concepts.add(document["concept_id"])
            filtered_sections += 1
            continue
        normalized.append(document)

    scored: dict[str, dict[str, Any]] = {}
    for document in normalized:
        item = _score_document(
            document,
            query_terms=query_terms,
            semantic_boosts=semantic_boosts,
        )
        if item is not None:
            scored[document["section_id"]] = item

    ordered_seeds = _ordered(scored)
    seed_concepts: list[str] = []
    for item in ordered_seeds:
        concept_id = item["document"]["concept_id"]
        if concept_id not in seed_concepts:
            seed_concepts.append(concept_id)
        if len(seed_concepts) >= min(limit, 5):
            break

    documents_by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in normalized:
        documents_by_concept[document["concept_id"]].append(document)
    graph_expanded_concepts: set[str] = set()
    for seed in seed_concepts:
        for neighbor in sorted(adjacency.get(seed, set())):
            audience = node_audiences.get(neighbor)
            if audience not in AUDIENCE_RANK:
                continue
            if AUDIENCE_RANK[audience] > maximum_rank:
                filtered_concepts.add(neighbor)
                continue
            candidates = sorted(
                documents_by_concept.get(neighbor, []),
                key=lambda item: item["section_id"],
            )
            if not candidates:
                continue
            existing = [
                item
                for item in scored.values()
                if item["document"]["concept_id"] == neighbor
            ]
            if existing:
                best = sorted(
                    existing,
                    key=lambda item: (
                        -item["score"],
                        item["document"]["section_id"],
                    ),
                )[0]
                best["score_components"]["graph"] += 1
                best["score"] += 1
                best["expanded_from"].append(seed)
                continue
            document = candidates[0]
            scored[document["section_id"]] = {
                "document": document,
                "score_components": {
                    "concept_title": 0,
                    "section_title": 0,
                    "description": 0,
                    "body": 0,
                    "legacy_terms": 0,
                    "semantic": 0,
                    "graph": 1,
                    "relation_graph": 0,
                },
                "score": 1,
                "expanded_from": [seed],
                "relation_expansions": [],
            }
            graph_expanded_concepts.add(neighbor)

    relation_expanded_concepts: set[str] = set()
    relation_neighbors_truncated = False
    relation_types_used: set[str] = set()
    if relation_aware_expansion:
        for seed in seed_concepts:
            neighbors = relation_adjacency.get(seed, [])
            if len(neighbors) > MAX_RELATION_NEIGHBORS_PER_SEED:
                relation_neighbors_truncated = True
            for edge in neighbors[:MAX_RELATION_NEIGHBORS_PER_SEED]:
                neighbor = edge["target"]
                audience = node_audiences.get(neighbor)
                edge_audience = edge["audience"]
                if audience not in AUDIENCE_RANK:
                    raise IntegrityError(
                        f"relation graph node is absent from compatibility graph: {neighbor}"
                    )
                if (
                    AUDIENCE_RANK[audience] > maximum_rank
                    or AUDIENCE_RANK[edge_audience] > maximum_rank
                ):
                    filtered_concepts.add(neighbor)
                    continue
                candidates = sorted(
                    documents_by_concept.get(neighbor, []),
                    key=lambda item: item["section_id"],
                )
                if not candidates:
                    continue
                evidence = _relation_evidence(edge)
                existing = [
                    item
                    for item in scored.values()
                    if item["document"]["concept_id"] == neighbor
                ]
                if existing:
                    best = sorted(
                        existing,
                        key=lambda item: (
                            -item["score"],
                            item["document"]["section_id"],
                        ),
                    )[0]
                    best["score_components"]["relation_graph"] += 1
                    best["score"] += 1
                    best["expanded_from"].append(seed)
                    best["relation_expansions"].append(evidence)
                else:
                    document = candidates[0]
                    scored[document["section_id"]] = {
                        "document": document,
                        "score_components": {
                            "concept_title": 0,
                            "section_title": 0,
                            "description": 0,
                            "body": 0,
                            "legacy_terms": 0,
                            "semantic": 0,
                            "graph": 0,
                            "relation_graph": 1,
                        },
                        "score": 1,
                        "expanded_from": [seed],
                        "relation_expansions": [evidence],
                    }
                    relation_expanded_concepts.add(neighbor)
                relation_types_used.add(edge["relation_type"])

    results: list[dict[str, Any]] = []
    selected_concepts: set[str] = set()
    for item in _ordered(scored):
        document = item["document"]
        concept_id = document["concept_id"]
        if concept_id in selected_concepts:
            continue
        record = records.get(concept_id, {})
        citations = []
        for source in record.get("sources", []):
            if not isinstance(source, dict):
                raise IntegrityError("provenance source must be an object")
            citations.append(
                {
                    "source_id": source["source_id"],
                    "uri": _citation_uri(source),
                    "retrieved_at": source["retrieved_at"],
                    "concept_id": concept_id,
                    "section_id": document["section_id"],
                }
            )
        results.append(
            {
                "concept_id": concept_id,
                "section_id": document["section_id"],
                "x_kos_id": document.get("x_kos_id"),
                "title": document["title"],
                "section_title": document["section_title"],
                "description": document["description"],
                "excerpt": document["excerpt"],
                "audience": document["audience"],
                "score": item["score"],
                "score_components": item["score_components"],
                "expanded_from": sorted(set(item["expanded_from"])),
                "relation_expansions": sorted(
                    {
                        (
                            value["edge_id"],
                            value["source"],
                            value["target"],
                        ): value
                        for value in item["relation_expansions"]
                    }.values(),
                    key=lambda value: (
                        value["source"],
                        value["target"],
                        value["relation_type"],
                        value["edge_id"],
                    ),
                ),
                "citations": citations,
            }
        )
        selected_concepts.add(concept_id)
        if len(results) >= limit:
            break

    candidate_concepts = {
        item["document"]["concept_id"] for item in scored.values()
    }
    semantic_used = any(
        result["score_components"]["semantic"] > 0 for result in results
    )
    graph_used = any(result["score_components"]["graph"] > 0 for result in results)
    relation_aware_expansion_used = any(
        result["score_components"]["relation_graph"] > 0 for result in results
    )
    status = "answered" if results else "not_found"
    not_found_reason = None
    if not results:
        not_found_reason = (
            "no_authorized_match" if filtered_concepts else "no_match"
        )
    return {
        "status": status,
        "results": results,
        "retrieval": {
            "strategy": "wiki_first",
            "stages": [
                "section_lexical",
                "semantic_optional",
                "graph_expansion",
                "relation_aware_optional",
                "authorized_selection",
            ],
            "query_term_count": len(query_terms),
            "section_document_count": len(normalized),
            "section_candidate_count": len(scored),
            "candidate_count": len(candidate_concepts),
            "selected_count": len(results),
            "acl_filtered_count": len(filtered_concepts),
            "acl_filtered_section_count": filtered_sections,
            "semantic_available": semantic_available,
            "semantic_used": semantic_used,
            "graph_seed_count": len(seed_concepts),
            "graph_expanded_count": len(graph_expanded_concepts),
            "graph_used": graph_used,
            "relation_graph_available": relation_graph is not None,
            "relation_graph_edge_count": relation_metadata["edge_count"],
            "relation_aware_expansion_enabled": relation_aware_expansion,
            "relation_aware_expansion_used": relation_aware_expansion_used,
            "relation_expanded_count": len(relation_expanded_concepts),
            "relation_types_used": sorted(relation_types_used),
            "relation_neighbors_per_seed_limit": MAX_RELATION_NEIGHBORS_PER_SEED,
            "relation_neighbors_truncated": relation_neighbors_truncated,
            "raw_fallback_allowed": False,
            "raw_fallback_used": False,
            "raw_fallback_reason": "disabled_by_governance",
        },
        "not_found_reason": not_found_reason,
    }
