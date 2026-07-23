from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m25_blog_pilot_batch_b import (
    ACCEPTED_BATCH_A_INVENTORY_SHA256,
    ACCEPTED_BATCH_B_INVENTORY_SHA256,
    ACCEPTED_MASTER_INVENTORY_SHA256,
    assemble_inventory_bundle,
    validate_accepted_baseline,
    validate_graph_identity,
)


def _record(index: int) -> dict[str, object]:
    series = f"series_{index}"
    return {
        "article_id": f"article_{index}",
        "slug": f"article-{index}",
        "series_id": series,
        "series_key": str(index),
        "series_title": f"Series {index}",
        "series_order": 1,
        "series_display_order": index,
        "series_resolution_source": "frontmatter",
        "partition_group_id": series,
    }


def _bundle() -> dict[str, object]:
    return assemble_inventory_bundle(
        repository="example/blog",
        commit="a" * 40,
        expected_count=4,
        batch_size=2,
        records=[_record(index) for index in range(4)],
        catalog=[],
        catalog_blob_sha="b" * 40,
        catalog_raw=b"catalog",
        convergence_count=0,
    )


def test_inventory_bundle_is_exact_complement() -> None:
    bundle = _bundle()
    assert len(bundle["batch_a"]) == 2
    assert len(bundle["batch_b"]) == 2
    assert bundle["a_ids"].isdisjoint(bundle["b_ids"])
    assert bundle["a_ids"] | bundle["b_ids"] == bundle["master_ids"]
    assert bundle["manifest_b"]["batch_id"] == "M25.9A-BLOG-B"


def test_inventory_bundle_rejects_unequal_batches() -> None:
    with pytest.raises(IntegrityError, match="two equal batches"):
        assemble_inventory_bundle(
            repository="example/blog",
            commit="a" * 40,
            expected_count=5,
            batch_size=2,
            records=[_record(index) for index in range(4)],
            catalog=[],
            catalog_blob_sha="b" * 40,
            catalog_raw=b"catalog",
            convergence_count=0,
        )


def test_accepted_baseline_requires_all_three_exact_digests() -> None:
    bundle = _bundle()
    validate_accepted_baseline(
        bundle,
        expected_master_sha256=bundle["master"]["inventory_sha256"],
        expected_batch_a_sha256=bundle["manifest_a"][
            "batch_inventory_sha256"
        ],
        expected_batch_b_sha256=bundle["manifest_b"][
            "batch_inventory_sha256"
        ],
    )

    with pytest.raises(IntegrityError, match="baseline drifted"):
        validate_accepted_baseline(
            bundle,
            expected_master_sha256="0" * 64,
            expected_batch_a_sha256=bundle["manifest_a"][
                "batch_inventory_sha256"
            ],
            expected_batch_b_sha256=bundle["manifest_b"][
                "batch_inventory_sha256"
            ],
        )


def test_accepted_baseline_constants_are_sha256_values() -> None:
    values = {
        ACCEPTED_MASTER_INVENTORY_SHA256,
        ACCEPTED_BATCH_A_INVENTORY_SHA256,
        ACCEPTED_BATCH_B_INVENTORY_SHA256,
    }
    assert len(values) == 3
    assert all(len(value) == 64 for value in values)
    assert all(set(value) <= set("0123456789abcdef") for value in values)


def test_graph_identity_accepts_traceable_population() -> None:
    records = [_record(0), _record(1)]
    nodes = [
        {
            "node_id": "series-0",
            "node_type": "Series",
            "source_article_ids": ["article_0"],
        },
        {
            "node_id": "series-1",
            "node_type": "Series",
            "source_article_ids": ["article_1"],
        },
        {
            "node_id": "article-0",
            "node_type": "Article",
            "source_article_id": "article_0",
            "source_locator": {
                "origin_repository": "example/blog",
                "origin_commit": "a" * 40,
                "origin_path": "one.md",
                "start_line": 1,
                "end_line": 10,
            },
        },
        {
            "node_id": "article-1",
            "node_type": "Article",
            "source_article_id": "article_1",
            "source_locator": {
                "origin_repository": "example/blog",
                "origin_commit": "a" * 40,
                "origin_path": "two.md",
                "start_line": 1,
                "end_line": 10,
            },
        },
    ]
    validate_graph_identity(records, nodes)


def test_graph_identity_rejects_split_series_title() -> None:
    records = [_record(0), _record(1)]
    records[1] = copy.deepcopy(records[1])
    records[1]["series_title"] = "Series 0"
    with pytest.raises(IntegrityError, match="one-to-one"):
        validate_graph_identity(records, [])
