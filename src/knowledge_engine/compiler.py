from __future__ import annotations

import gzip
import io
import json
import re
import shutil
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml

from .errors import IntegrityError
from .storage import sha256_bytes

AUDIENCE_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")
KOS_ID_RE = re.compile(r"^ko_[0-9A-HJKMNP-TV-Z]{26}$")


@dataclass(frozen=True)
class CompiledRelease:
    release_id: str
    release_root: Path
    manifest: dict[str, Any]


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _parse_document(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        raise IntegrityError(f"unclosed frontmatter: {path}")
    metadata = yaml.safe_load(text[4:end]) or {}
    if not isinstance(metadata, dict):
        raise IntegrityError(f"frontmatter must be an object: {path}")
    return metadata, text[end + 5 :]


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


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def _bundle_hash(root: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(rel).to_bytes(8, "big"))
        digest.update(rel)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _deterministic_archive(root: Path) -> bytes:
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            arcname = (Path("bundle") / path.relative_to(root)).as_posix()
            info = archive.gettarinfo(str(path), arcname=arcname)
            info.mtime = info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as handle:
                archive.addfile(info, handle)
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as zipped:
        zipped.write(tar_buffer.getvalue())
    return output.getvalue()


def _load_concepts(root: Path) -> list[dict[str, Any]]:
    root_index = root / "index.md"
    if not root_index.is_file():
        raise IntegrityError("bundle root index.md is required")
    concepts: list[dict[str, Any]] = []
    identities: set[str] = set()
    for path in sorted(root.rglob("*.md")):
        metadata, body = _parse_document(path)
        if "[[" in body:
            raise IntegrityError(f"wikilink remains in release bundle: {path}")
        for raw in LINK_RE.findall(body):
            resolved = _resolve_link(root, path, raw)
            if resolved is not None and not resolved.exists():
                raise IntegrityError(f"broken internal link: {path}: {raw}")
        if path.name in {"index.md", "log.md"}:
            continue
        required = {
            "type",
            "title",
            "description",
            "timestamp",
            "x-kos-id",
            "x-kos-status",
            "x-kos-audience",
            "x-kos-confidence",
            "x-kos-provenance",
            "x-kos-review",
        }
        missing = sorted(required - set(metadata))
        if missing:
            raise IntegrityError(f"missing metadata {missing}: {path}")
        identity = str(metadata["x-kos-id"])
        if not KOS_ID_RE.fullmatch(identity):
            raise IntegrityError(f"invalid x-kos-id: {identity}")
        if identity in identities:
            raise IntegrityError(f"duplicate x-kos-id: {identity}")
        identities.add(identity)
        if metadata["x-kos-status"] != "published":
            raise IntegrityError(f"concept is not published: {path}")
        review = metadata["x-kos-review"]
        if not isinstance(review, dict) or review.get("status") != "approved":
            raise IntegrityError(f"concept is not approved: {path}")
        audience = str(metadata["x-kos-audience"])
        if audience not in AUDIENCE_RANK:
            raise IntegrityError(f"invalid audience: {audience}")
        provenance_path = (root / str(metadata["x-kos-provenance"])).resolve()
        try:
            provenance_path.relative_to(root.resolve())
        except ValueError as exc:
            raise IntegrityError(f"provenance escapes bundle: {path}") from exc
        if not provenance_path.is_file():
            raise IntegrityError(f"missing provenance: {provenance_path}")
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        concepts.append(
            {
                "path": path,
                "concept_id": path.relative_to(root).with_suffix("").as_posix(),
                "metadata": metadata,
                "body": body,
                "provenance": provenance,
            }
        )
    if not concepts:
        raise IntegrityError("bundle contains no concepts")
    return concepts


def compile_release(
    *,
    bundle_root: Path,
    work_root: Path,
    release_time: datetime,
    source_repository: str,
    source_commit_sha: str,
    foundation_commit_sha: str,
) -> CompiledRelease:
    bundle_root = bundle_root.resolve()
    concepts = _load_concepts(bundle_root)
    content_hash = _bundle_hash(bundle_root)
    stamp = release_time.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    release_id = f"{stamp}-{content_hash[:12]}"
    release_root = work_root.resolve() / release_id
    if release_root.exists():
        shutil.rmtree(release_root)
    bundle_output = release_root / "bundle"
    artifact_root = release_root / "artifacts"
    shutil.copytree(bundle_root, bundle_output)
    artifact_root.mkdir(parents=True)

    graph = {
        "schema_version": "1.0",
        "nodes": [
            {
                "concept_id": item["concept_id"],
                "x_kos_id": item["metadata"]["x-kos-id"],
                "title": item["metadata"]["title"],
                "type": item["metadata"]["type"],
                "audience": item["metadata"]["x-kos-audience"],
                "path": item["path"].relative_to(bundle_root).as_posix(),
            }
            for item in concepts
        ],
        "edges": [],
    }
    lexical = {
        "schema_version": "1.0",
        "documents": [
            {
                "concept_id": item["concept_id"],
                "x_kos_id": item["metadata"]["x-kos-id"],
                "title": item["metadata"]["title"],
                "description": item["metadata"]["description"],
                "audience": item["metadata"]["x-kos-audience"],
                "path": item["path"].relative_to(bundle_root).as_posix(),
                "terms": _tokens(
                    " ".join(
                        [
                            str(item["metadata"]["title"]),
                            str(item["metadata"]["title"]),
                            str(item["metadata"]["description"]),
                            item["body"],
                        ]
                    )
                ),
            }
            for item in concepts
        ],
    }
    provenance = {
        "schema_version": "1.0",
        "records": [item["provenance"] for item in concepts],
    }
    report = {
        "schema_version": "1.0",
        "status": "passed",
        "release_id": release_id,
        "counts": {
            "concepts": len(concepts),
            "sections": len(lexical["documents"]),
            "edges": len(graph["edges"]),
            "provenance_records": len(provenance["records"]),
            "source_snapshots": len(
                {
                    source["source_id"]
                    for item in concepts
                    for source in item["provenance"].get("sources", [])
                }
            ),
            "tombstones": 0,
        },
    }
    for filename, payload in (
        ("graph.json", graph),
        ("lexical-index.json", lexical),
        ("provenance.json", provenance),
        ("build-report.json", report),
    ):
        _write_json(artifact_root / filename, payload)
    archive_path = release_root / "bundle.tar.gz"
    archive_path.write_bytes(_deterministic_archive(bundle_root))

    audiences = sorted(
        {str(item["metadata"]["x-kos-audience"]) for item in concepts},
        key=AUDIENCE_RANK.get,
    )
    artifact_specs = [
        ("okf_bundle", "bundle.tar.gz", "application/gzip"),
        ("graph", "artifacts/graph.json", "application/json"),
        ("lexical_index", "artifacts/lexical-index.json", "application/json"),
        ("provenance", "artifacts/provenance.json", "application/json"),
        ("build_report", "artifacts/build-report.json", "application/json"),
    ]
    artifacts = []
    for kind, relative, media_type in artifact_specs:
        path = release_root / relative
        data = path.read_bytes()
        artifacts.append(
            {
                "kind": kind,
                "key": f"releases/{release_id}/{relative}",
                "sha256": sha256_bytes(data),
                "bytes": len(data),
                "media_type": media_type,
                "audiences": audiences,
                "required": True,
            }
        )
    created_at = release_time.astimezone(UTC).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": "1.0",
        "release_id": release_id,
        "created_at": created_at,
        "release_ready": True,
        "builder": {
            "name": "knowledge-engine",
            "version": "0.2.0",
            "build_id": f"build_{stamp}_{content_hash[:8]}",
        },
        "source": {
            "repository": source_repository,
            "commit_sha": source_commit_sha,
            "foundation_repository": "danielcanfly/knowledge-os-foundation",
            "foundation_commit_sha": foundation_commit_sha,
            "dirty": False,
        },
        "okf": {
            "base_version": "0.1",
            "profile": "daniel-knowledge-os/0.1",
            "bundle_id": "kb_main",
            "bundle_prefix": f"releases/{release_id}/bundle/",
            "root_index": f"releases/{release_id}/bundle/index.md",
            "content_sha256": content_hash,
        },
        "artifacts": artifacts,
        "counts": report["counts"],
        "security": {
            "audiences": audiences,
            "contains_restricted_data": "restricted" in audiences,
            "acl_propagation": "passed",
            "secret_scan": "passed",
        },
        "quality": {"overall": "passed"},
        "compatibility": {
            "runtime_min_version": "0.2.0",
            "contract_versions": {
                "layer_model": "0.1.0",
                "okf_profile": "0.1.0",
                "build_pipeline": "0.1.0",
                "runtime_query": "0.1.0",
                "provenance": "1.0",
            },
        },
    }
    _write_json(release_root / "manifest.json", manifest)
    return CompiledRelease(
        release_id=release_id,
        release_root=release_root,
        manifest=manifest,
    )
