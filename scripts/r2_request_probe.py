#!/usr/bin/env python3
from __future__ import annotations

import argparse
import secrets
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
    random_name = secrets.token_hex(8)
    cases = [
        ("github_exact", f"_canary/github/{args.run_id}/{random_name}.txt"),
        ("github_no_ext", f"_canary/github/{args.run_id}/{random_name}"),
        ("request_shape_txt", f"_canary/request-shape/{args.run_id}/{random_name}.txt"),
        ("release_txt", f"releases/_probe-{args.run_id}/{random_name}.txt"),
    ]
    failures: list[str] = []
    for label, key in cases:
        try:
            store.put(
                key,
                payload,
                content_type="text/plain; charset=utf-8",
                sha256=sha256_bytes(payload),
                only_if_absent=True,
            )
            assert store.get(key) == payload
            print(f"PROBE_OK {label} key={key}")
        except Exception as exc:
            failures.append(f"{label}:{type(exc).__name__}:{exc}")
            print(f"PROBE_FAIL {label} key={key} error={type(exc).__name__}:{exc}")
        finally:
            try:
                store.delete(key)
            except Exception as exc:
                print(f"PROBE_DELETE_FAIL {label} {type(exc).__name__}:{exc}")
    if failures:
        raise RuntimeError(" | ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
