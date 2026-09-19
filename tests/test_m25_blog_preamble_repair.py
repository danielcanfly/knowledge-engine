from __future__ import annotations

from knowledge_engine.m25_blog_pilot import (
    build_nodes_and_edges,
    heading_sections,
    preamble_section,
    sha256,
    stable_id,
)


def _record(slug: str, title: str = "Example") -> tuple[dict[str, object], bytes]:
    raw = (
        "---\n"
        f"title: {title}\n"
        "draft: false\n"
        "---\n"
        "# Example\n"
        "\n"
        "Opening prose has enough words for eligibility.\n"
        "\n"
        "Second opening paragraph remains in the same source span.\n"
        "\n"
        "## Existing heading\n"
        "\n"
        "Existing section body.\n"
    ).encode()
    record: dict[str, object] = {
        "article_id": f"article__{slug}",
        "slug": slug,
        "title": title,
        "series_id": "series_example",
        "series_title": "Example Series",
        "series_order": 1,
        "canonical_url": f"https://example.test/{slug}",
        "origin_repository": "example/repository",
        "origin_commit": "a" * 40,
        "origin_path": f"src/content/blog/{slug}/en.md",
        "content_sha256": sha256(raw),
        "body_start_line": 5,
    }
    return record, raw


def _sections(nodes: list[dict[str, object]]) -> list[dict[str, object]]:
    return [node for node in nodes if node["node_type"] == "Section"]


def test_preamble_emits_one_exact_source_backed_span() -> None:
    record, raw = _record("opening")
    text = raw.decode()
    preamble = preamble_section(text, 5)
    assert preamble is not None
    assert preamble["start_line"] == 5
    assert preamble["end_line"] == 10
    expected = "".join(text.splitlines(keepends=True)[4:10])
    assert preamble["content"] == expected
    assert preamble["content_sha256"] == sha256(expected)
    nodes, _edges = build_nodes_and_edges([record], {"opening": raw})
    sections = _sections(nodes)
    assert len(sections) == 2
    assert sum(node.get("section_role") == "preamble" for node in sections) == 1


def test_no_heading_article_emits_deterministic_preamble() -> None:
    record, raw = _record("no-heading")
    raw = raw.replace(b"## Existing heading\n\nExisting section body.\n", b"")
    record["content_sha256"] = sha256(raw)
    record["body_start_line"] = 5
    first_nodes, first_edges = build_nodes_and_edges([record], {"no-heading": raw})
    second_nodes, second_edges = build_nodes_and_edges([record], {"no-heading": raw})
    sections = _sections(first_nodes)
    assert len(sections) == 1
    assert sections[0]["section_role"] == "preamble"
    assert first_nodes == second_nodes
    assert first_edges == second_edges


def test_non_prose_openings_do_not_emit_preamble() -> None:
    cases = (
        "# Heading only\n\n## Existing\nbody\n",
        "    indented code only\n    still code\n\n## Existing\nbody\n",
        "```md\n## Hidden\n```\n\n## Existing\nbody\n",
        "<aside>\n<div>metadata</div>\n</aside>\n\n## Existing\nbody\n",
    )
    for opening in cases:
        text = "---\ntitle: Example\n---\n" + opening
        assert preamble_section(text, 4) is None


def test_fenced_heading_does_not_create_false_boundary() -> None:
    text = (
        "---\ntitle: Example\n---\n"
        "# Example\n\n"
        "```md\n## Hidden\n```\n\n"
        "Opening prose remains after the fenced example.\n\n"
        "## Visible\nBody.\n"
    )
    preamble = preamble_section(text, 4)
    assert preamble is not None
    assert "## Hidden" in preamble["content"]
    assert preamble["end_line"] == 11


def test_legacy_heading_sections_and_ids_do_not_shift() -> None:
    record, raw = _record("identity")
    text = raw.decode()
    legacy = heading_sections(text, 5)
    expected_ids = [
        stable_id(
            "section",
            record["article_id"],
            str(ordinal),
            section["heading"],
            section["content_sha256"],
        )
        for ordinal, section in enumerate(legacy, start=1)
    ]
    nodes, _edges = build_nodes_and_edges([record], {"identity": raw})
    actual = {
        node["node_id"]: node
        for node in _sections(nodes)
        if node.get("section_role") != "preamble"
    }
    assert set(actual) == set(expected_ids)
    assert [actual[node_id]["source_locator"] for node_id in expected_ids] == [
        {
            "origin_repository": record["origin_repository"],
            "origin_commit": record["origin_commit"],
            "origin_path": record["origin_path"],
            "start_line": section["start_line"],
            "end_line": section["end_line"],
        }
        for section in legacy
    ]
