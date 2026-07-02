#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime

from knowledge_engine.config import Settings
from knowledge_engine.storage import create_object_store, sha256_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    store = create_object_store(Settings.from_env())
    payload = (
        "knowledge-engine-r2-canary\n"
        + datetime.now(UTC).isoformat()
        + "\n"
    ).encode()
    cases = [
        (
            "exact_shape",
            f"_canary/github/{args.run_id}/exact.txt",
            "text/plain; charset=utf-8",
        ),
        (
            "content_type_only",
            f"_canary/github/{args.run_id}/plain.txt",
            "text/plain",
        ),
        (
            "prefix_only",
            f"_canary/lifecycle/{args.run_id}/exact.txt",
            "text/plain; charset=utf-8",
        ),
        (
            "release_prefix",
            f"releases/_probe-{args.run_id}/exact.txt",
            "text/plain; charset=utf-8",
        ),
    ]

    failures: list[str] = []
    for label, key, content_type in cases:
        try:
            store.put(
                key,
                payload,
                content_type=content_type,
                sha256=sha256_bytes(payload),
                only_if_absent=True,
            )
            if store.get(key) != payload:
                raise RuntimeError("round-trip mismatch")
            print(f"R2_REQUEST_PROBE_PASSED label={label}")
        except Exception as exc:
            failures.append(f"{label}:{type(exc).__name__}:{exc}")
            print(f"R2_REQUEST_PROBE_FAILED label={label} type={type(exc).__name__} message={exc}")
        finally:
            try:
                store.delete(key)
            except Exception as exc:
                print(f"R2_REQUEST_PROBE_CLEANUP_FAILED label={label} type={type(exc).__name__}")

    if failures:
        raise RuntimeError("request probe failed: " + " | ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
