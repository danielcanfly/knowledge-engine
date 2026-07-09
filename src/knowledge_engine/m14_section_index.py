from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .errors import IntegrityError

HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")
SLUG_RE = re.compile(r"[^a-z0-9\u3400-\u9fff]+")


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def _slug(value: str) -> str:
    normalized = SLUG_RE.sub("-", value.lower()).strip("-")
    return normalized or "section"


def _excerpt(value: str, limit: int = 320) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def split_markdown_sections(
    *,
    concept_id: str,
    concept_title: str,
    body: str,
) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current_title = concept_title
    current_lines: list[str] = []
    slugs: dict[str, int] = {}

    def append_current() -> None:
        text = "\n".join(current_lines).strip()
        if not text:
            return
        base = _slug(current_title)
        occurrence = slugs.get(base, 0) + 1
        slugs[base] = occurrence
        suffix = "" if occurrence == 1 else f"-{occurrence}"
        section_slug = f"{base}{suffix}"
        sections.append(
            {
                "section_id": f"{concept_id}#{section_slug}",
                "section_title": current_title,
                "body": text,
                "excerpt": _excerpt(text),
            }
        )

    for line in body.splitlines():
        match = HEADER_RE.match(line)
        if match:
            append_current()
            current_title = match.group(2).strip()
            current_lines = []
            continue
        current_lines.append(line)
    append_current()
    if sections:
        return sections
    fallback = body.strip()
    return [
        {
            "section_id": f"{concept_id}#overview",
            "section_title": concept_title,
            "body": fallback,
            "excerpt": _excerpt(fallback),
        }
    ]


def build_section_documents(
    concepts: list[dict[str, Any]],
    *,
    bundle_root: Path,
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for item in concepts:
        metadata = item["metadata"]
        title = str(metadata["title"])
        description = str(metadata["description"])
        concept_id = str(item["concept_id"])
        sections = split_markdown_sections(
            concept_id=concept_id,
            concept_title=title,
            body=str(item["body"]),
        )
        for section in sections:
            searchable = " ".join(
                (
                    title,
                    title,
                    section["section_title"],
                    section["section_title"],
                    description,
                    section["body"],
                )
            )
            documents.append(
                {
                    "concept_id": concept_id,
                    "section_id": section["section_id"],
                    "x_kos_id": metadata["x-kos-id"],
                    "title": title,
                    "section_title": section["section_title"],
                    "description": description,
                    "excerpt": section["excerpt"],
                    "body": section["body"],
                    "audience": metadata["x-kos-audience"],
                    "path": item["path"].relative_to(bundle_root).as_posix(),
                    "terms": _tokens(searchable),
                }
            )
    documents.sort(key=lambda item: (item["concept_id"], item["section_id"]))
    return documents


def _resolve_link(root: Path, source: Path, raw: str) -> Path | None:
    target = unquote(raw.strip().split()[0].strip("<>"))
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or target.startswith(("mailto:", "tel:")):
        return None
    if not parsed.path or parsed.path.startswith("#"):
        return None
    result = (
        root / parsed.path.lstrip("/")
        if parsed.path.startswith("/")
        else source.parent / parsed.path
    ).resolve()
    try:
        result.relative_to(root.resolve())
    except ValueError as exc:
        raise IntegrityError(f"link escapes bundle: {source}: {raw}") from exc
    return result


def build_graph_edges(
    concepts: list[dict[str, Any]],
    *,
    bundle_root: Path,
) -> list[dict[str, str]]:
    by_path = {item["path"].resolve(): str(item["concept_id"]) for item in concepts}
    edges: set[tuple[str, str]] = set()
    for item in concepts:
        source_id = str(item["concept_id"])
        for raw in LINK_RE.findall(str(item["body"])):
            resolved = _resolve_link(bundle_root, item["path"], raw)
            if resolved is None:
                continue
            target_id = by_path.get(resolved)
            if target_id is None or target_id == source_id:
                continue
            edges.add((source_id, target_id))
    return [
        {
            "from_concept_id": source,
            "to_concept_id": target,
            "type": "links_to",
        }
        for source, target in sorted(edges)
    ]
