from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .compiler import CompiledRelease
from .errors import IntegrityError, ReleaseConflictError
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


def _put_immutable(
    *,
    store: ObjectStore,
    key: str,
    data: bytes,
    content_type: str,
    digest: str,
) -> None:
    created = False
    try:
        store.put(
            key,
            data,
            content_type=content_type,
            sha256=digest,
            only_if_absent=True,
        )
        created = True
    except ReleaseConflictError:
        pass

    remote = store.get(key)
    if len(remote) != len(data) or sha256_bytes(remote) != digest:
        reason = (
            "post-upload verification failed"
            if created
            else "immutable object collision"
        )
        raise IntegrityError(f"{reason}: {key}")


def _promote_channel(
    *,
    store: ObjectStore,
    pointer_key: str,
    pointer_data: bytes,
) -> None:
    digest = sha256_bytes(pointer_data)
    try:
        store.put(
            pointer_key,
            pointer_data,
            content_type="application/json",
            sha256=digest,
            only_if_absent=True,
        )
        return
    except ReleaseConflictError as conflict:
        current = store.head(pointer_key)
        if current is None:
            raise ReleaseConflictError(
                f"channel pointer disappeared during promotion: {pointer_key}"
            ) from conflict

    store.put(
        pointer_key,
        pointer_data,
        content_type="application/json",
        sha256=digest,
        expected_etag=current.etag,
    )


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
        _put_immutable(
            store=store,
            key=key,
            data=data,
            content_type=_content_type(path),
            digest=sha256_bytes(data),
        )

    manifest_data = manifest_path.read_bytes()
    manifest_key = release_prefix + "manifest.json"
    manifest_digest = sha256_bytes(manifest_data)
    _put_immutable(
        store=store,
        key=manifest_key,
        data=manifest_data,
        content_type="application/json",
        digest=manifest_digest,
    )

    pointer_key = f"channels/{channel}.json"
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
    _promote_channel(
        store=store,
        pointer_key=pointer_key,
        pointer_data=pointer_data,
    )
    return PublishResult(
        release_id=compiled.release_id,
        channel=channel,
        manifest_key=manifest_key,
        manifest_sha256=manifest_digest,
    )
