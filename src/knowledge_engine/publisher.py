from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .compiler import CompiledRelease
from .errors import IntegrityError
from .storage import ObjectStore, sha256_bytes


@dataclass(frozen=True)
class PublishResult:
    release_id: str
    channel: str
    manifest_key: str
    manifest_sha256: str


def _content_type(path: Path) -> str:
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".md":
        return "text/markdown; charset=utf-8"
    if path.name.endswith(".tar.gz"):
        return "application/gzip"
    return "application/octet-stream"


def publish_release(
    *,
    store: ObjectStore,
    compiled: CompiledRelease,
    channel: str,
    promoted_at: str,
) -> PublishResult:
    release_prefix = f"releases/{compiled.release_id}/"
    manifest_path = compiled.release_root / "manifest.json"
    immutable_files = sorted(
        path
        for path in compiled.release_root.rglob("*")
        if path.is_file() and path != manifest_path
    )
    for path in immutable_files:
        relative = path.relative_to(compiled.release_root).as_posix()
        key = release_prefix + relative
        data = path.read_bytes()
        digest = sha256_bytes(data)
        current = store.head(key)
        if current is not None:
            if current.bytes != len(data) or current.sha256 not in {None, digest}:
                raise IntegrityError(f"immutable object collision: {key}")
            remote = store.get(key)
            if sha256_bytes(remote) != digest:
                raise IntegrityError(f"immutable object collision: {key}")
            continue
        store.put(
            key,
            data,
            content_type=_content_type(path),
            sha256=digest,
            only_if_absent=True,
        )
        remote = store.get(key)
        if len(remote) != len(data) or sha256_bytes(remote) != digest:
            raise IntegrityError(f"post-upload verification failed: {key}")

    manifest_data = manifest_path.read_bytes()
    manifest_key = release_prefix + "manifest.json"
    manifest_digest = sha256_bytes(manifest_data)
    current_manifest = store.head(manifest_key)
    if current_manifest is None:
        store.put(
            manifest_key,
            manifest_data,
            content_type="application/json",
            sha256=manifest_digest,
            only_if_absent=True,
        )
    elif sha256_bytes(store.get(manifest_key)) != manifest_digest:
        raise IntegrityError(f"immutable manifest collision: {manifest_key}")
    if sha256_bytes(store.get(manifest_key)) != manifest_digest:
        raise IntegrityError("manifest verification failed after upload")

    pointer_key = f"channels/{channel}.json"
    current_pointer = store.head(pointer_key)
    pointer = {
        "schema_version": "1.0",
        "channel": channel,
        "release_id": compiled.release_id,
        "manifest_key": manifest_key,
        "manifest_sha256": manifest_digest,
        "promoted_at": promoted_at,
    }
    pointer_data = (
        json.dumps(pointer, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    store.put(
        pointer_key,
        pointer_data,
        content_type="application/json",
        sha256=sha256_bytes(pointer_data),
        expected_etag=current_pointer.etag if current_pointer else None,
        only_if_absent=current_pointer is None,
    )
    return PublishResult(
        release_id=compiled.release_id,
        channel=channel,
        manifest_key=manifest_key,
        manifest_sha256=manifest_digest,
    )
