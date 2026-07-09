from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.m14_retrieval import (
    SEMANTIC_SCHEMA,
    retrieve_wiki_first,
)
from knowledge_engine.runtime import Runtime


def _provenance(*concept_ids: str) -> dict:
    return {
        "records": [
            {
                "subject": {"concept_id": concept_id},
                "sources": [
                    {
                        "source_id": f"source-{index}",
                        "uri": f"https://example.com/{index}",
                        "retrieved_at": "2026-07-10T00:00:00Z",
                    }
                ],
            }
            for index, concept_id in enumerate(concept_ids, start=1)
        ]
    }


def test_compiler_emits_section_level_documents(built_store) -> None:
    _, compiled, _ = built_store
    lexical = json.loads(
        (compiled.release_root / "artifacts/lexical-index.json").read_text()
    )
    graph = json.loads((compiled.release_root / "artifacts/graph.json").read_text())
    section_ids = [item["section_id"] for item in lexical["documents"]]
    assert lexical["schema_version"] == "2.0"
    assert lexical["document_model"] == "section"
    assert section_ids == [
        "concepts/knowledge-compiler#knowledge-compiler",
        "concepts/knowledge-compiler#operational-rule",
    ]
    assert graph["schema_version"] == "1.1"
    assert compiled.manifest["counts"]["sections"] == 2


def test_runtime_prefers_matching_section_and_disables_raw_fallback(
    tmp_path: Path,
    built_store,
) -> None:
    store, _, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")
    result = runtime.query("channel pointer integrity", {"internal"})
    assert result["status"] == "answered"
    assert result["results"][0]["section_id"].endswith("#operational-rule")
    assert result["retrieval"]["strategy"] == "wiki_first"
    assert result["retrieval"]["section_document_count"] == 2
    assert result["retrieval"]["raw_fallback_allowed"] is False
    assert result["retrieval"]["raw_fallback_used"] is False
    assert result["retrieval"]["raw_fallback_reason"] == (
        "disabled_by_governance"
    )


def test_legacy_concept_documents_are_normalized_to_overview_sections() -> None:
    result = retrieve_wiki_first(
        query="compiler",
        allowed_audiences={"public"},
        lexical_index={
            "schema_version": "1.0",
            "documents": [
                {
                    "concept_id": "concepts/compiler",
                    "x_kos_id": "ko_legacy",
                    "title": "Compiler",
                    "description": "A compiler",
                    "audience": "public",
                    "terms": ["compiler"],
                }
            ],
        },
        graph={
            "nodes": [
                {
                    "concept_id": "concepts/compiler",
                    "audience": "public",
                }
            ],
            "edges": [],
        },
        provenance=_provenance("concepts/compiler"),
    )
    assert result["status"] == "answered"
    assert result["results"][0]["section_id"] == (
        "concepts/compiler#overview"
    )


def test_semantic_contribution_requires_compatible_artifact() -> None:
    lexical = {
        "documents": [
            {
                "concept_id": "concepts/compiler",
                "section_id": "concepts/compiler#overview",
                "title": "Compiler",
                "section_title": "Overview",
                "description": "Build system",
                "body": "Deterministic pipeline",
                "excerpt": "Deterministic pipeline",
                "audience": "public",
                "terms": ["compiler"],
            }
        ]
    }
    graph = {
        "nodes": [
            {"concept_id": "concepts/compiler", "audience": "public"}
        ],
        "edges": [],
    }
    semantic = {
        "schema_version": SEMANTIC_SCHEMA,
        "documents": [
            {
                "section_id": "concepts/compiler#overview",
                "terms": ["orchestration"],
            }
        ],
    }
    compatible = retrieve_wiki_first(
        query="orchestration",
        allowed_audiences={"public"},
        lexical_index=lexical,
        graph=graph,
        provenance=_provenance("concepts/compiler"),
        semantic_index=semantic,
    )
    incompatible = retrieve_wiki_first(
        query="orchestration",
        allowed_audiences={"public"},
        lexical_index=lexical,
        graph=graph,
        provenance=_provenance("concepts/compiler"),
        semantic_index={**semantic, "schema_version": "unknown/v1"},
    )
    assert compatible["status"] == "answered"
    assert compatible["retrieval"]["semantic_available"] is True
    assert compatible["retrieval"]["semantic_used"] is True
    assert incompatible["status"] == "not_found"
    assert incompatible["retrieval"]["semantic_available"] is False


def test_graph_expansion_rechecks_audience_before_adding_neighbor() -> None:
    lexical = {
        "documents": [
            {
                "concept_id": "concepts/public",
                "section_id": "concepts/public#overview",
                "title": "Public seed",
                "section_title": "Overview",
                "description": "Visible topic",
                "body": "visible topic",
                "excerpt": "visible topic",
                "audience": "public",
                "terms": ["visible", "topic"],
            },
            {
                "concept_id": "concepts/internal",
                "section_id": "concepts/internal#overview",
                "title": "Internal neighbor",
                "section_title": "Overview",
                "description": "Hidden detail",
                "body": "hidden detail",
                "excerpt": "hidden detail",
                "audience": "internal",
                "terms": ["hidden", "detail"],
            },
        ]
    }
    graph = {
        "nodes": [
            {"concept_id": "concepts/public", "audience": "public"},
            {"concept_id": "concepts/internal", "audience": "internal"},
        ],
        "edges": [
            {
                "from_concept_id": "concepts/public",
                "to_concept_id": "concepts/internal",
            }
        ],
    }
    public = retrieve_wiki_first(
        query="visible",
        allowed_audiences={"public"},
        lexical_index=lexical,
        graph=graph,
        provenance=_provenance("concepts/public", "concepts/internal"),
    )
    internal = retrieve_wiki_first(
        query="visible",
        allowed_audiences={"internal"},
        lexical_index=lexical,
        graph=graph,
        provenance=_provenance("concepts/public", "concepts/internal"),
    )
    assert [item["concept_id"] for item in public["results"]] == [
        "concepts/public"
    ]
    assert {item["concept_id"] for item in internal["results"]} == {
        "concepts/public",
        "concepts/internal",
    }
    neighbor = next(
        item
        for item in internal["results"]
        if item["concept_id"] == "concepts/internal"
    )
    assert neighbor["score_components"]["graph"] == 1
    assert neighbor["expanded_from"] == ["concepts/public"]


def test_retrieval_tie_breaking_is_deterministic() -> None:
    documents = [
        {
            "concept_id": concept_id,
            "section_id": f"{concept_id}#overview",
            "title": "Same",
            "section_title": "Same",
            "description": "same",
            "body": "same",
            "excerpt": "same",
            "audience": "public",
            "terms": ["same"],
        }
        for concept_id in ("concepts/zeta", "concepts/alpha")
    ]
    result = retrieve_wiki_first(
        query="same",
        allowed_audiences={"public"},
        lexical_index={"documents": documents},
        graph={
            "nodes": [
                {"concept_id": item["concept_id"], "audience": "public"}
                for item in documents
            ],
            "edges": [],
        },
        provenance=_provenance("concepts/zeta", "concepts/alpha"),
    )
    assert [item["concept_id"] for item in result["results"]] == [
        "concepts/alpha",
        "concepts/zeta",
    ]
