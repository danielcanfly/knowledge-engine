from __future__ import annotations

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine import m26_semantic_arch_repair_candidate_release as subject


def test_source_bound_release_id_changes_with_source_and_admission_identity() -> None:
    engine = "a" * 40
    first = subject._source_bound_candidate_release_id(
        engine_sha=engine,
        source_commit_sha="b" * 40,
        admission_sha256="c" * 64,
    )
    second = subject._source_bound_candidate_release_id(
        engine_sha=engine,
        source_commit_sha="d" * 40,
        admission_sha256="e" * 64,
    )

    assert first == f"m25blog-{'b' * 12}-{'c' * 12}-{'a' * 12}"
    assert second != first


def test_pack_population_is_dynamic_and_article_bound() -> None:
    pack = {
        "article_by_id": {"source_a": {}, "source_b": {}},
        "nodes": [
            {"node_type": "Series"},
            {"node_type": "Article"},
            {"node_type": "Article"},
            {"node_type": "Section"},
            {"node_type": "Section"},
            {"node_type": "Section"},
        ],
        "edges": [{}, {}, {}, {}],
    }

    assert subject._pack_population(pack) == {
        "sources": 2,
        "series": 1,
        "articles": 2,
        "sections": 3,
        "graph_nodes": 6,
        "graph_edges": 4,
        "semantic_documents": 5,
    }

    pack["nodes"] = [node for node in pack["nodes"] if node["node_type"] != "Article"] + [
        {"node_type": "Article"}
    ]
    with pytest.raises(
        IntegrityError,
        match="PA7_ARCH_REPAIR_CANDIDATE_ARTICLE_POPULATION_MISMATCH",
    ):
        subject._pack_population(pack)


def test_explicit_source_identity_must_be_complete() -> None:
    with pytest.raises(
        IntegrityError,
        match="PA7_ARCH_REPAIR_CANDIDATE_SOURCE_IDENTITY_INCOMPLETE",
    ):
        subject.build_semantic_arch_repair_candidate_bundle(
            {"article_by_id": {}, "source_bytes": {}, "nodes": [], "edges": []},
            engine_sha="a" * 40,
            source_repository="danielcanfly/daniel-blog",
        )
