#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
from datetime import UTC, datetime

from knowledge_engine.config import Settings
from knowledge_engine.storage import R2ObjectStore, sha256_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", "local"))
    args = parser.parse_args()
    settings = Settings.from_env()
    if settings.object_store_backend != "r2":
        raise SystemExit("OBJECT_STORE_BACKEND must be r2")
    store = R2ObjectStore(settings)
    suffix = secrets.token_hex(8)
    key = f"releases/_canary-{args.run_id}-{suffix}/artifacts/build-report.json"
    payload = (
        json.dumps(
            {
                "status": "passed",
                "generated_at": datetime.now(UTC).isoformat(),
                "counts": {"concepts": 1, "artifacts": 5},
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()
    digest = sha256_bytes(payload)
    try:
        store.put(
            key,
            payload,
            content_type="application/json",
            sha256=digest,
            only_if_absent=True,
        )
        downloaded = store.get(key)
        if downloaded != payload or sha256_bytes(downloaded) != digest:
            raise RuntimeError("R2 canary round-trip mismatch")
        metadata = store.head(key)
        if metadata is None or metadata.bytes != len(payload):
            raise RuntimeError("R2 canary metadata mismatch")
        print("R2_CANARY_PASSED")
        return 0
    finally:
        store.delete(key)
