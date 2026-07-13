from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m20_lexical_enrichment import (
    ALIAS_WEIGHT,
    RELATION_WEIGHT,
    TAG_WEIGHT,
    enrich_lexical_results,
)

RELEASE = {
    "release_id": "20260713T000000Z-m206fixture",
    "manifest_sha256": "a" * 64,
}


def _candidate(section: str, *, audience: str = "public") -> dict:
    return {
        "section_id": section,
        "concept_id": section.split("#", 1)[0],
        "audience": audience,
        "title": section,
        "citations": [{"source_id": f"src-{section}"}],
    }


def _lexical() -> dict:
    return {
        "status": "answered",
        "release": copy.deepcopy(RELEASE),
        "results": [
            _candidate("concepts/a#one"),
            _candidate("concepts/b#one"),
            _candidate("concepts/c#one"),
        ],
        "retrieval": {"mode": "lexical"},
        "evaluation": {"release_blocking": False},
    }


def _bundle() -> dict:
    return {
        **copy.deepcopy(RELEASE),
        "rows": [
            {
                "section_id": "concepts/a#one",
                "concept_id": "concepts/a",
                "audience": "public",
                "aliases": ["retrieval augmented generation"],
                "tags": ["rag", "retrieval"],
                "relations": [
                    {
                        "type": "depends_on",
                        "target_concept_id": "concepts/indexing",
                    }
                ],
            },
            {
                "section_id": "concepts/b#one",
                "concept_id": "concepts/b",
                "audience": "public",
                "aliases": ["hybrid search"],
                "tags": ["rag", "hybrid"],
                "relations": [
                    {
                        "type": "uses",
                        "target_concept_id": "concepts/reranking",
                    }
                ],
            },
            {
                "section_id": "concepts/c#one",
                "concept_id": "concepts/c",
                "audience": "public",
                "aliases": [],
                "tags": ["baseline"],
                "relations": [],
            },
        ],
    }


def test_fixed_signal_weights_reorder_candidates_deterministically() -> None:
    result = enrich_lexical_results(
        _lexical(),
        "Retrieval Augmented Generation",
        {"public"},
        _bundle(),
        limit=3,
    )

    candidates = result["enriched_lexical_candidates"]
    assert [item["section_id"] for item in candidates] == [
        "concepts/a#one",
        "concepts/b#one",
        "concepts/c#one",
    ]
    assert candidates[0]["alias_score"] == ALIAS_WEIGHT
    assert candidates[0]["signal_score"] == ALIAS_WEIGHT
    assert result["results"][0]["citations"] == [
        {"source_id": "src-concepts/a#one"}
    ]
    assert result["evaluation"] == {"release_blocking": False}


def test_tag_and_relation_scores_are_independent_and_bounded() -> None:
    result = enrich_lexical_results(
        _lexical(),
        "rag hybrid uses reranking",
        {"public"},
        _bundle(),
        limit=3,
    )

    first = result["enriched_lexical_candidates"][0]
    assert first["section_id"] == "concepts/b#one"
    assert first["tag_score"] == TAG_WEIGHT * 2
    assert first["relation_score"] == RELATION_WEIGHT
    assert first["alias_score"] == 0
    assert first["matched_tags"] == ["hybrid", "rag"]
    assert first["matched_relations"] == [
        {"type": "uses", "target_concept_id": "concepts/reranking"}
    ]


def test_nfkc_casefold_alias_matching_is_deterministic() -> None:
    bundle = _bundle()
    bundle["rows"][0]["aliases"] = ["ＲＡＧ"]
    result = enrich_lexical_results(
        _lexical(),
        "rag",
        {"public"},
        bundle,
    )
    first = result["enriched_lexical_candidates"][0]
    assert first["section_id"] == "concepts/a#one"
    assert first["matched_aliases"] == ["rag"]


def test_original_lexical_authority_is_preserved() -> None:
    lexical = _lexical()
    result = enrich_lexical_results(
        lexical,
        "hybrid search",
        {"public"},
        _bundle(),
    )
    assert result["results"] == lexical["results"]
    assert result["retrieval"]["lexical_enrichment_authoritative"] is False
    assert result["retrieval"]["production_authority"] is False


def test_cross_release_bundle_fails_closed() -> None:
    bundle = _bundle()
    bundle["manifest_sha256"] = "b" * 64
    with pytest.raises(IntegrityError, match="release identities differ"):
        enrich_lexical_results(_lexical(), "rag", {"public"}, bundle)


def test_acl_violation_fails_closed_before_scoring() -> None:
    lexical = _lexical()
    lexical["results"][0]["audience"] = "internal"
    bundle = _bundle()
    bundle["rows"][0]["audience"] = "internal"
    with pytest.raises(IntegrityError, match="unauthorised lexical row"):
        enrich_lexical_results(lexical, "rag", {"public"}, bundle)


def test_missing_extra_or_duplicate_rows_fail_closed() -> None:
    missing = _bundle()
    missing["rows"].pop()
    with pytest.raises(IntegrityError, match="missing enrichment row"):
        enrich_lexical_results(_lexical(), "rag", {"public"}, missing)

    extra = _bundle()
    extra["rows"].append(
        {
            "section_id": "concepts/extra#one",
            "concept_id": "concepts/extra",
            "audience": "public",
            "aliases": [],
            "tags": [],
            "relations": [],
        }
    )
    with pytest.raises(IntegrityError, match="unknown lexical sections"):
        enrich_lexical_results(_lexical(), "rag", {"public"}, extra)

    duplicate = _bundle()
    duplicate["rows"].append(copy.deepcopy(duplicate["rows"][0]))
    with pytest.raises(IntegrityError, match="duplicate section row"):
        enrich_lexical_results(_lexical(), "rag", {"public"}, duplicate)


def test_concept_identity_drift_and_duplicate_relations_fail_closed() -> None:
    drift = _bundle()
    drift["rows"][0]["concept_id"] = "concepts/wrong"
    with pytest.raises(IntegrityError, match="identity drift"):
        enrich_lexical_results(_lexical(), "rag", {"public"}, drift)

    duplicate = _bundle()
    relation = copy.deepcopy(duplicate["rows"][0]["relations"][0])
    duplicate["rows"][0]["relations"].append(relation)
    with pytest.raises(IntegrityError, match="duplicate relation signal"):
        enrich_lexical_results(_lexical(), "rag", {"public"}, duplicate)


def test_signal_count_and_request_bounds_fail_closed() -> None:
    bundle = _bundle()
    bundle["rows"][0]["aliases"] = [f"alias-{index}" for index in range(21)]
    with pytest.raises(IntegrityError, match="alias must be a bounded list"):
        enrich_lexical_results(_lexical(), "rag", {"public"}, bundle)

    with pytest.raises(IntegrityError, match="limit must be an integer"):
        enrich_lexical_results(_lexical(), "rag", {"public"}, _bundle(), limit=0)
