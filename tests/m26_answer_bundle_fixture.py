from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from knowledge_engine.m26_production_answer_bundle import (
    FULL_PRODUCTION_ADMISSION_SHA256,
    FULL_PRODUCTION_EDGE_COUNT,
    FULL_PRODUCTION_GRAPH_V2_SHA256,
    FULL_PRODUCTION_NODE_COUNT,
    FULL_PRODUCTION_RELEASE_ID,
    FULL_PRODUCTION_SOURCE_SHA,
    ProductionAnswerBundle,
)
from knowledge_engine.storage import sha256_bytes


def _digest(value: dict[str, Any]) -> str:
    return sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


@lru_cache(maxsize=1)
def synthetic_full_production_answer_bundle() -> ProductionAnswerBundle:
    nodes = [
        {
            "concept_id": f"concepts/prod-{index:04d}",
            "title": _title(index),
            "type": "Concept",
            "audience": "internal",
            "tags": ["answer-quality-fixture"],
        }
        for index in range(FULL_PRODUCTION_NODE_COUNT)
    ]
    edges = _edges()
    graph = {
        "schema_version": "knowledge-engine-graph/v1",
        "release_id": FULL_PRODUCTION_RELEASE_ID,
        "nodes": nodes,
        "edges": [
            {
                "edge_id": edge["edge_id"],
                "source": edge["source"],
                "target": edge["target"],
                "from_concept_id": edge["source"],
                "to_concept_id": edge["target"],
                "relation_type": edge["relation_type"],
                "audience": "internal",
            }
            for edge in edges
        ],
    }
    graph_v2 = {
        "schema_version": "knowledge-os-graph/v2",
        "renderer_neutral": True,
        "release": {"release_id": FULL_PRODUCTION_RELEASE_ID},
        "nodes": nodes,
        "edges": edges,
    }
    lexical_documents = [_document(index) for index in range(FULL_PRODUCTION_NODE_COUNT)]
    lexical_index = {
        "schema_version": "knowledge-engine-lexical-index/v1",
        "release_id": FULL_PRODUCTION_RELEASE_ID,
        "documents": lexical_documents,
    }
    provenance = {
        "schema_version": "knowledge-engine-provenance/v1",
        "release_id": FULL_PRODUCTION_RELEASE_ID,
        "records": [_provenance_record(index) for index in range(FULL_PRODUCTION_NODE_COUNT)],
    }
    semantic_inputs = {
        "schema_version": "knowledge-engine-semantic-inputs/v1",
        "release_id": FULL_PRODUCTION_RELEASE_ID,
        "documents": [
            {
                "section_id": document["section_id"],
                "source_id": document["source_id"],
                "text": document["body"],
                "text_sha256": sha256_bytes(document["body"].encode("utf-8")),
            }
            for document in lexical_documents
        ],
    }
    source_documents = {
        "schema_version": "knowledge-engine-source-documents/v1",
        "release_id": FULL_PRODUCTION_RELEASE_ID,
        "documents": [
            {
                "source_id": f"synthetic-source-{index:04d}",
                "uri": f"synthetic://m26-production/{index:04d}",
            }
            for index in range(FULL_PRODUCTION_NODE_COUNT)
        ],
    }
    document_source_index = {
        "schema_version": "knowledge-engine-document-source-index/v1",
        "release_id": FULL_PRODUCTION_RELEASE_ID,
        "sources": source_documents["documents"],
    }
    artifacts = {
        "graph": graph,
        "graph_v2": graph_v2,
        "lexical_index": lexical_index,
        "provenance": provenance,
        "semantic_inputs": semantic_inputs,
        "source_documents": source_documents,
        "document_source_index": document_source_index,
    }
    artifact_sha256 = {
        **{kind: _digest(payload) for kind, payload in artifacts.items()},
        "graph_v2": FULL_PRODUCTION_GRAPH_V2_SHA256,
    }
    artifact_keys = {
        kind: f"releases/{FULL_PRODUCTION_RELEASE_ID}/artifacts/{kind.replace('_', '-')}.json"
        for kind in artifacts
    }
    manifest = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": FULL_PRODUCTION_RELEASE_ID,
        "status": "production",
        "counts": {
            "document_graph_nodes": FULL_PRODUCTION_NODE_COUNT,
            "document_graph_edges": FULL_PRODUCTION_EDGE_COUNT,
            "document_sections": FULL_PRODUCTION_NODE_COUNT,
            "semantic_documents": 4197,
        },
        "artifacts": [
            {
                "kind": kind,
                "key": artifact_keys[kind],
                "sha256": digest,
                "bytes": 1,
                "media_type": "application/json",
                "audiences": ["authenticated_internal"],
                "required": True,
            }
            for kind, digest in sorted(artifact_sha256.items())
        ],
    }
    return ProductionAnswerBundle(
        manifest=manifest,
        graph=graph,
        graph_v2=graph_v2,
        lexical_index=lexical_index,
        provenance=provenance,
        manifest_sha256=_digest(manifest),
        artifact_sha256=artifact_sha256,
        artifact_keys=artifact_keys,
        loaded_at="2026-08-02T00:00:00Z",
        source_documents=source_documents,
        document_source_index=document_source_index,
        semantic_inputs=semantic_inputs,
    )


def _title(index: int) -> str:
    titles = {
        0: "Router Permission First Controls",
        1: "Adaptive Planning Invalidated Assumptions",
        2: "State Machines Legal Transitions",
        3: "Harness Acceptance Components",
        4: "Headless Harness Service",
        5: "Directed Acyclic Graph Dependencies",
        6: "Request Boundary Steering Controls",
        7: "Terminal Acceptance Component",
        30: "Outside Old Twenty Production Retrieval",
        31: "Outside Old Twenty Neighbour Hydration",
    }
    return titles.get(index, f"Production Concept {index:04d}")


def _document(index: int) -> dict[str, Any]:
    concept_id = f"concepts/prod-{index:04d}"
    section_id = f"{concept_id}#overview"
    title = _title(index)
    body = _body(index)
    return {
        "concept_id": concept_id,
        "section_id": section_id,
        "source_id": f"synthetic-source-{index:04d}",
        "audience": "internal",
        "title": title,
        "section_title": "Overview",
        "description": body[:180],
        "body": body,
        "excerpt": body[:320],
        "terms": body.lower().replace(".", "").split(),
    }


def _body(index: int) -> str:
    bodies = {
        0: (
            "A router should define permission-first controls before execution. "
            "It keeps owner admission, public denial, and retrieval boundaries explicit."
        ),
        1: (
            "Adaptive planning should react to invalidated assumptions by narrowing the plan. "
            "It records the changed premise before continuing execution."
        ),
        2: (
            "State machines make legal transitions explicit. "
            "They limit runtime movement to named states and accepted transitions."
        ),
        3: (
            "Harness acceptance components support permission-first execution. "
            "They connect owner admission checks with terminal acceptance evidence."
        ),
        4: (
            "The headless harness service executes acceptance checks without browser repair. "
            "It depends on harness acceptance components for verified runtime evidence."
        ),
        5: (
            "Directed acyclic graph dependencies model ordered relationships. "
            "They complement routers by showing which execution steps must precede others."
        ),
        6: (
            "Request boundary and steering controls changed through versioned source records. "
            "The temporal record keeps retrieved-at identity for comparison."
        ),
        7: (
            "The harness terminal acceptance component appears in the final verification path. "
            "It records whether the owner-only answer can be accepted."
        ),
        30: (
            "Outside old twenty production retrieval uses a full production graph seed. "
            "The selected section is deliberately outside the legacy twenty concept bundle."
        ),
        31: (
            "Outside old twenty neighbour hydration provides real source evidence for expansion. "
            "It is reached through the full production graph rather than the legacy bundle."
        ),
    }
    return bodies.get(
        index,
        f"Production concept {index:04d} has a hydrated section, source, and provenance record.",
    )


def _edges() -> list[dict[str, Any]]:
    special = [
        (3, 4, "depends_on"),
        (3, 7, "supports"),
        (0, 1, "complements"),
        (0, 5, "uses"),
        (1, 2, "requires"),
        (6, 1, "precedes"),
        (30, 31, "supports"),
    ]
    edges: list[dict[str, Any]] = []
    for index, (source, target, relation) in enumerate(special):
        edges.append(_edge(index, source, target, relation))
    next_index = len(edges)
    cursor = 0
    while len(edges) < FULL_PRODUCTION_EDGE_COUNT:
        source = cursor % FULL_PRODUCTION_NODE_COUNT
        target = (cursor + 1 + (cursor // FULL_PRODUCTION_NODE_COUNT)) % FULL_PRODUCTION_NODE_COUNT
        if source != target:
            edges.append(_edge(next_index, source, target, "related_to"))
            next_index += 1
        cursor += 1
    return edges


def _edge(index: int, source: int, target: int, relation: str) -> dict[str, Any]:
    return {
        "edge_id": f"edge-prod-{index:05d}",
        "source": f"concepts/prod-{source:04d}",
        "target": f"concepts/prod-{target:04d}",
        "relation_type": relation,
        "directed": True,
        "generated_inverse": False,
        "audience": "internal",
        "confidence": 0.91,
        "review_status": "approved",
        "provenance_ref": f"synthetic-provenance-{index:05d}",
    }


def _provenance_record(index: int) -> dict[str, Any]:
    concept_id = f"concepts/prod-{index:04d}"
    return {
        "subject": {"concept_id": concept_id},
        "sources": [
            {
                "source_id": f"synthetic-source-{index:04d}",
                "uri": f"synthetic://m26-production/{index:04d}",
                "retrieved_at": "2026-08-02T00:00:00Z",
            }
        ],
        "claims": [
            {
                "claim_id": f"claim-prod-{index:04d}",
                "text": f"{concept_id} has production source and provenance identity.",
            }
        ],
        "release_identity": {
            "release_id": FULL_PRODUCTION_RELEASE_ID,
            "source_commit_sha": FULL_PRODUCTION_SOURCE_SHA,
            "admission_sha256": FULL_PRODUCTION_ADMISSION_SHA256,
        },
    }
