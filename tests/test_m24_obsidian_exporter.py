from __future__ import annotations

import json

from knowledge_engine.m14_public_contracts import (
    PublicSearchRequest,
    public_search_response_from_runtime,
)
from knowledge_engine.m24_obsidian_exporter import (
    OBSIDIAN_EXPORT_SCHEMA,
    export_search_response_to_obsidian,
)


def _runtime_result(*, answered: bool = True) -> dict:
    return {
        "status": "answered" if answered else "not_found",
        "release": {
            "release_id": "20260720T000000Z-m24",
            "manifest_sha256": "c" * 64,
        },
        "results": (
            [
                {
                    "concept_id": "concepts/compiler",
                    "section_id": "concepts/compiler#operations",
                    "title": "Knowledge Compiler",
                    "section_title": "Operations",
                    "excerpt": "The compiler validates reviewed knowledge.",
                    "score": 12,
                    "citations": [
                        {
                            "source_id": "source-1",
                            "source_kind": "web",
                            "source_title": "Compiler Specification",
                            "publisher": "Example Foundation",
                            "uri": "https://example.com/compiler?b=2&a=1",
                            "retrieved_at": "2026-07-20T00:00:00Z",
                            "published_at": "2026-07-01T00:00:00Z",
                            "content_sha256": "d" * 64,
                            "snapshot_available": True,
                            "concept_id": "concepts/compiler",
                            "section_id": "concepts/compiler#operations",
                            "citation_scope": "claim",
                            "claim_id": "claim-1",
                            "support": "direct",
                            "locator": {
                                "heading": "Operations",
                                "page": 2,
                                "quote": "raw evidence must not export",
                            },
                            "claim_confidence": 0.98,
                            "review_status": "human_approved",
                            "derivation_type": "synthesized",
                        }
                    ],
                }
            ]
            if answered
            else []
        ),
        "not_found_reason": None if answered else "no_match",
    }


def _search_response(answered: bool = True):
    request = PublicSearchRequest(query="compiler", max_results=5)
    return public_search_response_from_runtime(
        _runtime_result(answered=answered),
        query=request.query,
        max_results=request.max_results,
        audience=request.audience,
    )


def test_obsidian_export_preserves_bounded_provenance_without_serving_authority() -> None:
    bundle = export_search_response_to_obsidian(_search_response())
    replay = export_search_response_to_obsidian(_search_response())

    assert bundle == replay
    assert bundle.schema_version == OBSIDIAN_EXPORT_SCHEMA
    assert bundle.authority.production_retrieval == "lexical"
    assert bundle.authority.semantic_serving_enabled is False
    assert bundle.authority.semantic_promotion_enabled is False
    assert bundle.authority.hybrid_retrieval_enabled is False
    assert bundle.authority.source_mutation_authorized is False

    files = {item.path: item for item in bundle.files}
    assert set(files) == {
        "README.md",
        "concepts/001-knowledge-compiler.md",
        "sources/001-compiler-specification.md",
        "manifest.json",
    }

    source_note = files["sources/001-compiler-specification.md"].content
    assert "Citation 1" in source_note
    assert "Locator: `heading=Operations, page=2`" in source_note
    assert "Claim IDs: `claim-1`" in source_note
    assert "Semantic serving: `disabled`" in source_note
    assert "raw evidence must not export" not in source_note
    assert "query_vector" not in source_note

    concept_note = files["concepts/001-knowledge-compiler.md"].content
    assert "[[sources/001-compiler-specification|" in concept_note
    assert "Retrieval authority: `lexical`" in concept_note

    manifest = json.loads(files["manifest.json"].content)
    assert manifest["authority"]["production_retrieval"] == "lexical"
    assert manifest["authority"]["semantic_serving_enabled"] is False
    assert manifest["authority"]["raw_evidence_exposed"] is False
    assert bundle.manifest_sha256 == files["manifest.json"].content_sha256


def test_empty_obsidian_export_keeps_manifest_and_readme_only() -> None:
    bundle = export_search_response_to_obsidian(_search_response(answered=False))

    assert [item.path for item in bundle.files] == ["README.md", "manifest.json"]
    assert "Result count: `0`" in bundle.files[0].content
    assert bundle.authority.retrieval_authority == "lexical"
