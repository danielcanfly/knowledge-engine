from knowledge_engine.m26_pa7_arbitrary_query_runtime import (
    _augment_source_coverage_candidates,
    _source_coverage_metadata,
)


def test_source_coverage_backfill_is_bounded_and_records_overlap() -> None:
    documents = [
        {
            "source_id": "source-a",
            "section_id": "section-a",
            "title": "Agent harness overview",
            "section_title": "Overview",
            "body": "An agent harness owns evidence and tools.",
        },
        {
            "source_id": "source-b",
            "section_id": "section-b",
            "title": "Agent harness controls",
            "section_title": "Evidence",
            "body": "The harness records evidence for a completed task.",
        },
    ]
    result = _augment_source_coverage_candidates(
        lexical_result={"results": [{"section_id": "section-a", "score": 4}]},
        lexical_index={"documents": documents},
        question="What evidence does an agent harness own?",
    )
    assert [item["section_id"] for item in result["results"]] == [
        "section-a",
        "section-b",
    ]
    coverage = result["results"][1]["score_components"]["source_coverage"]
    assert coverage["source_coverage"] is True
    assert "evidence" in coverage["title_overlap_terms"] + coverage["body_overlap_terms"]


def test_source_coverage_ignores_conversational_terms() -> None:
    metadata = _source_coverage_metadata(
        question="What does an agent say and how can it work?",
        document={
            "source_id": "source-a",
            "section_id": "section-a",
            "title": "Agent workflow",
            "section_title": "Overview",
            "body": "An agent workflow is bounded and observable.",
        },
    )
    assert metadata is not None
    assert "does" not in metadata["title_overlap_terms"] + metadata["body_overlap_terms"]
    assert "how" not in metadata["title_overlap_terms"] + metadata["body_overlap_terms"]
