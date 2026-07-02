#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from knowledge_engine.compiler import compile_release
from knowledge_engine.config import Settings
from knowledge_engine.publisher import publish_release
from knowledge_engine.runtime import Runtime
from knowledge_engine.storage import ObjectStore, create_object_store, sha256_bytes

ROOT = Path(__file__).resolve().parents[1]


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_base_time(run_id: str) -> datetime:
    """Map each integration run to a stable, collision-resistant release timestamp."""
    offset_seconds = int(hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:8], 16)
    return datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=offset_seconds)


def _release_keys(release_id: str, release_root: Path) -> list[str]:
    prefix = f"releases/{release_id}/"
    return [
        prefix + path.relative_to(release_root).as_posix()
        for path in sorted(release_root.rglob("*"))
        if path.is_file()
    ]


def _probe_compiled_artifact(
    store: ObjectStore,
    release_root: Path,
    run_id: str,
) -> None:
    manifest_path = release_root / "manifest.json"
    artifact = sorted(
        path
        for path in release_root.rglob("*")
        if path.is_file() and path != manifest_path
    )[0]
    relative = artifact.relative_to(release_root).as_posix()
    key = f"_canary/lifecycle/{run_id}/{relative}"
    data = artifact.read_bytes()
    digest = sha256_bytes(data)
    try:
        store.put(
            key,
            data,
            content_type="application/json",
            sha256=digest,
            only_if_absent=True,
        )
        if store.get(key) != data:
            raise RuntimeError("compiled artifact probe round-trip mismatch")
        print(f"COMPILED_ARTIFACT_PROBE_PASSED path={relative} bytes={len(data)}")
    finally:
        store.delete(key)


def run_integration(settings: Settings, run_id: str) -> dict:
    store: ObjectStore = create_object_store(settings)
    channel = f"ci-{run_id.lower().replace('_', '-')[:80]}"
    pointer_key = f"channels/{channel}.json"
    cleanup_keys: list[str] = []
    primary_error: BaseException | None = None
    with tempfile.TemporaryDirectory(prefix="knowledge-engine-r2-") as temp:
        temp_root = Path(temp)
        base_time = _run_base_time(run_id)
        try:
            first = compile_release(
                bundle_root=ROOT / "examples/okf-bundle",
                work_root=temp_root / "builds-a",
                release_time=base_time,
                source_repository="danielcanfly/knowledge-engine",
                source_commit_sha="a" * 40,
                foundation_commit_sha="d" * 40,
            )
            cleanup_keys.extend(_release_keys(first.release_id, first.release_root))
            _probe_compiled_artifact(store, first.release_root, run_id)
            publish_release(
                store=store,
                compiled=first,
                channel=channel,
                promoted_at=_timestamp(base_time),
            )
            first_pointer = store.get(pointer_key)
            runtime = Runtime(store, temp_root / "cache", channel)
            internal = runtime.query("knowledge compiler", {"public", "internal"})
            public = runtime.query("knowledge compiler", {"public"})
            if internal["status"] != "answered" or not internal["results"][0]["citations"]:
                raise RuntimeError("authorized R2 query did not return cited knowledge")
            if public["status"] != "not_found" or public["results"]:
                raise RuntimeError("public R2 query crossed the ACL boundary")

            second_time = base_time + timedelta(seconds=1)
            second = compile_release(
                bundle_root=ROOT / "examples/okf-bundle",
                work_root=temp_root / "builds-b",
                release_time=second_time,
                source_repository="danielcanfly/knowledge-engine",
                source_commit_sha="b" * 40,
                foundation_commit_sha="d" * 40,
            )
            cleanup_keys.extend(_release_keys(second.release_id, second.release_root))
            publish_release(
                store=store,
                compiled=second,
                channel=channel,
                promoted_at=_timestamp(second_time),
            )
            if runtime.refresh().release_id != second.release_id:
                raise RuntimeError("second release did not become active")

            current_pointer = store.head(pointer_key)
            if current_pointer is None:
                raise RuntimeError("channel pointer disappeared before rollback")
            store.put(
                pointer_key,
                first_pointer,
                content_type="application/json",
                sha256=sha256_bytes(first_pointer),
                expected_etag=current_pointer.etag,
            )
            rolled_back = runtime.refresh()
            if rolled_back.release_id != first.release_id:
                raise RuntimeError("channel rollback did not restore the first release")
            return {
                "status": "passed",
                "channel": channel,
                "first_release": first.release_id,
                "second_release": second.release_id,
                "rolled_back_to": rolled_back.release_id,
                "authorized_query": internal["status"],
                "public_query": public["status"],
            }
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            cleanup_errors: list[str] = []
            for key in [pointer_key, *reversed(cleanup_keys)]:
                try:
                    store.delete(key)
                except Exception as exc:
                    cleanup_errors.append(f"{key}: {type(exc).__name__}")
            if cleanup_errors:
                print(
                    "R2_INTEGRATION_CLEANUP_ERRORS " + "; ".join(cleanup_errors),
                    flush=True,
                )
                if primary_error is None:
                    raise RuntimeError("R2 integration cleanup failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = run_integration(Settings.from_env(), args.run_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    print("R2_RELEASE_INTEGRATION_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
