from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCHEMA = "knowledge-engine-m26-pa7-full-graph-readonly-inventory/v1"
MAX_JSON_BYTES = 80 * 1024 * 1024


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def infer_counts(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, dict):
        return None, None
    node_keys = ("nodes", "vertices", "concepts")
    edge_keys = ("edges", "links", "relations")
    nodes = next((len(value[key]) for key in node_keys if isinstance(value.get(key), list)), None)
    edges = next((len(value[key]) for key in edge_keys if isinstance(value.get(key), list)), None)
    counts = value.get("counts")
    if isinstance(counts, dict):
        if nodes is None:
            for key in ("nodes", "concepts", "vertices"):
                if isinstance(counts.get(key), int):
                    nodes = counts[key]
                    break
        if edges is None:
            for key in ("edges", "relations", "links"):
                if isinstance(counts.get(key), int):
                    edges = counts[key]
                    break
    graph = value.get("graph")
    if isinstance(graph, dict) and nodes is None and edges is None:
        return infer_counts(graph)
    return nodes, edges


def local_inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        lowered = path.name.lower()
        if "graph" not in lowered and "manifest" not in lowered and "pointer" not in lowered:
            continue
        try:
            size = path.stat().st_size
            if size > MAX_JSON_BYTES:
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
            nodes, edges = infer_counts(value)
            if nodes is None and edges is None:
                continue
            rows.append(
                {
                    "location": "repository",
                    "path": path.relative_to(root).as_posix(),
                    "bytes": size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "node_count": nodes,
                    "edge_count": edges,
                }
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    return rows


def r2_inventory() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    bucket = os.environ.get("R2_BUCKET", "").strip()
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    metadata = {
        "configured": bool(endpoint and bucket and access_key and secret_key),
        "endpoint_sha256": sha256_text(endpoint) if endpoint else None,
        "bucket_sha256": sha256_text(bucket) if bucket else None,
    }
    if not metadata["configured"]:
        return [], metadata

    import boto3  # type: ignore

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    candidates: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        response = client.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            key = str(item.get("Key", ""))
            lowered = key.lower()
            size = int(item.get("Size", 0))
            if not key.endswith(".json") or size > MAX_JSON_BYTES:
                continue
            if not any(term in lowered for term in ("graph", "manifest", "pointer", "release")):
                continue
            try:
                body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
                value = json.loads(body)
                nodes, edges = infer_counts(value)
                if nodes is None and edges is None:
                    continue
                candidates.append(
                    {
                        "location": "r2",
                        "key_sha256": sha256_text(key),
                        "key_suffix": "/".join(key.split("/")[-3:]),
                        "bytes": size,
                        "etag": str(item.get("ETag", "")).strip('"'),
                        "content_sha256": hashlib.sha256(body).hexdigest(),
                        "node_count": nodes,
                        "edge_count": edges,
                    }
                )
            except Exception as exc:
                candidates.append(
                    {
                        "location": "r2",
                        "key_sha256": sha256_text(key),
                        "key_suffix": "/".join(key.split("/")[-3:]),
                        "bytes": size,
                        "inspection_error_class": type(exc).__name__,
                    }
                )
        if not response.get("IsTruncated"):
            break
        token = response.get("NextContinuationToken")
    return candidates, metadata


def request_json(url: str, api_key: str) -> dict[str, Any]:
    request = Request(url, headers={"api-key": api_key, "accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        value = json.loads(response.read())
    if not isinstance(value, dict):
        raise ValueError("response is not an object")
    return value


def qdrant_inventory() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base = os.environ.get("QDRANT_URL", "").strip().rstrip("/")
    api_key = (
        os.environ.get("QDRANT_API_KEY_READ", "").strip()
        or os.environ.get("QDRANT_READ_ONLY_API_KEY", "").strip()
    )
    metadata = {
        "configured": bool(base and api_key),
        "endpoint_sha256": sha256_text(base) if base else None,
    }
    if not metadata["configured"]:
        return [], metadata
    rows: list[dict[str, Any]] = []
    try:
        listing = request_json(f"{base}/collections", api_key)
        collections = listing.get("result", {}).get("collections", [])
        for collection in collections:
            name = str(collection.get("name", ""))
            if not name:
                continue
            detail = request_json(f"{base}/collections/{name}", api_key).get("result", {})
            rows.append(
                {
                    "name": name,
                    "points_count": detail.get("points_count"),
                    "indexed_vectors_count": detail.get("indexed_vectors_count"),
                    "vectors_count": detail.get("vectors_count"),
                    "status": detail.get("status"),
                }
            )
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        metadata["inspection_error_class"] = type(exc).__name__
    return rows, metadata


def rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("node_count") or 0) + int(row.get("edge_count") or 0),
            int(row.get("bytes") or 0),
        ),
        reverse=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    local = local_inventory(args.root.resolve())
    r2, r2_meta = r2_inventory()
    qdrant, qdrant_meta = qdrant_inventory()
    ranked = rank(local + [row for row in r2 if "node_count" in row or "edge_count" in row])
    likely_full = [
        row
        for row in ranked
        if int(row.get("node_count") or 0) >= 1000
        or int(row.get("edge_count") or 0) >= 1000
    ]
    status = (
        "full_graph_candidates_found"
        if likely_full
        else "full_graph_candidate_not_found"
    )
    report = {
        "schema_version": SCHEMA,
        "status": status,
        "repository_candidates": local,
        "r2": r2_meta,
        "r2_candidates": r2,
        "qdrant": qdrant_meta,
        "qdrant_collections": qdrant,
        "ranked_graph_candidates": ranked[:50],
        "likely_full_graph_candidates": likely_full[:20],
        "mutation_counts": {
            "r2_writes": 0,
            "qdrant_writes": 0,
            "production_pointer_writes": 0,
            "canonical_writes": 0,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(report["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
