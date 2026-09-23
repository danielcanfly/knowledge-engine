from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from knowledge_engine import m25_blog_candidate_release as subject
from knowledge_engine.errors import IntegrityError


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_stable_kos_is_deterministic_and_valid() -> None:
    first = subject._stable_kos("article_example")
    assert first == subject._stable_kos("article_example")
    assert first.startswith("ko_")
    assert len(first) == 29


def test_body_lines_enforces_exact_locator() -> None:
    raw = b"one\ntwo\nthree\n"
    assert subject._body_lines(raw, 2, 3) == "two\nthree"
    with pytest.raises(IntegrityError, match="locator"):
        subject._body_lines(raw, 0, 2)


def test_validate_pack_rejects_authority_digest_drift(tmp_path: Path) -> None:
    admission = {
        "schema_version": subject.PACK_SCHEMA,
        "production_pointer_authorized": False,
        "source_write_authorized": True,
        "candidate_release_authorized": True,
    }
    unsigned = json.dumps(
        admission,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    admission["admission_sha256"] = hashlib.sha256(unsigned).hexdigest()
    _write_json(tmp_path / "admission.json", admission)
    with pytest.raises(IntegrityError, match="authority digest"):
        subject.validate_pack(tmp_path)


def test_candidate_channel_must_be_isolated(tmp_path: Path) -> None:
    with pytest.raises(IntegrityError, match="candidate channel"):
        subject.deploy_candidate(
            source_url="file:///tmp/source",
            source_sha="a" * 40,
            foundation_sha="b" * 40,
            channel="production",
            work_dir=tmp_path,
            release_time=subject.datetime(2026, 7, 24, tzinfo=subject.UTC),
            allow_live=False,
        )


def test_semantic_population_contract_is_article_plus_section() -> None:
    assert subject.COUNTS["semantic_documents"] == (
        subject.COUNTS["articles"] + subject.COUNTS["sections"]
    )
    assert subject.COUNTS["nodes"] == (
        subject.COUNTS["series"]
        + subject.COUNTS["articles"]
        + subject.COUNTS["sections"]
    )


def test_source_backed_description_restores_frontmatter_authority() -> None:
    article = {
        "title": "Harness Theory Part 09",
        "description": "Harness Theory Part 09",
        "origin_path": "src/content/blog/harness-theory-part-9/en.md",
    }
    raw = (
        b"---\n"
        b"title: Harness Theory Part 09\n"
        b"description: An agent harness confines autonomous action to authorised boundaries.\n"
        b"---\n\n"
        b"Body.\n"
    )

    assert subject._source_backed_description(article, raw) == (
        "An agent harness confines autonomous action to authorised boundaries."
    )


def test_source_backed_description_falls_back_to_inventory_when_source_has_none() -> None:
    article = {
        "title": "Article title",
        "description": "Inventory summary",
        "origin_path": "src/content/blog/example.md",
    }
    raw = b"---\ntitle: Article title\n---\n\nBody.\n"

    assert subject._source_backed_description(article, raw) == "Inventory summary"


def test_section_search_description_does_not_inherit_source_frontmatter() -> None:
    article = {
        "title": "Harness Theory Part 09",
        "description": "Harness Theory Part 09",
        "origin_path": "src/content/blog/harness-theory-part-9/en.md",
    }

    assert subject._section_search_description(article) == "Harness Theory Part 09"



def test_build_pack_artifacts_uses_supplied_pack_id() -> None:
    raw = (
        b"---\n"
        b"title: Example\n"
        b"description: Example description\n"
        b"---\n"
        b"\n"
        b"## Section\n"
        b"Body text.\n"
    )
    article = {
        "article_id": "source_example",
        "slug": "example",
        "title": "Example",
        "description": "Example description",
        "canonical_url": "https://example.test/example/",
        "series_id": "series_example",
        "series_title": "Example Series",
        "origin_repository": "owner/repo",
        "origin_commit": "a" * 40,
        "origin_path": "src/content/blog/example/en.md",
        "origin_blob_sha": "b" * 40,
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "owner": "Daniel Huang",
        "license": "owner-provided",
        "trust": "author-authored",
    }
    pack = {
        "article_by_id": {"source_example": article},
        "source_bytes": {"source_example": raw},
        "nodes": [
            {
                "node_id": "series_node",
                "node_type": "Series",
                "title": "Example Series",
            },
            {
                "node_id": "article_node",
                "node_type": "Article",
                "source_article_id": "source_example",
                "title": "Example",
            },
            {
                "node_id": "section_node",
                "node_type": "Section",
                "source_article_id": "source_example",
                "parent_article_node_id": "article_node",
                "title": "Section",
                "source_locator": {"start_line": 6, "end_line": 7},
                "content_sha256": hashlib.sha256(b"## Section\nBody text.").hexdigest(),
            },
        ],
        "edges": [],
    }

    artifacts = subject.build_pack_artifacts(
        pack,
        "candidate-release",
        expected_semantic_documents=2,
        pack_id="daniel-blog-en-180-test",
    )

    assert artifacts["source_index"][0]["path"] == (
        "_documents/daniel-blog-en-180-test/sources/example.md"
    )
    section_graph_node = next(
        item for item in artifacts["graph_v2_nodes"] if item["concept_id"] == "section_node"
    )
    assert section_graph_node["path"] == (
        "_documents/daniel-blog-en-180-test/sources/example.md"
    )
    series_graph_node = next(
        item for item in artifacts["graph_v2_nodes"] if item["concept_id"] == "series_node"
    )
    assert series_graph_node["path"] == (
        "_documents/daniel-blog-en-180-test/master-inventory.json"
    )
