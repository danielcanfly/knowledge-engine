from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m14_public_contracts import (
    PublicCitation,
    PublicSearchResponse,
    PublicSearchResult,
    PublicSourceViewer,
)

OBSIDIAN_EXPORT_SCHEMA = "knowledge-engine-m24-obsidian-export/v1"
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


def _locator(citation: PublicCitation) -> str:
    if citation.locator is None:
        return "not specified"
    values = citation.locator.model_dump(exclude_none=True)
    if not values:
        return "not specified"
    return ", ".join(f"{key}={value}" for key, value in sorted(values.items()))


def _citation_lines(citation: PublicCitation) -> list[str]:
    lines = [
        f"### Citation {citation.ordinal}",
        "",
        f"- Citation ID: `{citation.citation_id}`",
        f"- Concept ID: `{citation.concept_id}`",
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
    if result.source_card_ids:
        for card_id in result.source_card_ids:
            source_path = source_paths.get(card_id)
            if source_path is None:
                continue
            target = source_path.removesuffix(".md")
            ordinals = ", ".join(str(item) for item in result.citation_ordinals)
            lines.append(f"- [[{target}|{card_id}]] citations `{ordinals}`")
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
) -> ObsidianExportBundle:
    authority = ObsidianExportAuthority()
    files: list[ObsidianExportFile] = []
    source_paths: dict[str, str] = {}

    for index, viewer in enumerate(response.source_viewers, start=1):
        card = viewer.source_card
        path = f"sources/{index:03d}-{_slug(card.title or card.source_id)}.md"
        source_paths[card.source_card_id] = path
        files.append(_source_note(viewer=viewer, path=path))

    for index, result in enumerate(response.results, start=1):
        path = f"concepts/{index:03d}-{_slug(result.title or result.concept_id)}.md"
        files.append(_concept_note(result=result, path=path, source_paths=source_paths))

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
