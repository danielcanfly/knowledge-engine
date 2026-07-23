from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m25_blog_pilot import (
    GitHubClient,
    TreeBlob,
    build_batch,
    git_blob_sha,
    heading_sections,
    partition_by_groups,
)


class FakeClient(GitHubClient):
    def __init__(self, articles: dict[str, bytes]) -> None:
        self.articles = articles
        self.by_sha = {git_blob_sha(value): value for value in articles.values()}

    def tree(self, repository: str, commit: str) -> list[TreeBlob]:
        del repository, commit
        return [
            TreeBlob(path=path, sha=git_blob_sha(raw), size=len(raw))
            for path, raw in self.articles.items()
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


def test_partition_never_splits_real_series() -> None:
    records = [
        {"partition_group_id": "series_a", "series_title": "A", "series_order": 1, "slug": "a1"},
        {"partition_group_id": "series_a", "series_title": "A", "series_order": 2, "slug": "a2"},
        {"partition_group_id": "series_b", "series_title": "B", "series_order": 1, "slug": "b1"},
        {
            "partition_group_id": "standalone_x",
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
        {"partition_group_id": "series_a", "series_title": "A", "series_order": i, "slug": f"a{i}"}
        for i in range(1, 4)
    ] + [
        {"partition_group_id": "series_b", "series_title": "B", "series_order": i, "slug": f"b{i}"}
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
