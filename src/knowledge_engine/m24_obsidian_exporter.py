from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m14_public_contracts import (
    PublicCitation,
    PublicSearchResponse,
    PublicSearchResult,
    PublicSourceViewer,
)

OBSIDIAN_EXPORT_SCHEMA = "knowledge-engine-m24-obsidian-export/v1"
SOURCE_DOCUMENT_PACKAGE_ROOT = Path("pilot/m24/source-document-package")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class ObsidianExportAuthority(BaseModel):
    retrieval_authority: Literal["lexical"] = "lexical"
    production_retrieval: Literal["lexical"] = "lexical"
    semantic_serving_enabled: bool = False
    semantic_promotion_enabled: bool = False
    hybrid_retrieval_enabled: bool = False
    source_mutation_authorized: bool = False
    raw_evidence_exposed: bool = False


class ObsidianExportFile(BaseModel):
    path: str
    content: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ObsidianExportBundle(BaseModel):
    schema_version: str = OBSIDIAN_EXPORT_SCHEMA
    release_id: str
    request_id: str
    authority: ObsidianExportAuthority
    files: list[ObsidianExportFile]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _compact(value: object, *, limit: int = 240) -> str:
    compact = " ".join(str(value or "").split())
    return compact[: limit - 3].rstrip() + "..." if len(compact) > limit else compact


def _slug(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.casefold()).strip("-")
    if not slug:
        slug = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return slug[:72].strip("-") or "untitled"


def _frontmatter(metadata: dict[str, Any]) -> str:
    lines = ["---"]
    for key in sorted(metadata):
        value = metadata[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        else:
            rendered = json.dumps(value, ensure_ascii=False)
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    return "\n".join(lines)


def _file(path: str, content: str) -> ObsidianExportFile:
    if path.startswith("/") or ".." in path.split("/"):
        raise ValueError(f"unsafe export path: {path}")
    if not (path.endswith(".md") or path == "manifest.json"):
        raise ValueError(f"unsupported export path: {path}")
    normalized = content.rstrip() + "\n"
    return ObsidianExportFile(
        path=path,
        content=normalized,
        content_sha256=_sha256_text(normalized),
    )


def load_source_document_package(
    root: Path = SOURCE_DOCUMENT_PACKAGE_ROOT,
) -> dict[str, Any]:
    return json.loads(root.joinpath("source-documents.json").read_text(encoding="utf-8"))


def _display_title(value: str) -> str:
    return _compact(value, limit=120)


def _markdown_link(path: str, alias: str) -> str:
    return f"[[{path.removesuffix('.md')}|{alias}]]"


def _concept_alias(concept_id: str, concept_titles: dict[str, str]) -> str:
    return _display_title(concept_titles.get(concept_id) or concept_id.removeprefix("concepts/"))


def _source_alias(source_id: str, source_titles: dict[str, str]) -> str:
    return _display_title(source_titles.get(source_id) or source_id)


def _locator(citation: PublicCitation) -> str:
    if citation.locator is None:
        return "not specified"
    values = citation.locator.model_dump(exclude_none=True)
    if not values:
        return "not specified"
    return ", ".join(f"{key}={value}" for key, value in sorted(values.items()))


def _citation_lines(
    citation: PublicCitation,
    *,
    concept_paths: dict[str, str] | None = None,
    concept_titles: dict[str, str] | None = None,
) -> list[str]:
    concept_link = f"`{citation.concept_id}`"
    if concept_paths and citation.concept_id in concept_paths:
        concept_link = _markdown_link(
            concept_paths[citation.concept_id],
            _concept_alias(citation.concept_id, concept_titles or {}),
        )
    lines = [
        f"### Citation {citation.ordinal}",
        "",
        f"- Citation ID: `{citation.citation_id}`",
        f"- Concept ID: {concept_link}",
        f"- Section ID: `{citation.section_id}`",
        f"- Scope: `{citation.citation_scope}`",
        f"- Support: `{citation.support}`",
        f"- Locator: `{_locator(citation)}`",
    ]
    if citation.claim_ids:
        lines.append(
            "- Claim IDs: "
            + ", ".join(f"`{claim_id}`" for claim_id in citation.claim_ids)
        )
    if citation.review_status:
        lines.append(f"- Review status: `{_compact(citation.review_status)}`")
    if citation.derivation_type:
        lines.append(f"- Derivation type: `{_compact(citation.derivation_type)}`")
    return lines


def _citation_index_by_source(
    response: PublicSearchResponse,
) -> dict[str, list[PublicCitation]]:
    indexed: dict[str, list[PublicCitation]] = {}
    for viewer in response.source_viewers:
        indexed.setdefault(viewer.source_card.source_id, []).extend(viewer.citations)
    for citations in indexed.values():
        citations.sort(key=lambda item: item.ordinal)
    return indexed


def _concept_ids_for_source(
    *,
    source_doc: dict[str, Any],
    citations: list[PublicCitation],
) -> list[str]:
    concept_ids = set(source_doc.get("related_concepts") or [])
    concept_ids.update(citation.concept_id for citation in citations)
    return sorted(concept_ids)


def _source_document_metadata(
    *,
    source_doc: dict[str, Any],
    viewer: PublicSourceViewer | None,
) -> dict[str, Any]:
    origin = source_doc.get("origin") or {}
    integrity = source_doc.get("integrity") or {}
    registry = source_doc.get("registry") or {}
    metadata = {
        "schema_version": "knowledge-engine-m24-obsidian-source-note/v2",
        "release_id": source_doc["release_id"],
        "source_id": source_doc["source_id"],
        "source_kind": source_doc["kind"],
        "coverage_status": source_doc["coverage_status"],
        "canonical_uri": source_doc.get("canonical_uri"),
        "retrieval_authority": "lexical",
        "production_retrieval": "lexical",
        "semantic_serving_enabled": False,
        "semantic_promotion_enabled": False,
        "hybrid_retrieval_enabled": False,
        "source_mutation_authorized": False,
        "write_back_authorized": False,
        "raw_evidence_exposed": False,
        "content_bytes": integrity.get("byte_count", 0),
        "line_count": integrity.get("line_count", 0),
        "snapshot_sha256": integrity.get("snapshot_sha256"),
        "origin_repo": origin.get("repo"),
        "origin_commit": origin.get("commit"),
        "origin_path": origin.get("path"),
        "origin_blob_sha": origin.get("blob_sha"),
        "registry_source_repository": registry.get("source_repository"),
        "registry_source_commit": registry.get("source_commit"),
        "registry_content_sha256": registry.get("content_sha256"),
    }
    if viewer is not None:
        metadata["source_card_id"] = viewer.source_card.source_card_id
    return metadata


def _source_document_content_lines(source_doc: dict[str, Any]) -> list[str]:
    document = source_doc.get("document") or {}
    coverage = source_doc["coverage_status"]
    kind = source_doc["kind"]
    if coverage == "metadata_only_with_reason":
        reason = source_doc.get("metadata_only_reason") or document.get(
            "metadata_only_reason"
        )
        return [
            "## Full source content",
            "",
            "- Coverage: `metadata_only_with_reason`",
            f"- Reason: {reason}",
            "- Raw evidence: `metadata_only_exact_reason_preserved`",
        ]
    if kind == "markdown":
        body = document.get("raw_markdown") or document.get("body") or ""
        return [
            "## Full source content",
            "",
            "<!-- full native Markdown snapshot begins -->",
            "",
            body.rstrip(),
            "",
            "<!-- full native Markdown snapshot ends -->",
        ]
    if kind == "json":
        raw_json = document.get("raw_json") or document.get("body") or "{}"
        return [
            "## Full source content",
            "",
            "```json",
            raw_json.rstrip(),
            "```",
        ]
    body = document.get("body") or ""
    return ["## Full source content", "", body.rstrip()]


def _full_source_note(
    *,
    source_doc: dict[str, Any],
    viewer: PublicSourceViewer | None,
    path: str,
    related_concept_ids: list[str],
    citations: list[PublicCitation],
    concept_paths: dict[str, str],
    concept_titles: dict[str, str],
) -> ObsidianExportFile:
    origin = source_doc.get("origin") or {}
    integrity = source_doc.get("integrity") or {}
    registry = source_doc.get("registry") or {}
    title = _display_title(source_doc["title"])
    lines = [
        _frontmatter(_source_document_metadata(source_doc=source_doc, viewer=viewer)),
        "",
        f"# {title}",
        "",
        "## Source metadata",
        "",
        f"- Source ID: `{source_doc['source_id']}`",
        f"- Title: {title}",
        f"- Canonical URI: <{source_doc.get('canonical_uri')}>",
        f"- Kind: `{source_doc['kind']}`",
        f"- Coverage status: `{source_doc['coverage_status']}`",
        f"- Snapshot available: `{str(bool(integrity.get('snapshot_sha256'))).lower()}`",
        f"- Content bytes: `{integrity.get('byte_count', 0)}`",
        f"- Line count: `{integrity.get('line_count', 0)}`",
        "",
        "## Immutable origin identity",
        "",
        f"- Origin repo: `{origin.get('repo')}`",
        f"- Origin commit: `{origin.get('commit')}`",
        f"- Origin path: `{origin.get('path')}`",
        f"- Origin blob SHA: `{origin.get('blob_sha')}`",
        "",
        "## Integrity identities",
        "",
        f"- Snapshot SHA-256: `{integrity.get('snapshot_sha256')}`",
        f"- Browser payload SHA-256: `{integrity.get('browser_payload_sha256')}`",
        f"- Registry repository: `{registry.get('source_repository')}`",
        f"- Registry SHA: `{registry.get('source_commit')}`",
        f"- Registry content SHA-256: `{registry.get('content_sha256')}`",
        f"- Registry content hash scope: `{registry.get('content_hash_scope')}`",
        "- Truncated: `false`",
        "- Executable scripts detected: `false`",
        "",
        "## Related concepts",
        "",
    ]
    if related_concept_ids:
        for concept_id in related_concept_ids:
            concept_path = concept_paths.get(concept_id)
            if concept_path is None:
                lines.append(f"- `{concept_id}`")
            else:
                lines.append(
                    f"- {_markdown_link(concept_path, _concept_alias(concept_id, concept_titles))}"
                )
    else:
        lines.append("- No related release concepts declared.")
    lines.extend([""] + _source_document_content_lines(source_doc))
    lines.extend(["", "## Citation ledger", ""])
    if citations:
        for citation in citations:
            lines.extend(
                _citation_lines(
                    citation,
                    concept_paths=concept_paths,
                    concept_titles=concept_titles,
                )
            )
            lines.append("")
    else:
        lines.append("- No release-pinned citations were attached to this source.")
    return _file(path, "\n".join(lines))


def _source_note(
    *,
    viewer: PublicSourceViewer,
    path: str,
) -> ObsidianExportFile:
    card = viewer.source_card
    metadata = {
        "schema_version": "knowledge-engine-m24-obsidian-source-note/v1",
        "release_id": viewer.release_id,
        "source_card_id": card.source_card_id,
        "source_id": card.source_id,
        "source_kind": card.source_kind,
        "retrieval_authority": "lexical",
        "semantic_serving_enabled": False,
        "raw_evidence_exposed": False,
    }
    lines = [
        _frontmatter(metadata),
        "",
        f"# {_compact(card.title)}",
        "",
        "## Source",
        "",
        f"- URI: <{card.uri}>",
        f"- Publisher: {_compact(card.publisher)}",
        f"- Display host: `{card.display_host}`",
        f"- Retrieved at: `{card.retrieved_at}`",
        f"- Snapshot available: `{str(card.snapshot_available).lower()}`",
        f"- Integrity SHA-256: `{card.integrity_sha256 or 'not_available'}`",
        "",
        "## Provenance",
        "",
        f"- Citation count: `{viewer.summary.citation_count}`",
        f"- Concept count: `{viewer.summary.concept_count}`",
        f"- Claim count: `{viewer.summary.claim_count}`",
        f"- Retrieval authority: `{viewer.summary.retrieval_authority}`",
        "- Semantic serving: `disabled`",
        "- Raw evidence: `not_exported`",
        "",
        "## Citations",
        "",
    ]
    for citation in viewer.citations:
        lines.extend(_citation_lines(citation))
        lines.append("")
    return _file(path, "\n".join(lines))


def _concept_note(
    *,
    result: PublicSearchResult,
    path: str,
    source_paths: dict[str, str],
    source_titles: dict[str, str] | None = None,
    source_ids_by_card_id: dict[str, str] | None = None,
    source_ids_by_concept_id: dict[str, list[str]] | None = None,
) -> ObsidianExportFile:
    metadata = {
        "schema_version": "knowledge-engine-m24-obsidian-concept-note/v1",
        "concept_id": result.concept_id,
        "section_id": result.section_id,
        "retrieval_authority": "lexical",
        "semantic_serving_enabled": False,
        "raw_evidence_exposed": False,
    }
    lines = [
        _frontmatter(metadata),
        "",
        f"# {_compact(result.title)}",
        "",
        "## Section",
        "",
        f"- Section title: {_compact(result.section_title)}",
        f"- Concept ID: `{result.concept_id}`",
        f"- Section ID: `{result.section_id}`",
        f"- Rank: `{result.rank}`",
        f"- Score: `{result.score if result.score is not None else 'not_available'}`",
        "",
        "## Excerpt",
        "",
        _compact(result.excerpt, limit=800) or "No excerpt available.",
        "",
        "## Sources",
        "",
    ]
    linked_source_ids: list[str] = []
    for source_id in (source_ids_by_concept_id or {}).get(result.concept_id, []):
        if source_id not in linked_source_ids:
            linked_source_ids.append(source_id)
    for card_id in result.source_card_ids:
        source_id = (source_ids_by_card_id or {}).get(card_id, card_id)
        if source_id not in linked_source_ids:
            linked_source_ids.append(source_id)
    if linked_source_ids:
        for source_id in linked_source_ids:
            source_path = source_paths.get(source_id)
            if source_path is None:
                continue
            ordinals = ", ".join(str(item) for item in result.citation_ordinals)
            alias = _source_alias(source_id, source_titles or {})
            lines.append(f"- {_markdown_link(source_path, alias)} citations `{ordinals}`")
    else:
        lines.append("- No public source cards available.")
    lines.extend(
        [
            "",
            "## Authority",
            "",
            "- Retrieval authority: `lexical`",
            "- Semantic serving: `disabled`",
            "- Semantic promotion: `disabled`",
        ]
    )
    return _file(path, "\n".join(lines))


def export_search_response_to_obsidian(
    response: PublicSearchResponse,
    *,
    source_documents: dict[str, Any] | None = None,
) -> ObsidianExportBundle:
    authority = ObsidianExportAuthority()
    files: list[ObsidianExportFile] = []
    source_paths: dict[str, str] = {}
    source_titles: dict[str, str] = {}
    source_ids_by_card_id = {
        viewer.source_card.source_card_id: viewer.source_card.source_id
        for viewer in response.source_viewers
    }
    viewers_by_source_id = {
        viewer.source_card.source_id: viewer for viewer in response.source_viewers
    }
    concept_paths = {
        result.concept_id: f"concepts/{index:03d}-{_slug(result.title or result.concept_id)}.md"
        for index, result in enumerate(response.results, start=1)
    }
    concept_titles = {result.concept_id: result.title for result in response.results}
    citations_by_source = _citation_index_by_source(response)
    source_ids_by_concept_id: dict[str, list[str]] = {}

    if source_documents is not None:
        documents = source_documents["documents"]
        for index, (source_id, source_doc) in enumerate(documents.items(), start=1):
            path = f"sources/{index:03d}-{_slug(source_doc['title'] or source_id)}.md"
            source_paths[source_id] = path
            source_titles[source_id] = source_doc["title"]
        for source_id, source_doc in documents.items():
            citations = citations_by_source.get(source_id, [])
            related_concept_ids = _concept_ids_for_source(
                source_doc=source_doc,
                citations=citations,
            )
            for concept_id in related_concept_ids:
                source_ids_by_concept_id.setdefault(concept_id, []).append(source_id)
            files.append(
                _full_source_note(
                    source_doc=source_doc,
                    viewer=viewers_by_source_id.get(source_id),
                    path=source_paths[source_id],
                    related_concept_ids=related_concept_ids,
                    citations=citations,
                    concept_paths=concept_paths,
                    concept_titles=concept_titles,
                )
            )
    else:
        for index, viewer in enumerate(response.source_viewers, start=1):
            card = viewer.source_card
            path = f"sources/{index:03d}-{_slug(card.title or card.source_id)}.md"
            source_paths[card.source_card_id] = path
            source_paths[card.source_id] = path
            source_titles[card.source_id] = card.title
            files.append(_source_note(viewer=viewer, path=path))

    for result in response.results:
        path = concept_paths[result.concept_id]
        files.append(
            _concept_note(
                result=result,
                path=path,
                source_paths=source_paths,
                source_titles=source_titles,
                source_ids_by_card_id=source_ids_by_card_id,
                source_ids_by_concept_id=source_ids_by_concept_id,
            )
        )

    source_document_count = len(source_documents["documents"]) if source_documents else 0
    readme = _file(
        "README.md",
        "\n".join(
            [
                _frontmatter(
                    {
                        "schema_version": "knowledge-engine-m24-obsidian-readme/v1",
                        "release_id": response.release_id,
                        "request_id": response.request_id,
                        "retrieval_authority": "lexical",
                        "semantic_serving_enabled": False,
                    }
                ),
                "",
                "# LLM Wiki Obsidian Export",
                "",
                f"- Release ID: `{response.release_id}`",
                f"- Request ID: `{response.request_id}`",
                f"- Result count: `{len(response.results)}`",
                f"- Source viewer count: `{len(response.source_viewers)}`",
                f"- Source document count: `{source_document_count}`",
                "- Retrieval authority: `lexical`",
                "- Semantic serving: `disabled`",
                "- Source mutation: `not_authorized`",
            ]
        ),
    )
    files.insert(0, readme)

    manifest_payload = {
        "schema_version": f"{OBSIDIAN_EXPORT_SCHEMA}/manifest",
        "release_id": response.release_id,
        "request_id": response.request_id,
        "authority": authority.model_dump(),
        "files": [
            {"path": item.path, "content_sha256": item.content_sha256}
            for item in files
        ],
        "source_document_package": (
            {
                "schema_version": source_documents["schema_version"],
                "source_count": source_documents["source_count"],
                "release_id": source_documents["release_id"],
            }
            if source_documents
            else None
        ),
    }
    manifest = _file("manifest.json", _canonical_json(manifest_payload))
    manifest_sha256 = manifest.content_sha256
    files.append(manifest)
    return ObsidianExportBundle(
        release_id=response.release_id,
        request_id=response.request_id,
        authority=authority,
        files=files,
        manifest_sha256=manifest_sha256,
    )
