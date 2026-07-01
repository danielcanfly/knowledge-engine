#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    key = f"_canary/github/{args.run_id}/{secrets.token_hex(8)}.txt"
    payload = (
        "knowledge-engine-r2-canary\n"
        + datetime.now(UTC).isoformat()
        + "\n"
    ).encode()
    digest = sha256_bytes(payload)
    try:
        store.put(
            key,
            payload,
            content_type="text/plain; charset=utf-8",
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
