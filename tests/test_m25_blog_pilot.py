from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m25_blog_pilot import (
    SERIES_META_PATH,
    GitHubClient,
    TreeBlob,
    build_article_record,
    build_batch,
    git_blob_sha,
    heading_sections,
    parse_series_catalog,
    partition_by_groups,
)

CATALOG = b"""export type BlogLang = 'en' | 'zh';
const SERIES = [
  { slug: /^alpha-\\d+$/, key: 'alpha', order: 1, labelZh: '1. Alpha ZH', labelEn: '1. Alpha' },
  { slug: /^beta-\\d+$/, key: 'beta', order: 2, labelZh: '2. Beta ZH', labelEn: '2. Beta' },
  { slug: /^fallback-\\d+$/, key: 'fallback', order: 3,
    labelZh: '3. Fallback ZH', labelEn: '3. Fallback' },
];
"""


class FakeClient(GitHubClient):
    def __init__(self, articles: dict[str, bytes], catalog: bytes = CATALOG) -> None:
        self.files = dict(articles)
        self.files[SERIES_META_PATH] = catalog
        self.by_sha = {git_blob_sha(value): value for value in self.files.values()}

    def tree(self, repository: str, commit: str) -> list[TreeBlob]:
        del repository, commit
        return [
            TreeBlob(path=path, sha=git_blob_sha(raw), size=len(raw))
            for path, raw in self.files.items()
        ]

    def blob(self, repository: str, blob_sha: str) -> bytes:
        del repository
        return self.by_sha[blob_sha]


def article(
    slug: str,
    title: str,
    *,
    series: str | None,
    order: int | None,
    headings: tuple[str, ...] = ("One", "Two"),
) -> tuple[str, bytes]:
    frontmatter = [
        "---",
        f"title: {json.dumps(title)}",
        "draft: false",
        "pubDate: 2026-07-23",
    ]
    if series:
        frontmatter.append(f"series: {json.dumps(series)}")
    if order is not None:
        frontmatter.append(f"seriesOrder: {order}")
    frontmatter.extend(["---", "", f"# {title}", ""])
    for heading in headings:
        frontmatter.extend([f"## {heading}", "", f"Body for {heading}.", ""])
    path = f"src/content/blog/{slug}/en.md"
    return path, ("\n".join(frontmatter) + "\n").encode()


@pytest.fixture
def synthetic_articles() -> dict[str, bytes]:
    pairs = [
        article("alpha-1", "Alpha 1", series="Alpha", order=1),
        article("alpha-2", "Alpha 2", series="Alpha", order=2),
        article("beta-1", "Beta 1", series="Beta", order=1),
        article("gamma-1", "Gamma 1", series="Gamma", order=1),
        article("gamma-2", "Gamma 2", series="Gamma", order=2),
        article("single", "Single", series=None, order=None),
    ]
    return dict(pairs)


def test_build_batch_has_complete_population_and_traceable_nodes(
    tmp_path: Path, synthetic_articles: dict[str, bytes]
) -> None:
    receipt = build_batch(
        repository="example/blog",
        commit="a" * 40,
        expected_count=6,
        batch_size=3,
        output_dir=tmp_path,
        client=FakeClient(synthetic_articles),
    )
    assert receipt["master_source_count"] == 6
    assert receipt["batch_a_source_count"] == 3
    assert receipt["batch_b_source_count"] == 3
    assert receipt["intersection_count"] == 0
    assert receipt["missing_count"] == 0
    assert receipt["snapshot_count"] == 3
    assert receipt["article_node_count"] == 3
    assert receipt["section_node_count"] == 6
    assert receipt["formal_series_count"] == 3
    assert receipt["parent_collection_count"] == 4
    assert receipt["standalone_article_count"] == 1
    assert receipt["semantic_claim_promotion_permitted"] is False
    nodes = [
        json.loads(line)
        for line in (tmp_path / "candidate-nodes.jsonl").read_text().splitlines()
    ]
    section_nodes = [node for node in nodes if node["node_type"] == "Section"]
    assert all(node["source_locator"]["start_line"] > 0 for node in section_nodes)
    assert all(
        node["source_locator"]["end_line"] >= node["source_locator"]["start_line"]
        for node in section_nodes
    )


def test_series_catalog_parser_preserves_key_order_and_clean_label() -> None:
    catalog = parse_series_catalog(CATALOG)
    assert [entry["key"] for entry in catalog] == ["alpha", "beta", "fallback"]
    assert catalog[0]["display_order"] == 1
    assert catalog[0]["label_en"] == "1. Alpha"
    assert catalog[0]["label_en_clean"] == "Alpha"


def test_catalog_fallback_resolves_missing_frontmatter_series() -> None:
    path, raw = article("fallback-1", "Fallback 1", series=None, order=None)
    record = build_article_record(
        repository="example/blog",
        commit="a" * 40,
        tree_blob=TreeBlob(path=path, sha=git_blob_sha(raw), size=len(raw)),
        raw=raw,
        series_catalog=parse_series_catalog(CATALOG),
    )
    assert record["series_id"] == "series_fallback"
    assert record["series_title"] == "Fallback"
    assert record["series_order"] == 1
    assert record["series_resolution_source"] == "series_catalog_fallback"


def test_explicit_frontmatter_series_takes_label_precedence() -> None:
    path, raw = article("alpha-1", "Alpha 1", series="Custom Alpha", order=9)
    record = build_article_record(
        repository="example/blog",
        commit="a" * 40,
        tree_blob=TreeBlob(path=path, sha=git_blob_sha(raw), size=len(raw)),
        raw=raw,
        series_catalog=parse_series_catalog(CATALOG),
    )
    assert record["series_id"] == "series_alpha"
    assert record["series_title"] == "Custom Alpha"
    assert record["series_order"] == 9
    assert record["series_resolution_source"] == "frontmatter"


def test_partition_never_splits_real_series() -> None:
    records = [
        {
            "partition_group_id": "series_a",
            "series_display_order": 1,
            "series_title": "A",
            "series_order": 1,
            "slug": "a1",
        },
        {
            "partition_group_id": "series_a",
            "series_display_order": 1,
            "series_title": "A",
            "series_order": 2,
            "slug": "a2",
        },
        {
            "partition_group_id": "series_b",
            "series_display_order": 2,
            "series_title": "B",
            "series_order": 1,
            "slug": "b1",
        },
        {
            "partition_group_id": "standalone_x",
            "series_display_order": 999,
            "series_title": "Standalone Articles",
            "series_order": None,
            "slug": "x",
        },
    ]
    batch_a, batch_b, _ = partition_by_groups(records, batch_size=2)
    a_groups = {item["partition_group_id"] for item in batch_a}
    b_groups = {item["partition_group_id"] for item in batch_b}
    assert "series_a" in a_groups
    assert "series_a" not in b_groups


def test_partition_fails_when_whole_series_cannot_hit_target() -> None:
    records = [
        {
            "partition_group_id": "series_a",
            "series_display_order": 1,
            "series_title": "A",
            "series_order": i,
            "slug": f"a{i}",
        }
        for i in range(1, 4)
    ] + [
        {
            "partition_group_id": "series_b",
            "series_display_order": 2,
            "series_title": "B",
            "series_order": i,
            "slug": f"b{i}",
        }
        for i in range(1, 4)
    ]
    with pytest.raises(IntegrityError, match="no exact whole-series partition"):
        partition_by_groups(records, batch_size=2)


def test_expected_population_mismatch_fails_closed(
    tmp_path: Path, synthetic_articles: dict[str, bytes]
) -> None:
    with pytest.raises(IntegrityError, match="expected 8 English articles"):
        build_batch(
            repository="example/blog",
            commit="a" * 40,
            expected_count=8,
            batch_size=4,
            output_dir=tmp_path,
            client=FakeClient(synthetic_articles),
        )


def test_heading_parser_ignores_code_fence() -> None:
    text = """---
title: Example
---
# Title
## Visible
text
```md
## Hidden
```
### Also visible
"""
    sections = heading_sections(text, body_start_line=4)
    assert [section["heading"] for section in sections] == ["Visible", "Also visible"]


def test_git_blob_sha_matches_git_object_rule() -> None:
    raw = b"hello\n"
    assert git_blob_sha(raw) == "ce013625030ba8dba906f756967f9e9ca394464a"
