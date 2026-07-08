#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

from knowledge_engine.config import Settings
from knowledge_engine.storage import ObjectStore, create_object_store, sha256_bytes

PRODUCTION_POINTER_KEY = "channels/production.json"
EXPECTED_POINTER_SHA256 = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
EXPECTED_RELEASE_ID = "20260708T040116Z-69a9f445699a"
EXPECTED_MANIFEST_SHA256 = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
EXPECTED_MANIFEST_KEY = f"releases/{EXPECTED_RELEASE_ID}/manifest.json"


@dataclass(frozen=True)
class BaselineExpectation:
    pointer_sha256: str = EXPECTED_POINTER_SHA256
    release_id: str = EXPECTED_RELEASE_ID
    manifest_sha256: str = EXPECTED_MANIFEST_SHA256
    manifest_key: str = EXPECTED_MANIFEST_KEY


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return value


def verify_production_baseline(
    store: ObjectStore,
    expectation: BaselineExpectation = BaselineExpectation(),
) -> dict[str, Any]:
    """Read and verify the production pointer and manifest without mutating storage."""

    pointer_bytes = store.get(PRODUCTION_POINTER_KEY)
    pointer_sha256 = sha256_bytes(pointer_bytes)
    if pointer_sha256 != expectation.pointer_sha256:
        raise RuntimeError(
            "production pointer bytes changed: "
            f"expected {expectation.pointer_sha256}, observed {pointer_sha256}"
        )
    try:
        pointer = _object(json.loads(pointer_bytes), "production pointer")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("production pointer is not valid UTF-8 JSON") from exc

    expected_pointer = {
        "channel": "production",
        "release_id": expectation.release_id,
        "manifest_key": expectation.manifest_key,
        "manifest_sha256": expectation.manifest_sha256,
    }
    for key, expected in expected_pointer.items():
        observed = pointer.get(key)
        if observed != expected:
            raise RuntimeError(
                f"production pointer {key} changed: expected {expected!r}, observed {observed!r}"
            )

    manifest_bytes = store.get(expectation.manifest_key)
    manifest_sha256 = sha256_bytes(manifest_bytes)
    if manifest_sha256 != expectation.manifest_sha256:
        raise RuntimeError(
            "production manifest bytes changed: "
            f"expected {expectation.manifest_sha256}, observed {manifest_sha256}"
        )
    try:
        manifest = _object(json.loads(manifest_bytes), "production manifest")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("production manifest is not valid UTF-8 JSON") from exc

    return {
        "status": "passed",
        "mode": "read_only",
        "pointer_key": PRODUCTION_POINTER_KEY,
        "pointer_sha256": pointer_sha256,
        "release_id": expectation.release_id,
        "manifest_key": expectation.manifest_key,
        "manifest_sha256": manifest_sha256,
        "manifest_schema_version": manifest.get("schema_version"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-read-only",
        action="store_true",
        help="required acknowledgement that this command performs reads only",
    )
    args = parser.parse_args()
    if not args.confirm_read_only:
        parser.error("--confirm-read-only is required")
    settings = Settings.from_env()
    store = create_object_store(settings)
    result = verify_production_baseline(store)
    print(json.dumps(result, indent=2, sort_keys=True))
    print("M10_PRODUCTION_BASELINE_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
