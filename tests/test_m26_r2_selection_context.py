from knowledge_engine.m26_pa7_arbitrary_query_runtime import _select_diverse_candidates


def test_selection_preserves_rank_stratified_source_coverage() -> None:
    candidates = [
        {"section_id": "s1", "source_id": "a", "concept_id": "a", "seed_rank": 1, "score": 100, "channels": {"lexical"}},
        {"section_id": "s7", "source_id": "b", "concept_id": "b", "seed_rank": 7, "score": 2, "channels": {"lexical"}, "source_coverage": {"coverage_score": 4}},
        {"section_id": "s33", "source_id": "c", "concept_id": "c", "seed_rank": 33, "score": 1, "channels": {"lexical"}, "source_coverage": {"coverage_score": 10}},
    ]
    selected = _select_diverse_candidates(candidates, budget=3)
    assert {item["section_id"] for item in selected} == {"s1", "s7", "s33"}
