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
    slugify,
    write_json,
    write_jsonl,
)


def _record_digest(record: dict[str, Any]) -> str:
    unsigned = dict(record)
    unsigned.pop("record_sha256", None)
    return sha256(unsigned)


def build_catalog_label_index(catalog: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for entry in catalog:
        normalized = slugify(entry["label_en_clean"])
        existing = index.get(normalized)
        if existing is not None and existing != entry["key"]:
            raise IntegrityError(
                "M25-BLOG-ALIAS-001 normalized catalog label maps to multiple keys"
            )
        index[normalized] = entry["key"]
    return index


def converge_series_aliases(
    records: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    label_index = build_catalog_label_index(catalog)
    clean: list[dict[str, Any]] = []
    convergence_count = 0

    for value in records:
        record = json.loads(json.dumps(value))
        if record["series_key"] != "standalone":
            normalized_title = slugify(record["series_title"])
            catalog_key = label_index.get(normalized_title)
            if catalog_key is not None and catalog_key != record["series_key"]:
                record["series_key"] = catalog_key
                record["series_id"] = f"series_{catalog_key}"
                record["partition_group_id"] = record["series_id"]
                record["series_resolution_source"] = (
                    "frontmatter_catalog_label_alias"
                )
                convergence_count += 1
        record["record_sha256"] = _record_digest(record)
        clean.append(record)

    title_to_ids: dict[str, set[str]] = defaultdict(set)
    id_to_titles: dict[str, set[str]] = defaultdict(set)
    for record in clean:
        normalized_title = slugify(record["series_title"])
        title_to_ids[normalized_title].add(record["series_id"])
        id_to_titles[record["series_id"]].add(normalized_title)

    split_titles = {
        title: sorted(ids) for title, ids in title_to_ids.items() if len(ids) != 1
    }
    split_ids = {
        series_id: sorted(titles)
        for series_id, titles in id_to_titles.items()
        if len(titles) != 1
    }
    if split_titles or split_ids:
        raise IntegrityError(
            "M25-BLOG-ALIAS-002 series title/key identity is not one-to-one: "
            + json.dumps(
                {"split_titles": split_titles, "split_ids": split_ids},
                sort_keys=True,
            )
        )
    return clean, convergence_count


def build_converged_batch(
    *,
    repository: str,
    commit: str,
    expected_count: int,
    batch_size: int,
    output_dir: Path,
    client: GitHubClient,
) -> dict[str, Any]:
    if expected_count != batch_size * 2:
        raise IntegrityError(
            "M25-BLOG-ALIAS-003 expected count must equal two equal batches"
        )

    tree = client.tree(repository, commit)
    article_blobs = sorted(
        (blob for blob in tree if ARTICLE_PATH_RE.fullmatch(blob.path)),
        key=lambda item: item.path,
    )
    if len(article_blobs) != expected_count:
        raise IntegrityError(
            f"M25-BLOG-ALIAS-004 expected {expected_count} articles, "
            f"found {len(article_blobs)}"
        )

    catalog_candidates = [blob for blob in tree if blob.path == SERIES_META_PATH]
    if len(catalog_candidates) != 1:
        raise IntegrityError("M25-BLOG-ALIAS-005 exact series catalog blob missing")
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
            raise IntegrityError("M25-BLOG-ALIAS-006 duplicate article slug")
        raw_by_slug[record["slug"]] = raw
        records.append(record)

    records, convergence_count = converge_series_aliases(records, catalog)
    batch_a, batch_b, selected_groups = partition_by_groups(
        records, batch_size=batch_size
    )

    master_ids = {item["article_id"] for item in records}
    a_ids = {item["article_id"] for item in batch_a}
    b_ids = {item["article_id"] for item in batch_b}
    if a_ids & b_ids or a_ids | b_ids != master_ids:
        raise IntegrityError("M25-BLOG-ALIAS-007 A/B reconciliation failed")
    if len(batch_a) != batch_size or len(batch_b) != batch_size:
        raise IntegrityError("M25-BLOG-ALIAS-008 batch sizes drifted")

    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    for existing in source_dir.glob("*.md"):
        existing.unlink()
    for record in batch_a:
        (source_dir / f"{record['slug']}.md").write_bytes(
            raw_by_slug[record["slug"]]
        )

    nodes, edges = build_nodes_and_edges(batch_a, raw_by_slug)
    series_ids = {item["series_id"] for item in records}
    formal_series_ids = series_ids - {"series_standalone"}
    formal_series_titles = {
        item["series_title"]
        for item in records
        if item["series_id"] != "series_standalone"
    }
    if len(formal_series_ids) != len(formal_series_titles):
        raise IntegrityError(
            "M25-BLOG-ALIAS-009 formal series IDs and titles are not one-to-one"
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
            "series_catalog_blob_sha": catalog_blob.sha,
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

    batch_a_series_ids = {item["series_id"] for item in batch_a}
    batch_a_series_titles = {item["series_title"] for item in batch_a}
    if len(batch_a_series_ids) != len(batch_a_series_titles):
        raise IntegrityError(
            "M25-BLOG-ALIAS-010 Batch A series IDs and titles are not one-to-one"
        )

    receipt = sign(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "batch_a_candidate_graph_receipt",
            "status": "batch_a_acquired_candidate_structural_nodes_ready",
            "origin_repository": repository,
            "origin_commit": commit,
            "master_inventory_sha256": master["inventory_sha256"],
            "batch_a_inventory_sha256": manifest_a["batch_inventory_sha256"],
            "batch_b_inventory_sha256": manifest_b["batch_inventory_sha256"],
            "series_catalog_blob_sha": catalog_blob.sha,
            "series_catalog_sha256": sha256(catalog_raw),
            "master_source_count": len(records),
            "formal_series_count": len(formal_series_ids),
            "parent_collection_count": len(series_ids),
            "standalone_article_count": standalone_count,
            "catalog_fallback_article_count": fallback_count,
            "series_alias_convergence_count": convergence_count,
            "batch_a_source_count": len(batch_a),
            "batch_b_source_count": len(batch_b),
            "intersection_count": len(a_ids & b_ids),
            "missing_count": len(master_ids - (a_ids | b_ids)),
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
                "bind_exact_batch_a_inventory_and_candidate_graph_to_review_authority"
            ),
        },
        "receipt_sha256",
    )

    write_json(output_dir / "master-inventory.json", master)
    write_json(output_dir / "batch-a-inventory.json", manifest_a)
    write_json(output_dir / "batch-b-inventory.json", manifest_b)
    write_jsonl(output_dir / "candidate-nodes.jsonl", nodes)
    write_jsonl(output_dir / "candidate-edges.jsonl", edges)
    write_json(output_dir / "batch-a-receipt.json", receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="knowledge-m25-blog-series-convergence"
    )
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
        receipt = build_converged_batch(
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
