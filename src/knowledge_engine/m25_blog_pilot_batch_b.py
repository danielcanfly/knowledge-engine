from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .m25_blog_pilot import (
    ARTICLE_PATH_RE,
    SCHEMA_VERSION,
    SERIES_META_PATH,
    GitHubClient,
    build_article_record,
    build_nodes_and_edges,
    parse_series_catalog,
    partition_by_groups,
    sha256,
    sign,
    write_json,
    write_jsonl,
)
from .m25_blog_series_convergence import converge_series_aliases

ACCEPTED_MASTER_INVENTORY_SHA256 = (
    "ee8589e4e2ce19005507fc5b9f3aa47d3c0320ab34848e81948c5cdaad7f729e"
)
ACCEPTED_BATCH_A_INVENTORY_SHA256 = (
    "734b6d5d346ad1e283d8d420332e6dab0f6c77074f7a4ed445bbcba62144f879"
)
ACCEPTED_BATCH_B_INVENTORY_SHA256 = (
    "f58b1be75093ad4f530e5317c35055a9b1cc21d56cef6b921550fd544b976988"
)


def assemble_inventory_bundle(
    *,
    repository: str,
    commit: str,
    expected_count: int,
    batch_size: int,
    records: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    catalog_blob_sha: str,
    catalog_raw: bytes,
    convergence_count: int,
) -> dict[str, Any]:
    if expected_count != batch_size * 2:
        raise IntegrityError(
            "M25-BLOG-B-001 expected count must equal two equal batches"
        )

    batch_a, batch_b, selected_groups = partition_by_groups(
        records, batch_size=batch_size
    )
    master_ids = {item["article_id"] for item in records}
    a_ids = {item["article_id"] for item in batch_a}
    b_ids = {item["article_id"] for item in batch_b}
    if a_ids & b_ids or a_ids | b_ids != master_ids:
        raise IntegrityError("M25-BLOG-B-002 A/B reconciliation failed")
    if len(batch_a) != batch_size or len(batch_b) != batch_size:
        raise IntegrityError("M25-BLOG-B-003 batch sizes drifted")

    series_ids = {item["series_id"] for item in records}
    formal_series_ids = series_ids - {"series_standalone"}
    formal_series_titles = {
        item["series_title"]
        for item in records
        if item["series_id"] != "series_standalone"
    }
    if len(formal_series_ids) != len(formal_series_titles):
        raise IntegrityError(
            "M25-BLOG-B-004 formal series IDs and titles are not one-to-one"
        )

    group_counts: dict[str, int] = defaultdict(int)
    for record in records:
        group_counts[record["partition_group_id"]] += 1
    standalone_count = sum(
        item["series_id"] == "series_standalone" for item in records
    )
    fallback_count = sum(
        item["series_resolution_source"] == "series_catalog_fallback"
        for item in records
    )

    master = sign(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "master_inventory",
            "origin_repository": repository,
            "origin_commit": commit,
            "language": "en",
            "expected_article_count": expected_count,
            "article_count": len(records),
            "formal_series_count": len(formal_series_ids),
            "parent_collection_count": len(series_ids),
            "partition_group_count": len(group_counts),
            "standalone_article_count": standalone_count,
            "catalog_fallback_article_count": fallback_count,
            "series_alias_convergence_count": convergence_count,
            "series_catalog_path": SERIES_META_PATH,
            "series_catalog_blob_sha": catalog_blob_sha,
            "series_catalog_sha256": sha256(catalog_raw),
            "series_catalog_entry_count": len(catalog),
            "series_catalog": catalog,
            "articles": records,
        },
        "inventory_sha256",
    )
    manifest_a = sign(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "batch_inventory",
            "batch_id": "M25.9A-BLOG-A",
            "master_inventory_sha256": master["inventory_sha256"],
            "origin_repository": repository,
            "origin_commit": commit,
            "source_count": len(batch_a),
            "selected_partition_groups": selected_groups,
            "articles": batch_a,
        },
        "batch_inventory_sha256",
    )
    manifest_b = sign(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "batch_inventory",
            "batch_id": "M25.9A-BLOG-B",
            "master_inventory_sha256": master["inventory_sha256"],
            "origin_repository": repository,
            "origin_commit": commit,
            "source_count": len(batch_b),
            "articles": batch_b,
        },
        "batch_inventory_sha256",
    )
    return {
        "master": master,
        "manifest_a": manifest_a,
        "manifest_b": manifest_b,
        "batch_a": batch_a,
        "batch_b": batch_b,
        "master_ids": master_ids,
        "a_ids": a_ids,
        "b_ids": b_ids,
    }


def validate_accepted_baseline(
    bundle: dict[str, Any],
    *,
    expected_master_sha256: str = ACCEPTED_MASTER_INVENTORY_SHA256,
    expected_batch_a_sha256: str = ACCEPTED_BATCH_A_INVENTORY_SHA256,
    expected_batch_b_sha256: str = ACCEPTED_BATCH_B_INVENTORY_SHA256,
) -> None:
    actual = {
        "master": bundle["master"]["inventory_sha256"],
        "batch_a": bundle["manifest_a"]["batch_inventory_sha256"],
        "batch_b": bundle["manifest_b"]["batch_inventory_sha256"],
    }
    expected = {
        "master": expected_master_sha256,
        "batch_a": expected_batch_a_sha256,
        "batch_b": expected_batch_b_sha256,
    }
    if actual != expected:
        raise IntegrityError(
            "M25-BLOG-B-005 accepted inventory baseline drifted: "
            + json.dumps({"actual": actual, "expected": expected}, sort_keys=True)
        )


def validate_graph_identity(
    records: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
) -> None:
    series_ids = {item["series_id"] for item in records}
    series_titles = {item["series_title"] for item in records}
    if len(series_ids) != len(series_titles):
        raise IntegrityError(
            "M25-BLOG-B-006 Batch B series IDs and titles are not one-to-one"
        )
    series_nodes = [node for node in nodes if node["node_type"] == "Series"]
    if len(series_nodes) != len(series_ids):
        raise IntegrityError(
            "M25-BLOG-B-007 Batch B Series-node population drifted"
        )
    article_ids = {item["article_id"] for item in records}
    article_nodes = [node for node in nodes if node["node_type"] == "Article"]
    if {node["source_article_id"] for node in article_nodes} != article_ids:
        raise IntegrityError(
            "M25-BLOG-B-008 Batch B Article-node population drifted"
        )
    for node in nodes:
        if node["node_type"] in {"Article", "Section"}:
            locator = node.get("source_locator")
            if not isinstance(locator, dict):
                raise IntegrityError("M25-BLOG-B-009 node source locator missing")
            required = {
                "origin_repository",
                "origin_commit",
                "origin_path",
                "start_line",
                "end_line",
            }
            if set(locator) != required:
                raise IntegrityError("M25-BLOG-B-010 node source locator incomplete")
        elif node["node_type"] == "Series":
            if not node.get("source_article_ids"):
                raise IntegrityError(
                    "M25-BLOG-B-011 Series node lacks source article lineage"
                )


def build_batch_b(
    *,
    repository: str,
    commit: str,
    expected_count: int,
    batch_size: int,
    output_dir: Path,
    client: GitHubClient,
) -> dict[str, Any]:
    tree = client.tree(repository, commit)
    article_blobs = sorted(
        (blob for blob in tree if ARTICLE_PATH_RE.fullmatch(blob.path)),
        key=lambda item: item.path,
    )
    if len(article_blobs) != expected_count:
        raise IntegrityError(
            f"M25-BLOG-B-012 expected {expected_count} articles, "
            f"found {len(article_blobs)}"
        )

    catalog_candidates = [blob for blob in tree if blob.path == SERIES_META_PATH]
    if len(catalog_candidates) != 1:
        raise IntegrityError("M25-BLOG-B-013 exact series catalog blob missing")
    catalog_blob = catalog_candidates[0]
    catalog_raw = client.blob(repository, catalog_blob.sha)
    catalog = parse_series_catalog(catalog_raw)

    records: list[dict[str, Any]] = []
    raw_by_slug: dict[str, bytes] = {}
    for tree_blob in article_blobs:
        raw = client.blob(repository, tree_blob.sha)
        record = build_article_record(
            repository=repository,
            commit=commit,
            tree_blob=tree_blob,
            raw=raw,
            series_catalog=catalog,
        )
        if record["slug"] in raw_by_slug:
            raise IntegrityError("M25-BLOG-B-014 duplicate article slug")
        raw_by_slug[record["slug"]] = raw
        records.append(record)

    records, convergence_count = converge_series_aliases(records, catalog)
    bundle = assemble_inventory_bundle(
        repository=repository,
        commit=commit,
        expected_count=expected_count,
        batch_size=batch_size,
        records=records,
        catalog=catalog,
        catalog_blob_sha=catalog_blob.sha,
        catalog_raw=catalog_raw,
        convergence_count=convergence_count,
    )
    validate_accepted_baseline(bundle)

    batch_b = bundle["batch_b"]
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    for existing in source_dir.glob("*.md"):
        existing.unlink()
    for record in batch_b:
        raw = raw_by_slug[record["slug"]]
        if sha256(raw) != record["content_sha256"]:
            raise IntegrityError("M25-BLOG-B-015 content digest drifted")
        (source_dir / f"{record['slug']}.md").write_bytes(raw)

    nodes, edges = build_nodes_and_edges(batch_b, raw_by_slug)
    validate_graph_identity(batch_b, nodes)

    receipt = sign(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "batch_b_candidate_graph_receipt",
            "status": "batch_b_acquired_candidate_structural_nodes_ready",
            "origin_repository": repository,
            "origin_commit": commit,
            "accepted_predecessor_sha": (
                "6286a21d67164ded2cb677618ffe95db8db10938"
            ),
            "master_inventory_sha256": bundle["master"]["inventory_sha256"],
            "batch_a_inventory_sha256": bundle["manifest_a"][
                "batch_inventory_sha256"
            ],
            "batch_b_inventory_sha256": bundle["manifest_b"][
                "batch_inventory_sha256"
            ],
            "series_catalog_blob_sha": catalog_blob.sha,
            "series_catalog_sha256": sha256(catalog_raw),
            "master_source_count": len(records),
            "formal_series_count": bundle["master"]["formal_series_count"],
            "parent_collection_count": bundle["master"][
                "parent_collection_count"
            ],
            "standalone_article_count": bundle["master"][
                "standalone_article_count"
            ],
            "catalog_fallback_article_count": bundle["master"][
                "catalog_fallback_article_count"
            ],
            "series_alias_convergence_count": convergence_count,
            "batch_a_source_count": len(bundle["batch_a"]),
            "batch_b_source_count": len(batch_b),
            "intersection_count": len(bundle["a_ids"] & bundle["b_ids"]),
            "missing_count": len(
                bundle["master_ids"] - (bundle["a_ids"] | bundle["b_ids"])
            ),
            "snapshot_count": len(list(source_dir.glob("*.md"))),
            "node_count": len(nodes),
            "series_node_count": sum(
                node["node_type"] == "Series" for node in nodes
            ),
            "article_node_count": sum(
                node["node_type"] == "Article" for node in nodes
            ),
            "section_node_count": sum(
                node["node_type"] == "Section" for node in nodes
            ),
            "edge_count": len(edges),
            "nodes_sha256": sha256(nodes),
            "edges_sha256": sha256(edges),
            "semantic_claim_promotion_permitted": False,
            "source_write_permitted": False,
            "production_mutation_permitted": False,
            "m25_9b_authorized": False,
            "m25_9c_authorized": False,
            "next_legal_action": (
                "bind_exact_batch_b_inventory_and_candidate_graph_to_review_authority"
            ),
        },
        "receipt_sha256",
    )

    write_json(output_dir / "master-inventory.json", bundle["master"])
    write_json(output_dir / "batch-a-inventory.json", bundle["manifest_a"])
    write_json(output_dir / "batch-b-inventory.json", bundle["manifest_b"])
    write_jsonl(output_dir / "candidate-nodes.jsonl", nodes)
    write_jsonl(output_dir / "candidate-edges.jsonl", edges)
    write_json(output_dir / "batch-b-receipt.json", receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge-m25-blog-pilot-batch-b")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--batch-size", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = os.environ.get("BLOG_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        receipt = build_batch_b(
            repository=args.repository,
            commit=args.commit,
            expected_count=args.expected_count,
            batch_size=args.batch_size,
            output_dir=args.output_dir,
            client=GitHubClient(token),
        )
    except IntegrityError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
