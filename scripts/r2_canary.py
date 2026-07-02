#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
from datetime import UTC, datetime

from knowledge_engine.config import Settings
from knowledge_engine.storage import R2ObjectStore, sha256_bytes


def _fingerprint(label: str, value: str | None) -> str:
    raw = (value or "").encode()
    return f"{label}:len={len(raw)}:sha256={hashlib.sha256(raw).hexdigest()[:12]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", "local"))
    args = parser.parse_args()
    settings = Settings.from_env()
    print(
        "R2_CONFIG_FINGERPRINT "
        + " ".join(
            [
                _fingerprint("endpoint", settings.r2_endpoint_url),
                _fingerprint("bucket", settings.r2_bucket),
                _fingerprint("access", settings.r2_access_key_id),
                _fingerprint("secret", settings.r2_secret_access_key),
            ]
        )
    )
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
