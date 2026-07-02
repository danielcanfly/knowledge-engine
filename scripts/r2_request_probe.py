#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from knowledge_engine.config import Settings
from knowledge_engine.storage import create_object_store, sha256_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    store = create_object_store(Settings.from_env())

    report = (json.dumps({"schema_version": "1.0", "status": "passed"}, indent=2) + "\n").encode()
    cases = [
        ("text_small", b"knowledge-engine-r2-canary\n", "text/plain; charset=utf-8"),
        ("text_250", b"x" * 250, "text/plain; charset=utf-8"),
        ("json_small", b'{"status":"passed"}\n', "application/json"),
        ("json_report", report, "application/json"),
    ]
    failures: list[str] = []
    for label, payload, content_type in cases:
        key = f"_canary/request-shape/{args.run_id}/{label}"
        try:
            store.put(
                key,
                payload,
                content_type=content_type,
                sha256=sha256_bytes(payload),
                only_if_absent=True,
            )
            assert store.get(key) == payload
            print(f"PROBE_OK {label} bytes={len(payload)} type={content_type}")
        except Exception as exc:
            failures.append(f"{label}:{type(exc).__name__}:{exc}")
            print(f"PROBE_FAIL {label} bytes={len(payload)} type={content_type} error={type(exc).__name__}:{exc}")
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
