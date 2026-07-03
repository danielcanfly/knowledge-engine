from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .compiler import CompiledRelease, compile_release
from .errors import IntegrityError
from .storage import sha256_bytes

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class SourceCheckout:
    repository: str
    commit_sha: str
    root: Path
    snapshot: dict[str, Any]


def _run_git(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise IntegrityError(f"git command failed: {' '.join(args)}: {detail}")
    return completed.stdout.strip()


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _safe_tracked_path(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise IntegrityError(f"unsafe tracked source path: {raw}")
    return path


def _snapshot_repository(root: Path, repository: str, commit_sha: str) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    listed = _run_git("ls-files", "-s", "-z", cwd=root)
    for record in listed.split("\0"):
        if not record:
            continue
        metadata, raw_path = record.split("\t", 1)
        mode, blob_sha, stage = metadata.split()
        if stage != "0":
            raise IntegrityError(f"unmerged source entry: {raw_path}")
        if mode == "120000":
            raise IntegrityError(f"source symlinks are not allowed: {raw_path}")
        path = _safe_tracked_path(raw_path)
        absolute = root.joinpath(*path.parts)
        if not absolute.is_file():
            raise IntegrityError(f"tracked source file is missing: {raw_path}")
        data = absolute.read_bytes()
        files.append(
            {
                "path": path.as_posix(),
                "mode": mode,
                "git_blob_sha": blob_sha,
                "bytes": len(data),
                "sha256": sha256_bytes(data),
            }
        )

    if not files:
        raise IntegrityError("source repository contains no tracked files")

    digest_input = {
        "repository": repository,
        "commit_sha": commit_sha,
        "files": files,
    }
    content_sha256 = hashlib.sha256(_canonical_json(digest_input)).hexdigest()
    return {
        "schema_version": "1.0",
        **digest_input,
        "file_count": len(files),
        "content_sha256": content_sha256,
    }


def checkout_source(
    *,
    repository_url: str,
    repository: str,
    commit_sha: str,
    checkout_root: Path,
) -> SourceCheckout:
    normalized_sha = commit_sha.strip().lower()
    if not SHA_RE.fullmatch(normalized_sha):
        raise IntegrityError("source SHA must be an exact 40-character lowercase commit SHA")

    checkout_root = checkout_root.resolve()
    if checkout_root.exists():
        shutil.rmtree(checkout_root)
    checkout_root.mkdir(parents=True)

    _run_git("init", "--quiet", cwd=checkout_root)
    _run_git("remote", "add", "origin", repository_url, cwd=checkout_root)
    _run_git(
        "fetch",
        "--quiet",
        "--no-tags",
        "--depth=1",
        "origin",
        normalized_sha,
        cwd=checkout_root,
    )
    _run_git("checkout", "--quiet", "--detach", "FETCH_HEAD", cwd=checkout_root)

    actual_sha = _run_git("rev-parse", "HEAD", cwd=checkout_root).lower()
    if actual_sha != normalized_sha:
        raise IntegrityError(
            f"source SHA mismatch: requested {normalized_sha}, checked out {actual_sha}"
        )
    if _run_git("status", "--porcelain", cwd=checkout_root):
        raise IntegrityError("source checkout is dirty")

    snapshot = _snapshot_repository(checkout_root, repository, normalized_sha)
    return SourceCheckout(
        repository=repository,
        commit_sha=normalized_sha,
        root=checkout_root,
        snapshot=snapshot,
    )


def materialize_source_bundle(checkout: SourceCheckout, destination: Path) -> Path:
    destination = destination.resolve()
    if destination.exists():
        shutil.rmtree(destination)

    source_bundle = checkout.root / "bundle"
    if not (source_bundle / "index.md").is_file():
        raise IntegrityError("knowledge-source bundle/index.md is required")
    shutil.copytree(source_bundle, destination)

    source_provenance = checkout.root / "provenance"
    if not source_provenance.is_dir():
        raise IntegrityError("knowledge-source provenance/ directory is required")
    shutil.copytree(source_provenance, destination / "provenance")

    snapshot_path = destination / "_source" / "source-snapshot.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_bytes(_canonical_json(checkout.snapshot))
    return destination


def build_source_release(
    *,
    repository_url: str,
    repository: str,
    source_commit_sha: str,
    foundation_commit_sha: str,
    work_root: Path,
    release_time: datetime,
    builder_commit_sha: str | None = None,
) -> tuple[CompiledRelease, dict[str, Any]]:
    raw_builder_sha = builder_commit_sha or os.environ.get(
        "KNOWLEDGE_ENGINE_BUILDER_SHA",
        "0" * 40,
    )
    normalized_builder_sha = raw_builder_sha.strip().lower()
    if not SHA_RE.fullmatch(normalized_builder_sha):
        raise IntegrityError("builder SHA must be an exact 40-character lowercase commit SHA")

    checkout = checkout_source(
        repository_url=repository_url,
        repository=repository,
        commit_sha=source_commit_sha,
        checkout_root=work_root / "source-checkout",
    )
    bundle_root = materialize_source_bundle(
        checkout,
        work_root / "materialized-bundle",
    )
    compiled = compile_release(
        bundle_root=bundle_root,
        work_root=work_root / "releases",
        release_time=release_time,
        source_repository=repository,
        source_commit_sha=checkout.commit_sha,
        foundation_commit_sha=foundation_commit_sha,
    )

    snapshot_data = _canonical_json(checkout.snapshot)
    snapshot_artifact = compiled.release_root / "artifacts/source-snapshot.json"
    snapshot_artifact.write_bytes(snapshot_data)
    compiled.manifest["builder"]["git_sha"] = normalized_builder_sha
    compiled.manifest["source"]["snapshot_sha256"] = checkout.snapshot[
        "content_sha256"
    ]
    compiled.manifest["artifacts"].append(
        {
            "kind": "source_snapshot",
            "key": f"releases/{compiled.release_id}/artifacts/source-snapshot.json",
            "sha256": sha256_bytes(snapshot_data),
            "bytes": len(snapshot_data),
            "media_type": "application/json",
            "audiences": compiled.manifest["security"]["audiences"],
            "required": True,
        }
    )
    (compiled.release_root / "manifest.json").write_bytes(
        _canonical_json(compiled.manifest)
    )
    return compiled, checkout.snapshot
