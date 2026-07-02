#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from knowledge_engine.compiler import CompiledRelease, compile_release
from knowledge_engine.config import Settings
from knowledge_engine.errors import IntegrityError
from knowledge_engine.publisher import publish_release
from knowledge_engine.runtime import Runtime
from knowledge_engine.storage import ObjectStore, create_object_store, sha256_bytes

SOURCE_SHA = "8b521b2ff23b5750a4ddf91772600700176883c0"
FOUNDATION_SHA = "d12c7c416c950d743d4cd5e7964fd3c3bc0d9062"


def release_keys(compiled: CompiledRelease) -> list[str]:
    prefix = f"releases/{compiled.release_id}/"
    return [
        prefix + path.relative_to(compiled.release_root).as_posix()
        for path in sorted(compiled.release_root.rglob("*"))
        if path.is_file()
    ]


def delete_keys(store: ObjectStore, keys: list[str]) -> list[str]:
    errors: list[str] = []
    for key in reversed(keys):
        try:
            store.delete(key)
        except Exception as exc:  # pragma: no cover - live cleanup evidence
            errors.append(f"{key}:{type(exc).__name__}:{exc}")
    return errors


def main() -> int:
    channel = os.environ["TAMPER_CHANNEL"]
    if not channel.startswith("oracle-tamper-"):
        raise RuntimeError("refusing to use a non-isolated channel")

    store = create_object_store(Settings.from_env())
    pointer_key = f"channels/{channel}.json"
    production_pointer_before = store.get("channels/production.json")
    cleanup_keys: list[str] = []
    original_artifact: bytes | None = None
    tampered_key: str | None = None
    tampered_media_type = "application/octet-stream"
    primary_error: BaseException | None = None

    with tempfile.TemporaryDirectory(prefix="oracle-tamper-") as temp:
        root = Path(temp)
        first_time = datetime.now(UTC).replace(microsecond=0)
        second_time = first_time + timedelta(seconds=1)
        try:
            first = compile_release(
                bundle_root=Path("/fixtures"),
                work_root=root / "first",
                release_time=first_time,
                source_repository="danielcanfly/knowledge-engine",
                source_commit_sha=SOURCE_SHA,
                foundation_commit_sha=FOUNDATION_SHA,
            )
            cleanup_keys.extend(release_keys(first))
            publish_release(
                store=store,
                compiled=first,
                channel=channel,
                promoted_at=first_time.isoformat().replace("+00:00", "Z"),
            )

            runtime = Runtime(store, root / "cache", channel)
            active_first = runtime.refresh()
            if active_first.release_id != first.release_id:
                raise RuntimeError("first release did not become active")
            print(f"ORACLE_LKG_BASELINE_RELEASE={first.release_id}")

            second = compile_release(
                bundle_root=Path("/fixtures"),
                work_root=root / "second",
                release_time=second_time,
                source_repository="danielcanfly/knowledge-engine",
                source_commit_sha=SOURCE_SHA,
                foundation_commit_sha=FOUNDATION_SHA,
            )
            cleanup_keys.extend(release_keys(second))
            publish_release(
                store=store,
                compiled=second,
                channel=channel,
                promoted_at=second_time.isoformat().replace("+00:00", "Z"),
            )

            artifact = next(
                item
                for item in second.manifest["artifacts"]
                if item["kind"] == "lexical_index"
            )
            tampered_key = artifact["key"]
            tampered_media_type = artifact["media_type"]
            original_artifact = store.get(tampered_key)
            original_head = store.head(tampered_key)
            if original_head is None:
                raise RuntimeError("artifact disappeared before integrity test")

            invalid_data = b'{"invalid_test_artifact":true}\n'
            store.put(
                tampered_key,
                invalid_data,
                content_type=tampered_media_type,
                sha256=sha256_bytes(invalid_data),
                expected_etag=original_head.etag,
            )
            print(f"ORACLE_INVALID_TEST_KEY={tampered_key}")

            try:
                runtime.refresh()
            except IntegrityError as exc:
                print(f"ORACLE_TAMPER_DETECTED={type(exc).__name__}:{exc}")
            else:
                raise RuntimeError("invalid test release was activated")

            active_after_failure = runtime.active
            if (
                active_after_failure is None
                or active_after_failure.release_id != first.release_id
            ):
                raise RuntimeError("last-known-good release was not preserved")
            print(f"ORACLE_LKG_PRESERVED={active_after_failure.release_id}")

            invalid_head = store.head(tampered_key)
            if invalid_head is None:
                raise RuntimeError("test artifact disappeared before restore")
            store.put(
                tampered_key,
                original_artifact,
                content_type=tampered_media_type,
                sha256=artifact["sha256"],
                expected_etag=invalid_head.etag,
            )
            original_artifact = None

            recovered = runtime.refresh()
            if recovered.release_id != second.release_id:
                raise RuntimeError("restored release did not recover")
            print(f"ORACLE_TAMPER_RECOVERY_PASSED={recovered.release_id}")

            evidence = {
                "channel": channel,
                "first_release_id": first.release_id,
                "second_release_id": second.release_id,
                "test_key": tampered_key,
                "lkg_preserved": True,
                "recovery_passed": True,
            }
            print("ORACLE_TAMPER_EVIDENCE=" + json.dumps(evidence, sort_keys=True))
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            restore_errors: list[str] = []
            if tampered_key and original_artifact is not None:
                try:
                    current = store.head(tampered_key)
                    if current is not None:
                        store.put(
                            tampered_key,
                            original_artifact,
                            content_type=tampered_media_type,
                            sha256=sha256_bytes(original_artifact),
                            expected_etag=current.etag,
                        )
                except Exception as exc:  # pragma: no cover - live cleanup
                    restore_errors.append(
                        f"restore:{tampered_key}:{type(exc).__name__}:{exc}"
                    )

            cleanup_errors: list[str] = []
            try:
                store.delete(pointer_key)
            except Exception as exc:  # pragma: no cover - live cleanup
                cleanup_errors.append(f"{pointer_key}:{type(exc).__name__}:{exc}")
            cleanup_errors.extend(delete_keys(store, cleanup_keys))

            try:
                production_pointer_after = store.get("channels/production.json")
                if production_pointer_after != production_pointer_before:
                    cleanup_errors.append("production pointer changed")
            except Exception as exc:  # pragma: no cover - live cleanup
                cleanup_errors.append(
                    f"production-check:{type(exc).__name__}:{exc}"
                )

            all_errors = restore_errors + cleanup_errors
            if all_errors:
                print("ORACLE_TAMPER_CLEANUP_ERRORS=" + " | ".join(all_errors))
                if primary_error is None:
                    raise RuntimeError("integrity proof cleanup failed")
            else:
                print("ORACLE_PRODUCTION_POINTER_UNCHANGED")
                print("ORACLE_TAMPER_CLEANUP_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
