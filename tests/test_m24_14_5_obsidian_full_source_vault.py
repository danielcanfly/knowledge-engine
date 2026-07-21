from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path, PurePosixPath

from knowledge_engine.m24_internal_product_deployment import (
    OBSIDIAN_VAULT_ZIP_RELATIVE,
    SITE_ROOT,
    ZIP_TIMESTAMP,
    build_p6_internal_product_deployment,
)
from knowledge_engine.m24_product_surface_integration import canonical_obsidian_export
from knowledge_engine.storage import sha256_bytes

OLD_METADATA_ONLY_VAULT_SHA256 = (
    "e8c84fb521640b0a213615837243f3fb012b85774b3b64ef86da51e8a8a016af"
)
SOURCE_PACKAGE = Path("pilot/m24/source-document-package/source-documents.json")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


def _source_documents() -> dict:
    return json.loads(SOURCE_PACKAGE.read_text(encoding="utf-8"))["documents"]


def _files_by_path() -> dict[str, str]:
    return {item.path: item.content for item in canonical_obsidian_export().files}


def _frontmatter_value(note: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}: (.+)$", note, flags=re.MULTILINE)
    assert match, f"missing frontmatter key {key}"
    return json.loads(match.group(1))


def _source_notes_by_id(files: dict[str, str]) -> dict[str, tuple[str, str]]:
    notes: dict[str, tuple[str, str]] = {}
    for path, content in files.items():
        if path.startswith("sources/") and path.endswith(".md"):
            notes[_frontmatter_value(content, "source_id")] = (path, content)
    return notes


def _concept_notes_by_id(files: dict[str, str]) -> dict[str, tuple[str, str]]:
    notes: dict[str, tuple[str, str]] = {}
    for path, content in files.items():
        if path.startswith("concepts/") and path.endswith(".md"):
            notes[_frontmatter_value(content, "concept_id")] = (path, content)
    return notes


def _fenced_json(note: str) -> dict:
    match = re.search(r"```json\n(.*?)\n```", note, flags=re.DOTALL)
    assert match, "missing fenced json snapshot"
    return json.loads(match.group(1))


def _resolve_wikilinks(markdown_files: dict[str, str]) -> list[tuple[str, str, str]]:
    note_targets = {path[:-3] for path in markdown_files}
    unresolved: list[tuple[str, str, str]] = []
    for source_path, text in markdown_files.items():
        for raw_target in WIKILINK_RE.findall(text):
            target = raw_target.strip().removeprefix("./")
            if target.startswith("../"):
                resolved = (PurePosixPath(source_path).parent / target).as_posix()
                while "/../" in resolved:
                    parts: list[str] = []
                    for part in PurePosixPath(resolved).parts:
                        if part == "..":
                            if parts:
                                parts.pop()
                        elif part != ".":
                            parts.append(part)
                    resolved = "/".join(parts)
            else:
                resolved = target
            if resolved not in note_targets:
                unresolved.append((source_path, raw_target, resolved))
    return unresolved


def test_m24_14_5_canonical_obsidian_export_uses_full_source_package() -> None:
    files = _files_by_path()
    source_docs = _source_documents()
    source_notes = _source_notes_by_id(files)
    concept_notes = _concept_notes_by_id(files)

    assert len(concept_notes) == 20
    assert len(source_notes) == 7
    assert len([doc for doc in source_docs.values() if doc["kind"] == "markdown"]) == 4
    assert len([doc for doc in source_docs.values() if doc["kind"] == "json"]) == 2
    assert len(
        [
            doc
            for doc in source_docs.values()
            if doc["coverage_status"] == "metadata_only_with_reason"
        ]
    ) == 1

    for source_id, source_doc in source_docs.items():
        path, note = source_notes[source_id]
        integrity = source_doc["integrity"]
        origin = source_doc["origin"]
        assert "Raw evidence: `not_exported`" not in note
        assert "## Source metadata" in note
        assert "## Immutable origin identity" in note
        assert "## Integrity identities" in note
        assert "## Related concepts" in note
        assert "## Full source content" in note
        assert "## Citation ledger" in note
        assert f"- Content bytes: `{integrity['byte_count']}`" in note
        assert f"- Line count: `{integrity['line_count']}`" in note
        assert f"- Origin repo: `{origin['repo']}`" in note
        assert f"- Origin commit: `{origin['commit']}`" in note
        assert f"- Origin path: `{origin['path']}`" in note
        assert f"- Origin blob SHA: `{origin['blob_sha']}`" in note
        assert f"- Snapshot SHA-256: `{integrity['snapshot_sha256']}`" in note
        assert f"- Registry SHA: `{source_doc['registry']['source_commit']}`" in note
        assert sha256_bytes(note.encode("utf-8"))
        assert path.startswith("sources/")


def test_m24_14_5_source_notes_preserve_full_markdown_json_and_m3_reason() -> None:
    source_notes = _source_notes_by_id(_files_by_path())
    source_docs = _source_documents()
    deep_markers = {
        "source_blog_agent_architecture_6d": (
            "Multi-agent is an organisational choice, not a maturity level"
        ),
        "source_blog_agent_execution_paths": (
            "Simple requests pay the latency and error surface of planning"
        ),
        "source_blog_agent_planning_strategies": (
            "The production objective is not maximum planning freedom"
        ),
    }

    for source_id, marker in deep_markers.items():
        _, note = source_notes[source_id]
        body = source_docs[source_id]["document"]["body"]
        assert marker in note
        assert body.strip() in note
        assert "excerpt" not in _frontmatter_value(note, "coverage_status")

    harness_note = source_notes["source_m23_4_harness_proposed_concepts"][1]
    assert source_docs["source_m23_4_harness_proposed_concepts"]["document"][
        "body"
    ].strip() in harness_note

    for source_id in (
        "source_m23_4_harness_provenance_summary",
        "source_m24_source_pr_19_decision_capture",
    ):
        _, note = source_notes[source_id]
        assert _fenced_json(note) == json.loads(source_docs[source_id]["document"]["raw_json"])

    m3_note = source_notes["source_m3_contract"][1]
    assert source_docs["source_m3_contract"]["metadata_only_reason"] in m3_note
    assert "metadata_only_exact_reason_preserved" in m3_note
    assert "full native Markdown snapshot begins" not in m3_note


def test_m24_14_5_obsidian_wikilinks_resolve_and_are_bidirectional() -> None:
    files = _files_by_path()
    markdown_files = {path: content for path, content in files.items() if path.endswith(".md")}
    source_docs = _source_documents()
    source_notes = _source_notes_by_id(files)
    concept_notes = _concept_notes_by_id(files)

    assert _resolve_wikilinks(markdown_files) == []

    for source_id, source_doc in source_docs.items():
        source_path, source_note = source_notes[source_id]
        source_target = source_path.removesuffix(".md")
        for concept_id in source_doc.get("related_concepts") or []:
            concept_path, concept_note = concept_notes[concept_id]
            concept_target = concept_path.removesuffix(".md")
            assert f"[[{concept_target}|" in source_note
            assert f"[[{source_target}|" in concept_note
            assert source_doc["title"] in concept_note

    for _, source_note in source_notes.values():
        if "### Citation " in source_note:
            assert re.search(r"Concept ID: \[\[concepts/[^|\]]+\|", source_note)


def test_m24_14_5_vault_zip_is_deterministic_full_source_and_path_safe() -> None:
    build_p6_internal_product_deployment()
    zip_path = SITE_ROOT / OBSIDIAN_VAULT_ZIP_RELATIVE
    first = zip_path.read_bytes()
    build_p6_internal_product_deployment()
    second = zip_path.read_bytes()

    assert first == second
    assert sha256_bytes(second) != OLD_METADATA_ONLY_VAULT_SHA256

    with zipfile.ZipFile(zip_path, "r") as archive:
        assert archive.testzip() is None
        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert names == sorted(names)
        assert len([name for name in names if name.startswith("concepts/")]) == 20
        assert len([name for name in names if name.startswith("sources/")]) == 7
        assert ".obsidian/app.json" in names
        assert "README.md" in names
        assert "manifest.json" in names
        assert all(info.date_time == ZIP_TIMESTAMP for info in infos)
        assert all(info.compress_type == zipfile.ZIP_STORED for info in infos)
        assert all(((info.external_attr >> 16) & 0o777) == 0o644 for info in infos)
        for name in names:
            path = PurePosixPath(name)
            assert not path.is_absolute()
            assert ".." not in path.parts
