#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

RELEASE_ID = "20260720T160000Z-46137c97263e"
SOURCE_SHA = "acf78596ace8a7366688ccef72b507204d09d9f9"
BLOG_COMMIT = "27e2fe996f878f2129bf510d6a326c02f7d87be5"

CONCEPTS_BY_SOURCE_ID = {
    "source_blog_agent_architecture_6d": [
        "concepts/six-dimensional-map-of-llm-agent-architectures"
    ],
    "source_blog_agent_execution_paths": ["concepts/agent-execution-paths"],
    "source_blog_agent_planning_strategies": ["concepts/agent-planning-strategies"],
    "source_m23_4_harness_proposed_concepts": [
        "concepts/harness",
        "concepts/harness-agent-loop",
        "concepts/harness-verification",
        "concepts/headless-harness-service",
        "concepts/request-boundary",
    ],
    "source_m23_4_harness_provenance_summary": [
        "concepts/harness",
        "concepts/harness-agent-loop",
        "concepts/harness-verification",
        "concepts/headless-harness-service",
        "concepts/request-boundary",
    ],
    "source_m24_source_pr_19_decision_capture": [
        "concepts/source-governance",
        "concepts/harness",
        "concepts/task-contract",
    ],
    "source_m3_contract": [
        "concepts/task-contract",
        "concepts/completion-gate",
        "concepts/source-governance",
    ],
}


def _git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", repo.as_posix(), *args])


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _parse_markdown(text: str) -> tuple[dict[str, str], str]:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            frontmatter_text = text[4:end]
            metadata: dict[str, str] = {}
            for line in frontmatter_text.splitlines():
                if ":" in line and not line.startswith(" "):
                    key, value = line.split(":", 1)
                    metadata[key.strip()] = value.strip().strip('"')
            return metadata, text[end + 5 :]
    return {}, text


def _toc_from_markdown(text: str) -> list[dict[str, Any]]:
    toc: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", line)
        if not match:
            continue
        title = match.group(2).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        toc.append({"level": len(match.group(1)), "title": title, "slug": slug})
    return toc


def _line_count(data: bytes) -> int:
    text = data.decode("utf-8")
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _origin_specs(args: argparse.Namespace) -> dict[str, tuple[str, str, str, Path]]:
    return {
        "source_blog_agent_architecture_6d": (
            "huaihsuanbusiness/daniel-blog",
            BLOG_COMMIT,
            "src/content/blog/the-atlas-of-agent-design-patterns-part-1/en.md",
            args.blog_repo,
        ),
        "source_blog_agent_execution_paths": (
            "huaihsuanbusiness/daniel-blog",
            BLOG_COMMIT,
            "src/content/blog/the-atlas-of-agent-design-patterns-part-2/en.md",
            args.blog_repo,
        ),
        "source_blog_agent_planning_strategies": (
            "huaihsuanbusiness/daniel-blog",
            BLOG_COMMIT,
            "src/content/blog/the-atlas-of-agent-design-patterns-part-3/en.md",
            args.blog_repo,
        ),
        "source_m23_4_harness_proposed_concepts": (
            "danielcanfly/knowledge-source",
            "deb3ad1e631c2149183d10561fbceb0a1848a989",
            "proposals/m23-4/proposed-concepts.md",
            args.source_repo,
        ),
        "source_m23_4_harness_provenance_summary": (
            "danielcanfly/knowledge-source",
            "deb3ad1e631c2149183d10561fbceb0a1848a989",
            "proposals/m23-4/provenance-summary.json",
            args.source_repo,
        ),
        "source_m24_source_pr_19_decision_capture": (
            "danielcanfly/knowledge-engine",
            "22041bfecd07c9e4b75146ab4d0b83e417e914e8",
            "pilot/m24/m24-source-pr-19-decision-capture.json",
            args.engine_repo,
        ),
    }


def _document_payload(record: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    source_id = record["source_id"]
    origin_specs = _origin_specs(args)
    raw: bytes | None = None
    origin = {
        "repo": record.get("uri", "").removeprefix("https://github.com/"),
        "commit": record.get("origin_commit"),
        "path": record.get("origin_path"),
        "blob_sha": record.get("origin_blob_sha"),
    }
    coverage_status = "metadata_only_with_reason"
    reason = None
    document: dict[str, Any] = {"format": "metadata", "body": ""}
    toc: list[dict[str, Any]] = []

    if source_id in origin_specs:
        origin_repo, commit, path, local_repo = origin_specs[source_id]
        raw = _git_bytes(local_repo, "show", f"{commit}:{path}")
        blob_sha = _git_bytes(local_repo, "ls-tree", commit, path).decode().split()[2]
        origin = {
            "repo": origin_repo,
            "commit": commit,
            "path": path,
            "blob_sha": blob_sha,
        }
        text = raw.decode("utf-8")
        if record.get("kind") == "json":
            parsed = json.loads(text)
            document = {
                "format": "json",
                "json": parsed,
                "body": json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                "raw_json": text,
            }
            coverage_status = "structured_snapshot"
        else:
            frontmatter, body = _parse_markdown(text)
            document = {
                "format": "markdown",
                "frontmatter": frontmatter,
                "body": body,
                "raw_markdown": text,
            }
            toc = _toc_from_markdown(body)
            coverage_status = "full_snapshot"
    else:
        reason = (
            "No exact release-authoritative file or immutable snapshot was resolved "
            "for this governance contract in the M24.14.5 repair authority boundary."
        )
        document = {
            "format": "metadata",
            "body": "",
            "metadata_only_reason": reason,
        }

    snapshot_sha = _sha256_bytes(raw) if raw is not None else None
    payload = {
        "schema_version": "knowledge-engine-m24-14-5-source-document/v1",
        "release_id": RELEASE_ID,
        "source_id": source_id,
        "title": record.get("title") or source_id,
        "kind": record.get("kind"),
        "owner": record.get("owner"),
        "license": record.get("license"),
        "trust": record.get("trust"),
        "audience": record.get("audience"),
        "canonical_uri": record.get("uri"),
        "coverage_status": coverage_status,
        "metadata_only_reason": reason,
        "origin": origin,
        "registry": {
            "source_repository": "danielcanfly/knowledge-source",
            "source_commit": SOURCE_SHA,
            "source_id": source_id,
            "content_sha256": record.get("content_sha256"),
            "content_hash_scope": record.get("content_hash_scope")
            or (
                "full-source-bytes"
                if snapshot_sha and snapshot_sha == record.get("content_sha256")
                else "registry-declared"
            ),
        },
        "integrity": {
            "snapshot_sha256": snapshot_sha,
            "browser_payload_sha256": None,
            "origin_blob_sha": origin.get("blob_sha"),
            "byte_count": len(raw) if raw is not None else 0,
            "line_count": _line_count(raw or b""),
            "truncated": False,
            "executable_scripts_detected": bool(
                re.search(r"<\s*script\b", document.get("body", ""), re.I)
            ),
        },
        "related_concepts": CONCEPTS_BY_SOURCE_ID[source_id],
        "citations": [],
        "document": document,
        "toc": toc,
    }
    comparable = json.loads(json.dumps(payload, ensure_ascii=False))
    comparable["integrity"]["browser_payload_sha256"] = None
    payload["integrity"]["browser_payload_sha256"] = _canonical_sha256(comparable)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--source-repo",
        type=Path,
        default=Path("/Users/daniel/LLM-Wiki-Local/knowledge-source"),
    )
    parser.add_argument(
        "--blog-repo",
        type=Path,
        default=Path("/tmp/m24_14_5_origin_repos/daniel-blog"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("pilot/m24/source-document-package"),
    )
    args = parser.parse_args()

    registry = json.loads((args.source_repo / "registry/sources.json").read_text())
    args.output.joinpath("sources").mkdir(parents=True, exist_ok=True)
    documents = {}
    rows = []
    for record in registry["sources"]:
        payload = _document_payload(record, args)
        safe_id = payload["source_id"].replace("/", "_")
        payload_path = args.output / "sources" / f"{safe_id}.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        documents[payload["source_id"]] = payload
        rows.append(
            {
                "source_id": payload["source_id"],
                "title": payload["title"],
                "kind": payload["kind"],
                "coverage_status": payload["coverage_status"],
                "snapshot_available": payload["coverage_status"]
                in {"full_snapshot", "structured_snapshot"},
                "metadata_only_reason": payload["metadata_only_reason"],
                "origin_repo": payload["origin"].get("repo"),
                "origin_commit": payload["origin"].get("commit"),
                "origin_path": payload["origin"].get("path"),
                "origin_blob_sha": payload["origin"].get("blob_sha"),
                "registry_content_sha256": payload["registry"].get("content_sha256"),
                "registry_content_hash_scope": payload["registry"].get(
                    "content_hash_scope"
                ),
                "generated_snapshot_sha256": payload["integrity"].get(
                    "snapshot_sha256"
                ),
                "browser_payload_sha256": payload["integrity"].get(
                    "browser_payload_sha256"
                ),
                "content_bytes": payload["integrity"]["byte_count"],
                "line_count": payload["integrity"]["line_count"],
                "document_path": f"data/sources/{safe_id}.json",
                "canonical_uri": payload["canonical_uri"],
                "related_concepts": payload["related_concepts"],
            }
        )
    source_index = {
        "schema_version": "knowledge-engine-m24-14-5-source-index/v1",
        "release_id": RELEASE_ID,
        "source_repository": "danielcanfly/knowledge-source",
        "source_commit_sha": SOURCE_SHA,
        "source_count": len(rows),
        "coverage_matrix": rows,
    }
    source_documents = {
        "schema_version": "knowledge-engine-m24-14-5-source-documents/v1",
        "release_id": RELEASE_ID,
        "source_count": len(documents),
        "documents": documents,
    }
    (args.output / "source-index.json").write_text(
        json.dumps(source_index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    (args.output / "source-documents.json").write_text(
        json.dumps(source_documents, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    (args.output / "registry-sources.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
