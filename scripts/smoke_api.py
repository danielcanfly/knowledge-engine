#!/usr/bin/env python3
from __future__ import annotations

import argparse

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", default=None)
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=20) as client:
        health = client.get("/v1/health")
        health.raise_for_status()
        current = client.get("/v1/releases/current")
        current.raise_for_status()
        query = client.post("/v1/query", json={"query": "knowledge compiler"})
        query.raise_for_status()
        if not query.json().get("results"):
            raise RuntimeError("smoke query returned no results")
    print("API_SMOKE_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
