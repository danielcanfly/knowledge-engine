from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.knowledge_engine.errors import IntegrityError
from src.knowledge_engine.graph_v2 import compile_graph_v2


def concept(root: Path, name: str, audience: str = "public", **metadata: object) -> dict:
    path = root / "concepts" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n---\n", encoding="utf-8")
    base = {
        "x-kos-id": "ko_01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "title": name.title(),
        "description": f"{name} description",
        "type": "Concept",
        "x-kos-audience": audience,
        "x-kos-status": "published",
        "x-kos-confidence": 0.9,
        "x-kos-provenance": f"provenance/{name}.json",
    }
    base.update(metadata)
    return {"concept_id": f"concepts/{name}", "metadata": base, "path": path}


def profile(root: Path) -> None:
    path = root / "_meta" / "graph-profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"authoring_relation_types": [
        {"type": "uses", "direction": "directed", "inverse": "used_by"},
        {"type": "contrasts_with", "direction": "undirected", "inverse": "contrasts_with"},
    ]}), encoding="utf-8")


def compile(root: Path, concepts: list[dict]) -> dict:
    profile(root)
    return compile_graph_v2(
        concepts,
        bundle_root=root,
        release_id="release_test",
        source_commit_sha="a" * 40,
        foundation_commit_sha="b" * 40,
        content_sha256="c" * 64,
    )


def test_zero_relation_graph_is_deterministic_and_renderer_neutral(tmp_path: Path) -> None:
    concepts = [concept(tmp_path, "one"), concept(tmp_path, "two")]
    first = compile(tmp_path, concepts)
    second = compile(tmp_path, list(reversed(concepts)))
    assert first == second
    assert first["schema_version"] == "knowledge-os-graph/v2"
    assert first["edges"] == []
    assert all(set(node).isdisjoint({"x", "y", "color", "size"}) for node in first["nodes"])


def test_directed_relation_emits_deterministic_inverse_and_acl(tmp_path: Path) -> None:
    relation = {
        "target": "concepts/two", "type": "uses", "direction": "directed",
        "confidence": 0.8, "qualifiers": {"context": "runtime"},
        "provenance": {"record": "provenance/one.json", "claim_id": "claim_one"},
        "review": {"status": "approved", "review_id": "review_one"},
    }
    concepts = [
        concept(tmp_path, "one", **{"x-kos-relations": [relation]}),
        concept(tmp_path, "two", audience="internal"),
    ]
    graph = compile(tmp_path, concepts)
    assert len(graph["edges"]) == 2
    assert {edge["relation_type"] for edge in graph["edges"]} == {"uses", "used_by"}
    assert {edge["audience"] for edge in graph["edges"]} == {"internal"}
    assert sum(edge["generated_inverse"] for edge in graph["edges"]) == 1


def test_missing_target_fails_closed(tmp_path: Path) -> None:
    relation = {
        "target": "concepts/missing", "type": "uses", "direction": "directed",
        "confidence": 0.8, "provenance": {}, "review": {},
    }
    with pytest.raises(IntegrityError, match="missing relation target"):
        compile(tmp_path, [concept(tmp_path, "one", **{"x-kos-relations": [relation]})])


def test_alias_collision_fails_closed(tmp_path: Path) -> None:
    concepts = [
        concept(tmp_path, "one", **{"x-kos-aliases": ["Shared Name"]}),
        concept(tmp_path, "two", **{"x-kos-aliases": ["shared   name"]}),
    ]
    with pytest.raises(IntegrityError, match="ambiguous graph v2 alias"):
        compile(tmp_path, concepts)


def test_renderer_field_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(IntegrityError, match="renderer-specific"):
        compile(tmp_path, [concept(tmp_path, "one", sigma_color="red")])
