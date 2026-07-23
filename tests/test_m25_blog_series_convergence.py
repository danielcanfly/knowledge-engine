from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m25_blog_pilot import SERIES_META_PATH, GitHubClient, TreeBlob, git_blob_sha
from knowledge_engine.m25_blog_series_convergence import (
    build_catalog_label_index,
    build_converged_batch,
    converge_series_aliases,
)

CATALOG = b"""const SERIES = [
  { slug: /^from-rag-part-\\d+$/, key: 'from-rag', order: 1,
    labelZh: '1. RAG ZH', labelEn: '1. From RAG to Enterprise-Grade RAG' },
  { slug: /^other-\\d+$/, key: 'other', order: 2,
    labelZh: '2. Other ZH', labelEn: '2. Other Series' },
];
"""


class FakeClient(GitHubClient):
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.files[SERIES_META_PATH] = CATALOG
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


def article(slug: str, title: str, series: str | None = None) -> tuple[str, bytes]:
    lines = ["---", f"title: {json.dumps(title)}", "draft: false"]
    if series:
        lines.append(f"series: {json.dumps(series)}")
    lines.extend(["---", "", f"# {title}", "", "## Section", "", "Body."])
    return f"src/content/blog/{slug}/en.md", ("\n".join(lines) + "\n").encode()


def test_explicit_appendix_title_converges_to_catalog_key() -> None:
    records = [
        {
            "series_key": "from-rag",
            "series_id": "series_from-rag",
            "series_title": "From RAG to Enterprise-Grade RAG",
            "partition_group_id": "series_from-rag",
            "series_resolution_source": "series_catalog_fallback",
            "record_sha256": "0" * 64,
        },
        {
            "series_key": "from-rag-to-enterprise-grade-rag",
            "series_id": "series_from-rag-to-enterprise-grade-rag",
            "series_title": "From RAG to Enterprise-Grade RAG",
            "partition_group_id": "series_from-rag-to-enterprise-grade-rag",
            "series_resolution_source": "frontmatter",
            "record_sha256": "1" * 64,
        },
    ]
    catalog = [
        {
            "key": "from-rag",
            "label_en_clean": "From RAG to Enterprise-Grade RAG",
        }
    ]
    clean, count = converge_series_aliases(records, catalog)
    assert count == 1
    assert {item["series_id"] for item in clean} == {"series_from-rag"}
    assert clean[1]["series_resolution_source"] == "frontmatter_catalog_label_alias"


def test_catalog_label_collision_fails_closed() -> None:
    catalog = [
        {"key": "a", "label_en_clean": "Same Series"},
        {"key": "b", "label_en_clean": "Same Series"},
    ]
    with pytest.raises(IntegrityError, match="multiple keys"):
        build_catalog_label_index(catalog)


def test_converged_batch_has_one_series_node_per_title(tmp_path: Path) -> None:
    files = dict(
        [
            article("from-rag-part-1", "Part 1"),
            article(
                "from-rag-appendix-a",
                "Appendix A",
                series="From RAG to Enterprise-Grade RAG",
            ),
            article("other-1", "Other 1"),
            article("standalone", "Standalone"),
        ]
    )
    receipt = build_converged_batch(
        repository="example/blog",
        commit="a" * 40,
        expected_count=4,
        batch_size=2,
        output_dir=tmp_path,
        client=FakeClient(files),
    )
    master = json.loads((tmp_path / "master-inventory.json").read_text())
    title_to_ids: dict[str, set[str]] = {}
    for record in master["articles"]:
        title_to_ids.setdefault(record["series_title"], set()).add(record["series_id"])
    assert all(len(ids) == 1 for ids in title_to_ids.values())
    assert master["formal_series_count"] == 2
    assert master["parent_collection_count"] == 3
    assert master["series_alias_convergence_count"] == 1
    assert receipt["series_alias_convergence_count"] == 1
