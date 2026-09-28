from __future__ import annotations

from typing import Any, Mapping

from knowledge_engine import m26_pa7_arbitrary_query_runtime as runtime
from tests.m26_answer_bundle_fixture import synthetic_full_production_answer_bundle


def _old_bounded_augmentation_documents(
    *,
    documents: list[Mapping[str, Any]],
    evidence: list[Mapping[str, Any]],
    lexical_results: list[Mapping[str, Any]],
    limit: int,
) -> list[Mapping[str, Any]]:
    docs = [item for item in documents if isinstance(item, Mapping)]
    by_section = {str(item.get("section_id", "")): item for item in docs}
    selected_sections = {
        str(item.get("section_id", ""))
        for item in evidence
        if str(item.get("section_id", ""))
    }
    lexical_sections = [
        str(item.get("section_id", ""))
        for item in lexical_results
        if isinstance(item, Mapping) and str(item.get("section_id", ""))
    ]
    ordered_ids: list[str] = []
    for section_id in [
        *selected_sections,
        *lexical_sections[: max(limit * 4, 32)],
    ]:
        if section_id and section_id not in ordered_ids:
            ordered_ids.append(section_id)
    selected_sources = {
        str(item.get("source_id", ""))
        for item in evidence
        if str(item.get("source_id", ""))
    }
    selected_concepts = {
        str(item.get("concept_id", ""))
        for item in evidence
        if str(item.get("concept_id", ""))
    }
    for item in docs:
        section_id = str(item.get("section_id", ""))
        if not section_id or section_id in ordered_ids:
            continue
        if (
            str(item.get("source_id", "")) in selected_sources
            or str(item.get("concept_id", "")) in selected_concepts
        ):
            ordered_ids.append(section_id)
        if len(ordered_ids) >= max(limit * 8, 96):
            break
    return [
        by_section[section_id]
        for section_id in ordered_ids
        if section_id in by_section
    ]


def test_augmentation_document_index_reuses_immutable_release_documents() -> None:
    bundle = synthetic_full_production_answer_bundle()
    documents = bundle.lexical_index["documents"]
    runtime._AUGMENTATION_DOCUMENT_INDEX_CACHE.clear()
    runtime._AUGMENTATION_DOCUMENT_INDEX_CACHE_ORDER.clear()

    first = runtime._augmentation_document_index(documents)
    second = runtime._augmentation_document_index(documents)

    assert first is not None
    assert second is first
    assert len(first.documents) == len(documents)


def test_bounded_augmentation_cache_preserves_legacy_document_order() -> None:
    bundle = synthetic_full_production_answer_bundle()
    documents = bundle.lexical_index["documents"]
    lexical = runtime.retrieve_wiki_first(
        query="What should a router define for permission-first controls?",
        allowed_audiences={"public", "internal"},
        lexical_index=bundle.lexical_index,
        graph=bundle.graph,
        relation_graph=bundle.graph_v2,
        relation_aware_expansion=True,
        provenance=bundle.provenance,
        semantic_index=bundle.semantic_inputs,
        limit=8,
    )
    evidence = [
        {
            "section_id": lexical["results"][0]["section_id"],
            "source_id": documents[0]["source_id"],
            "concept_id": documents[0]["concept_id"],
        }
    ]

    expected = _old_bounded_augmentation_documents(
        documents=documents,
        evidence=evidence,
        lexical_results=lexical["results"],
        limit=12,
    )
    actual = runtime._bounded_augmentation_documents(
        documents=documents,
        evidence=evidence,
        lexical_results=lexical["results"],
        limit=12,
    )

    assert [
        str(item.get("section_id", ""))
        for item in actual or []
    ] == [
        str(item.get("section_id", ""))
        for item in expected
    ]


def test_source_coverage_cache_preserves_cold_and_warm_results() -> None:
    bundle = synthetic_full_production_answer_bundle()
    question = "When is separating work across multiple agents actually worth the complexity?"
    lexical = runtime.retrieve_wiki_first(
        query=question,
        allowed_audiences={"public", "internal"},
        lexical_index=bundle.lexical_index,
        graph=bundle.graph,
        relation_graph=bundle.graph_v2,
        relation_aware_expansion=True,
        provenance=bundle.provenance,
        semantic_index=bundle.semantic_inputs,
        limit=8,
    )

    runtime._AUGMENTATION_DOCUMENT_INDEX_CACHE.clear()
    runtime._AUGMENTATION_DOCUMENT_INDEX_CACHE_ORDER.clear()
    cold = runtime._augment_source_coverage_candidates(
        lexical_result=lexical,
        lexical_index=bundle.lexical_index,
        question=question,
    )
    warm = runtime._augment_source_coverage_candidates(
        lexical_result=lexical,
        lexical_index=bundle.lexical_index,
        question=question,
    )

    assert cold == warm
