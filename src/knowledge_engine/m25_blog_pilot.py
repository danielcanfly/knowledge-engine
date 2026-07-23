from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .errors import IntegrityError

SCHEMA_VERSION = "knowledge-engine-m25-9-blog-pilot/v1"
ARTICLE_PATH_RE = re.compile(r"^src/content/blog/([^/]+)/en\.md$")
HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
SLUG_RE = re.compile(r"[^a-z0-9]+")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256(value: bytes | str | Any) -> str:
    if isinstance(value, bytes):
        data = value
    elif isinstance(value, str):
        data = value.encode("utf-8")
    else:
        data = canonical_bytes(value)
    return hashlib.sha256(data).hexdigest()


def sign(value: dict[str, Any], field: str) -> dict[str, Any]:
    output = json.loads(json.dumps(value))
    output.pop(field, None)
    output[field] = sha256(output)
    return output


def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "untitled"


def stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts))[:20]
    return f"{prefix}_{digest}"


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default, ensure_ascii=False))


@dataclass(frozen=True)
class TreeBlob:
    path: str
    sha: str
    size: int


class GitHubClient:
    def __init__(self, token: str | None = None, *, timeout: int = 30) -> None:
        self.token = token
        self.timeout = timeout

    def _request_json(self, url: str) -> dict[str, Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "knowledge-engine-m25-blog-pilot",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise IntegrityError("M25-BLOG-001 GitHub returned a non-object")
                return payload
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise IntegrityError(f"M25-BLOG-002 GitHub HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
            time.sleep(2**attempt)
        raise IntegrityError("M25-BLOG-003 GitHub request exhausted retries") from last_error

    def tree(self, repository: str, commit: str) -> list[TreeBlob]:
        url = f"https://api.github.com/repos/{repository}/git/trees/{commit}?recursive=1"
        payload = self._request_json(url)
        if payload.get("truncated") is True:
            raise IntegrityError("M25-BLOG-004 recursive Git tree was truncated")
        entries = payload.get("tree")
        if not isinstance(entries, list):
            raise IntegrityError("M25-BLOG-005 Git tree missing")
        blobs: list[TreeBlob] = []
        for item in entries:
            if not isinstance(item, dict) or item.get("type") != "blob":
                continue
            path = item.get("path")
            digest = item.get("sha")
            size = item.get("size")
            if isinstance(path, str) and isinstance(digest, str) and isinstance(size, int):
                blobs.append(TreeBlob(path=path, sha=digest, size=size))
        return blobs

    def blob(self, repository: str, blob_sha: str) -> bytes:
        url = f"https://api.github.com/repos/{repository}/git/blobs/{blob_sha}"
        payload = self._request_json(url)
        if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
            raise IntegrityError("M25-BLOG-006 unsupported Git blob encoding")
        try:
            data = base64.b64decode(payload["content"], validate=False)
        except ValueError as exc:
            raise IntegrityError("M25-BLOG-007 invalid Git blob payload") from exc
        if git_blob_sha(data) != blob_sha:
            raise IntegrityError("M25-BLOG-008 Git blob identity mismatch")
        return data


def parse_frontmatter(raw: bytes, *, path: str) -> tuple[dict[str, Any], str, int]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntegrityError(f"M25-BLOG-009 non-UTF-8 article: {path}") from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise IntegrityError(f"M25-BLOG-010 missing frontmatter: {path}")
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        raise IntegrityError(f"M25-BLOG-011 unterminated frontmatter: {path}")
    try:
        metadata = yaml.safe_load("\n".join(lines[1:closing])) or {}
    except yaml.YAMLError as exc:
        raise IntegrityError(f"M25-BLOG-012 invalid frontmatter: {path}") from exc
    if not isinstance(metadata, dict):
        raise IntegrityError(f"M25-BLOG-013 frontmatter is not an object: {path}")
    return json_safe(metadata), text, closing + 2


def _series_order(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("seriesOrder", metadata.get("series_order"))
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise IntegrityError("M25-BLOG-014 invalid series order") from exc


def build_article_record(
    *,
    repository: str,
    commit: str,
    tree_blob: TreeBlob,
    raw: bytes,
) -> dict[str, Any]:
    match = ARTICLE_PATH_RE.fullmatch(tree_blob.path)
    if match is None:
        raise IntegrityError("M25-BLOG-015 unexpected article path")
    slug = match.group(1)
    metadata, text, body_start_line = parse_frontmatter(raw, path=tree_blob.path)
    title = metadata.get("title")
    if not isinstance(title, str) or not title.strip():
        raise IntegrityError(f"M25-BLOG-016 article title missing: {tree_blob.path}")
    draft = metadata.get("draft", False)
    if draft is not False:
        raise IntegrityError(f"M25-BLOG-017 draft article entered population: {tree_blob.path}")
    series_title = metadata.get("series")
    if series_title is not None and not isinstance(series_title, str):
        raise IntegrityError(f"M25-BLOG-018 invalid series title: {tree_blob.path}")
    series_title = series_title.strip() if isinstance(series_title, str) else ""
    series_id = f"series_{slugify(series_title)}" if series_title else "series_standalone"
    partition_group_id = series_id if series_title else f"standalone_{slug}"
    published = metadata.get("pubDate", metadata.get("published_at", metadata.get("date")))
    categories = metadata.get("categories", metadata.get("category", []))
    if isinstance(categories, str):
        categories = [categories]
    if not isinstance(categories, list):
        categories = []
    tags = metadata.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        tags = []
    record = {
        "article_id": f"daniel_blog_en__{slug}",
        "slug": slug,
        "language": "en",
        "title": title.strip(),
        "description": metadata.get("description"),
        "series_id": series_id,
        "series_title": series_title or "Standalone Articles",
        "series_order": _series_order(metadata),
        "partition_group_id": partition_group_id,
        "published_at": json_safe(published),
        "categories": sorted(str(item) for item in categories),
        "tags": sorted(str(item) for item in tags),
        "canonical_url": f"https://danielcanfly.com/en/blog/{slug}/",
        "origin_repository": repository,
        "origin_commit": commit,
        "origin_path": tree_blob.path,
        "origin_blob_sha": tree_blob.sha,
        "content_sha256": sha256(raw),
        "content_bytes": len(raw),
        "body_start_line": body_start_line,
        "license": "owner-provided",
        "owner": "Daniel Huang",
        "audience": "public",
        "trust": "author-authored",
        "terminal_acquisition_state": "acquired_verified",
    }
    record["record_sha256"] = sha256(record)
    return record


def partition_by_groups(
    records: list[dict[str, Any]], *, batch_size: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["partition_group_id"]].append(record)
    ordered = sorted(groups.items(), key=lambda item: item[0])
    choices: dict[int, tuple[int, ...]] = {0: ()}
    for index, (_, members) in enumerate(ordered):
        size = len(members)
        snapshot = dict(choices)
        for subtotal, selected in snapshot.items():
            total = subtotal + size
            candidate = selected + (index,)
            if total <= batch_size and (
                total not in choices or candidate < choices[total]
            ):
                choices[total] = candidate
    if batch_size not in choices:
        counts = {group: len(members) for group, members in ordered}
        raise IntegrityError(
            "M25-BLOG-019 no exact whole-series partition for requested batch size: "
            + json.dumps(counts, sort_keys=True)
        )
    selected_indices = set(choices[batch_size])
    selected_groups = [ordered[index][0] for index in choices[batch_size]]
    batch_a: list[dict[str, Any]] = []
    batch_b: list[dict[str, Any]] = []
    for index, (_, members) in enumerate(ordered):
        target = batch_a if index in selected_indices else batch_b
        target.extend(members)

    def sort_key(item: dict[str, Any]) -> tuple[str, int, str]:
        return (
            item["series_title"].casefold(),
            item["series_order"] if item["series_order"] is not None else 10**9,
            item["slug"],
        )

    return sorted(batch_a, key=sort_key), sorted(batch_b, key=sort_key), selected_groups


def heading_sections(text: str, body_start_line: int) -> list[dict[str, Any]]:
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []
    in_fence = False
    fence_token = ""
    for index, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            token = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_token = token
            elif token == fence_token:
                in_fence = False
                fence_token = ""
            continue
        if in_fence or index < body_start_line:
            continue
        match = HEADING_RE.match(line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))
    sections: list[dict[str, Any]] = []
    for position, (line_no, level, heading) in enumerate(headings):
        end_line = headings[position + 1][0] - 1 if position + 1 < len(headings) else len(lines)
        content = "\n".join(lines[line_no - 1 : end_line]).strip() + "\n"
        sections.append(
            {
                "heading": heading,
                "heading_level": level,
                "start_line": line_no,
                "end_line": end_line,
                "content_sha256": sha256(content),
            }
        )
    return sections


def build_nodes_and_edges(
    records: list[dict[str, Any]],
    raw_by_slug: dict[str, bytes],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    series_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        series_members[record["series_id"]].append(record)
    for series_id, members in sorted(series_members.items()):
        series_title = members[0]["series_title"]
        node_id = stable_id("series", series_id)
        nodes.append(
            {
                "node_id": node_id,
                "node_type": "Series",
                "title": series_title,
                "status": "candidate_structural",
                "source_article_ids": [item["article_id"] for item in members],
                "content_sha256": sha256(
                    {"series_id": series_id, "articles": [item["article_id"] for item in members]}
                ),
            }
        )
    series_node_ids = {
        node["title"]: node["node_id"] for node in nodes if node["node_type"] == "Series"
    }
    article_node_ids: dict[str, str] = {}
    for record in records:
        article_node_id = stable_id("article", record["article_id"], record["content_sha256"])
        article_node_ids[record["article_id"]] = article_node_id
        nodes.append(
            {
                "node_id": article_node_id,
                "node_type": "Article",
                "title": record["title"],
                "status": "candidate_structural",
                "source_article_id": record["article_id"],
                "series_id": record["series_id"],
                "series_order": record["series_order"],
                "canonical_url": record["canonical_url"],
                "source_locator": {
                    "origin_repository": record["origin_repository"],
                    "origin_commit": record["origin_commit"],
                    "origin_path": record["origin_path"],
                    "start_line": record["body_start_line"],
                    "end_line": len(raw_by_slug[record["slug"]].decode("utf-8").splitlines()),
                },
                "content_sha256": record["content_sha256"],
            }
        )
        series_node_id = series_node_ids[record["series_title"]]
        edges.extend(
            [
                {
                    "edge_id": stable_id("edge", article_node_id, "part_of", series_node_id),
                    "source": article_node_id,
                    "target": series_node_id,
                    "type": "part_of",
                    "status": "candidate_structural",
                },
                {
                    "edge_id": stable_id("edge", series_node_id, "contains", article_node_id),
                    "source": series_node_id,
                    "target": article_node_id,
                    "type": "contains",
                    "status": "candidate_structural",
                },
            ]
        )
        text = raw_by_slug[record["slug"]].decode("utf-8")
        for ordinal, section in enumerate(
            heading_sections(text, record["body_start_line"]), start=1
        ):
            section_node_id = stable_id(
                "section",
                record["article_id"],
                str(ordinal),
                section["heading"],
                section["content_sha256"],
            )
            nodes.append(
                {
                    "node_id": section_node_id,
                    "node_type": "Section",
                    "title": section["heading"],
                    "status": "candidate_structural",
                    "source_article_id": record["article_id"],
                    "parent_article_node_id": article_node_id,
                    "heading_level": section["heading_level"],
                    "source_locator": {
                        "origin_repository": record["origin_repository"],
                        "origin_commit": record["origin_commit"],
                        "origin_path": record["origin_path"],
                        "start_line": section["start_line"],
                        "end_line": section["end_line"],
                    },
                    "content_sha256": section["content_sha256"],
                }
            )
            edges.extend(
                [
                    {
                        "edge_id": stable_id(
                            "edge", section_node_id, "part_of", article_node_id
                        ),
                        "source": section_node_id,
                        "target": article_node_id,
                        "type": "part_of",
                        "status": "candidate_structural",
                    },
                    {
                        "edge_id": stable_id(
                            "edge", article_node_id, "contains", section_node_id
                        ),
                        "source": article_node_id,
                        "target": section_node_id,
                        "type": "contains",
                        "status": "candidate_structural",
                    },
                ]
            )
    for series_id, members in sorted(series_members.items()):
        ordered_members = sorted(
            members,
            key=lambda item: (
                item["series_order"] if item["series_order"] is not None else 10**9,
                item["slug"],
            ),
        )
        for current, following in zip(ordered_members, ordered_members[1:], strict=False):
            source_id = article_node_ids[current["article_id"]]
            target_id = article_node_ids[following["article_id"]]
            edges.append(
                {
                    "edge_id": stable_id("edge", source_id, "precedes", target_id),
                    "source": source_id,
                    "target": target_id,
                    "type": "precedes",
                    "status": "candidate_structural",
                    "series_id": series_id,
                }
            )
    nodes.sort(key=lambda item: item["node_id"])
    edges.sort(key=lambda item: item["edge_id"])
    return nodes, edges


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for value in values:
            handle.write(json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n")


def build_batch(
    *,
    repository: str,
    commit: str,
    expected_count: int,
    batch_size: int,
    output_dir: Path,
    client: GitHubClient,
) -> dict[str, Any]:
    if expected_count != batch_size * 2:
        raise IntegrityError("M25-BLOG-020 expected count must equal two equal batches")
    article_blobs = [
        blob for blob in client.tree(repository, commit) if ARTICLE_PATH_RE.fullmatch(blob.path)
    ]
    article_blobs.sort(key=lambda item: item.path)
    if len(article_blobs) != expected_count:
        raise IntegrityError(
            f"M25-BLOG-021 expected {expected_count} English articles, found {len(article_blobs)}"
        )
    records: list[dict[str, Any]] = []
    raw_by_slug: dict[str, bytes] = {}
    for tree_blob in article_blobs:
        raw = client.blob(repository, tree_blob.sha)
        record = build_article_record(
            repository=repository, commit=commit, tree_blob=tree_blob, raw=raw
        )
        if record["slug"] in raw_by_slug:
            raise IntegrityError("M25-BLOG-022 duplicate article slug")
        raw_by_slug[record["slug"]] = raw
        records.append(record)
    batch_a, batch_b, selected_groups = partition_by_groups(records, batch_size=batch_size)
    ids = {item["article_id"] for item in records}
    ids_a = {item["article_id"] for item in batch_a}
    ids_b = {item["article_id"] for item in batch_b}
    if ids_a & ids_b or ids_a | ids_b != ids:
        raise IntegrityError("M25-BLOG-023 A/B reconciliation failed")
    if len(batch_a) != batch_size or len(batch_b) != batch_size:
        raise IntegrityError("M25-BLOG-024 batch sizes drifted")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    for record in batch_a:
        target = source_dir / f"{record['slug']}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw_by_slug[record["slug"]])
    nodes, edges = build_nodes_and_edges(batch_a, raw_by_slug)
    group_counts: dict[str, int] = defaultdict(int)
    for record in records:
        group_counts[record["partition_group_id"]] += 1
    master = sign(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "master_inventory",
            "origin_repository": repository,
            "origin_commit": commit,
            "language": "en",
            "expected_article_count": expected_count,
            "article_count": len(records),
            "series_count": len({item["series_id"] for item in records}),
            "partition_group_count": len(group_counts),
            "articles": records,
        },
        "inventory_sha256",
    )
    manifest_a = sign(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "batch_inventory",
            "batch_id": "M25.9A-BLOG-A",
            "master_inventory_sha256": master["inventory_sha256"],
            "origin_repository": repository,
            "origin_commit": commit,
            "source_count": len(batch_a),
            "selected_partition_groups": selected_groups,
            "articles": batch_a,
        },
        "batch_inventory_sha256",
    )
    manifest_b = sign(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "batch_inventory",
            "batch_id": "M25.9A-BLOG-B",
            "master_inventory_sha256": master["inventory_sha256"],
            "origin_repository": repository,
            "origin_commit": commit,
            "source_count": len(batch_b),
            "articles": batch_b,
        },
        "batch_inventory_sha256",
    )
    node_digest = sha256(nodes)
    edge_digest = sha256(edges)
    receipt = sign(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "batch_a_candidate_graph_receipt",
            "status": "batch_a_acquired_candidate_structural_nodes_ready",
            "origin_repository": repository,
            "origin_commit": commit,
            "master_inventory_sha256": master["inventory_sha256"],
            "batch_a_inventory_sha256": manifest_a["batch_inventory_sha256"],
            "batch_b_inventory_sha256": manifest_b["batch_inventory_sha256"],
            "master_source_count": len(records),
            "batch_a_source_count": len(batch_a),
            "batch_b_source_count": len(batch_b),
            "intersection_count": len(ids_a & ids_b),
            "missing_count": len(ids - (ids_a | ids_b)),
            "snapshot_count": len(list(source_dir.glob("*.md"))),
            "node_count": len(nodes),
            "series_node_count": sum(node["node_type"] == "Series" for node in nodes),
            "article_node_count": sum(node["node_type"] == "Article" for node in nodes),
            "section_node_count": sum(node["node_type"] == "Section" for node in nodes),
            "edge_count": len(edges),
            "nodes_sha256": node_digest,
            "edges_sha256": edge_digest,
            "semantic_claim_promotion_permitted": False,
            "source_write_permitted": False,
            "production_mutation_permitted": False,
            "m25_9b_authorized": False,
            "m25_9c_authorized": False,
            "next_legal_action": (
                "bind_exact_batch_a_inventory_and_candidate_graph_to_review_authority"
            ),
        },
        "receipt_sha256",
    )
    write_json(output_dir / "master-inventory.json", master)
    write_json(output_dir / "batch-a-inventory.json", manifest_a)
    write_json(output_dir / "batch-b-inventory.json", manifest_b)
    write_jsonl(output_dir / "candidate-nodes.jsonl", nodes)
    write_jsonl(output_dir / "candidate-edges.jsonl", edges)
    write_json(output_dir / "batch-a-receipt.json", receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge-m25-blog-pilot")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--batch-size", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = os.environ.get("BLOG_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        receipt = build_batch(
            repository=args.repository,
            commit=args.commit,
            expected_count=args.expected_count,
            batch_size=args.batch_size,
            output_dir=args.output_dir,
            client=GitHubClient(token),
        )
    except IntegrityError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
