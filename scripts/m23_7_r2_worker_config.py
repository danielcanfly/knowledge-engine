from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"M23.7-R2.1 missing required environment variable: {name}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the untracked M23.7 R2.1 Wrangler placement config"
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    qdrant_url = _required_env("QDRANT_URL")
    parsed = urlparse(qdrant_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SystemExit("M23.7-R2.1 QDRANT_URL must be an HTTPS endpoint")

    config = {
        "$schema": "node_modules/wrangler/config-schema.json",
        "name": "knowledge-engine-m23-7-r2-binding",
        "main": "worker.mjs",
        "compatibility_date": "2026-07-15",
        "compatibility_flags": ["nodejs_compat"],
        "ai": {"binding": "AI"},
        "placement": {"hostname": parsed.hostname},
        "observability": {
            "enabled": True,
            "head_sampling_rate": 1,
            "logs": {"invocation_logs": False},
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    output.write_text(raw, encoding="utf-8")
    print(
        "M23.7_R2_1_WRANGLER_CONFIG "
        f"config_sha256={hashlib.sha256(raw.encode()).hexdigest()} "
        f"hostname_sha256={hashlib.sha256(parsed.hostname.encode()).hexdigest()} "
        f"output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
