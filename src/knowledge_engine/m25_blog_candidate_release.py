from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from .compiler import CompiledRelease
from .config import Settings
from .errors import IntegrityError
from .m14_section_index import _tokens
from .m23_cloudflare_qdrant import (
    CLOUDFLARE_MODEL,
    QDRANT_DISTANCE,
    QDRANT_VECTOR_NAME,
    VECTOR_DIMENSION,
    CloudflareConfig,
    QdrantConfig,
    SectionInput,
    build_qdrant_points,
    embed_sections,
    preflight_qdrant_collection,
    upsert_qdrant_points,
)
from .publisher import publish_release
from .source import build_source_release
from .storage import create_object_store, sha256_bytes

PACK_SCHEMA = "knowledge-source-document-pack-admission/v1"
RECEIPT_SCHEMA = "knowledge-engine-m25-10-blog-candidate-deployment/v1"
PACK_RELATIVE = Path("documents/daniel-blog-en-156")
EXPECTED = {
    "master_inventory_sha256": "ee8589e4e2ce19005507fc5b9f3aa47d3c0320ab34848e81948c5cdaad7f729e",
    "batch_a_inventory_sha256": "734b6d5d346ad1e283d8d420332e6dab0f6c77074f7a4ed445bbcba62144f879",
    "batch_b_inventory_sha256": "f58b1be75093ad4f530e5317c35055a9b1cc21d56cef6b921550fd544b976988",
    "combined_nodes_sha256": "68f8040a790d55276ced5d19f67c022dc645d801dd2749c46739f91d9f031440",
    "combined_edges_sha256": "21c5a739a1bf2bcd78bdb032e71afc8b89d68b9c4180f626742567f39233aed8",
    "admission_sha256": "f5f01d82c7a1a38cf15fc54c890b904c4c015f608e2d25e294f9469f9b1927f2",
}
COUNTS = {
    "sources": 156,
    "series": 25,
    "articles": 156,
    "sections": 4041,
    "nodes": 4222,
    "edges": 8525,
    "semantic_documents": 4197,
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode()
    )


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M25-BLOG-LIVE-001 invalid JSON: {path}") from exc


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        values = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M25-BLOG-LIVE-002 invalid JSONL: {path}") from exc
    if any(not isinstance(value, dict) for value in values):
        raise IntegrityError(f"M25-BLOG-LIVE-003 non-object JSONL row: {path}")
    return values


def _excerpt(value: str, limit: int = 320) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _body_lines(raw: bytes, start: int, end: int) -> str:
    lines = raw.decode("utf-8").splitlines()
    if not 1 <= start <= end <= len(lines):
        raise IntegrityError(
            "M25-BLOG-LIVE-004 source locator is outside immutable bytes"
        )
    return "\n".join(lines[start - 1 : end]).strip()


def _stable_kos(node_id: str) -> str:
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    number = int(hashlib.sha256(node_id.encode()).hexdigest(), 16)
    chars = []
    for _ in range(26):
        chars.append(alphabet[number & 31])
        number >>= 5
    return "ko_" + "".join(reversed(chars))


def validate_pack(pack_root: Path) -> dict[str, Any]:
    admission = _load(pack_root / "admission.json")
    if admission.get("schema_version") != PACK_SCHEMA:
        raise IntegrityError("M25-BLOG-LIVE-005 admission schema drift")
    unsigned = dict(admission)
    claimed = unsigned.pop("admission_sha256", None)
    actual = hashlib.sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    if claimed != actual or claimed != EXPECTED["admission_sha256"]:
        raise IntegrityError("M25-BLOG-LIVE-006 admission authority digest mismatch")
    for field, digest in EXPECTED.items():
        if admission.get(field) != digest:
            raise IntegrityError(
                f"M25-BLOG-LIVE-007 accepted identity drift: {field}"
            )
    if admission.get("production_pointer_authorized") is not False:
        raise IntegrityError("M25-BLOG-LIVE-008 production pointer authority drift")
    if (
        admission.get("source_write_authorized") is not True
        or admission.get("candidate_release_authorized") is not True
    ):
        raise IntegrityError("M25-BLOG-LIVE-009 live authority missing")

    master = _load(pack_root / "master-inventory.json")
    batch_a = _load(pack_root / "batch-a-inventory.json")
    batch_b = _load(pack_root / "batch-b-inventory.json")
    if master.get("inventory_sha256") != EXPECTED["master_inventory_sha256"]:
        raise IntegrityError("M25-BLOG-LIVE-010 master inventory mismatch")
    if (
        batch_a.get("batch_inventory_sha256")
        != EXPECTED["batch_a_inventory_sha256"]
    ):
        raise IntegrityError("M25-BLOG-LIVE-011 Batch A inventory mismatch")
    if (
        batch_b.get("batch_inventory_sha256")
        != EXPECTED["batch_b_inventory_sha256"]
    ):
        raise IntegrityError("M25-BLOG-LIVE-012 Batch B inventory mismatch")

    nodes_path = pack_root / "candidate-nodes.jsonl"
    edges_path = pack_root / "candidate-edges.jsonl"
    if sha256_bytes(nodes_path.read_bytes()) != EXPECTED["combined_nodes_sha256"]:
        raise IntegrityError("M25-BLOG-LIVE-013 combined node bytes drift")
    if sha256_bytes(edges_path.read_bytes()) != EXPECTED["combined_edges_sha256"]:
        raise IntegrityError("M25-BLOG-LIVE-014 combined edge bytes drift")
    nodes = _jsonl(nodes_path)
    edges = _jsonl(edges_path)
    node_counts = Counter(node.get("node_type") for node in nodes)
    if node_counts != Counter({"Series": 25, "Article": 156, "Section": 4041}):
        raise IntegrityError("M25-BLOG-LIVE-015 node population drift")
    if len(edges) != COUNTS["edges"] or len(
        {edge.get("edge_id") for edge in edges}
    ) != len(edges):
        raise IntegrityError("M25-BLOG-LIVE-016 edge population drift")

    articles = master.get("articles")
    if not isinstance(articles, list) or len(articles) != COUNTS["sources"]:
        raise IntegrityError("M25-BLOG-LIVE-017 source population drift")
    source_bytes: dict[str, bytes] = {}
    article_by_id: dict[str, dict[str, Any]] = {}
    for article in articles:
        if not isinstance(article, dict):
            raise IntegrityError("M25-BLOG-LIVE-018 malformed article inventory")
        path = pack_root / "sources" / f"{article['slug']}.md"
        raw = path.read_bytes()
        if sha256_bytes(raw) != article.get("content_sha256"):
            raise IntegrityError(
                f"M25-BLOG-LIVE-019 immutable source mismatch: {article['slug']}"
            )
        source_bytes[article["article_id"]] = raw
        article_by_id[article["article_id"]] = article
    if len(source_bytes) != COUNTS["sources"]:
        raise IntegrityError("M25-BLOG-LIVE-020 duplicate source identity")
    return {
        "admission": admission,
        "master": master,
        "nodes": nodes,
        "edges": edges,
        "source_bytes": source_bytes,
        "article_by_id": article_by_id,
    }


def build_pack_artifacts(pack: Mapping[str, Any], release_id: str) -> dict[str, Any]:
    article_by_id = pack["article_by_id"]
    source_bytes = pack["source_bytes"]
    nodes = pack["nodes"]
    edges = pack["edges"]
    article_nodes = {
        node["source_article_id"]: node
        for node in nodes
        if node["node_type"] == "Article"
    }
    graph_nodes: list[dict[str, Any]] = []
    graph_v2_nodes: list[dict[str, Any]] = []
    lexical: list[dict[str, Any]] = []
    semantic: list[dict[str, Any]] = []
    source_index: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []

    for article_id, article in sorted(article_by_id.items()):
        raw = source_bytes[article_id]
        article_node = article_nodes[article_id]
        path = f"_documents/daniel-blog-en-156/sources/{article['slug']}.md"
        description = article.get("description") or article["title"]
        source_index.append(
            {
                "source_id": article_id,
                "title": article["title"],
                "canonical_url": article["canonical_url"],
                "series_id": article["series_id"],
                "series_title": article["series_title"],
                "path": path,
                "origin_repository": article["origin_repository"],
                "origin_commit": article["origin_commit"],
                "origin_path": article["origin_path"],
                "origin_blob_sha": article["origin_blob_sha"],
                "content_sha256": article["content_sha256"],
                "bytes": len(raw),
                "audience": "public",
            }
        )
        provenance.append(
            {
                "schema_version": "knowledge-source-document-provenance/v1",
                "source_id": article_id,
                "release_id": release_id,
                "origin": {
                    "repository": article["origin_repository"],
                    "commit": article["origin_commit"],
                    "path": article["origin_path"],
                    "blob_sha": article["origin_blob_sha"],
                    "content_sha256": article["content_sha256"],
                },
                "canonical_url": article["canonical_url"],
                "owner": article["owner"],
                "license": article["license"],
                "trust": article["trust"],
            }
        )
        text = "\n".join(
            filter(
                None,
                [article["title"], str(description), article["series_title"]],
            )
        )
        article_doc = {
            "concept_id": article_node["node_id"],
            "section_id": article_node["node_id"],
            "x_kos_id": _stable_kos(article_node["node_id"]),
            "title": article["title"],
            "section_title": "Article overview",
            "description": description,
            "excerpt": _excerpt(text),
            "body": text,
            "audience": "public",
            "path": path,
            "terms": _tokens(text),
            "node_type": "Article",
            "source_id": article_id,
            "series_id": article["series_id"],
            "canonical_url": article["canonical_url"],
        }
        lexical.append(article_doc)
        semantic.append(
            {
                "section_id": article_node["node_id"],
                "text": text,
                "payload": {
                    "release_id": release_id,
                    "node_type": "Article",
                    "source_id": article_id,
                    "article_node_id": article_node["node_id"],
                    "series_id": article["series_id"],
                    "title": article["title"],
                    "canonical_url": article["canonical_url"],
                    "audience": "public",
                    "source_commit_sha": article["origin_commit"],
                    "source_path": article["origin_path"],
                    "content_sha256": article["content_sha256"],
                },
            }
        )

    for node in nodes:
        node_id = node["node_id"]
        node_type = node["node_type"]
        source_id = node.get("source_article_id")
        article = article_by_id.get(source_id) if source_id else None
        path = (
            f"_documents/daniel-blog-en-156/sources/{article['slug']}.md"
            if article
            else "_documents/daniel-blog-en-156/master-inventory.json"
        )
        graph_nodes.append(
            {
                "concept_id": node_id,
                "x_kos_id": _stable_kos(node_id),
                "title": node["title"],
                "type": node_type,
                "audience": "public",
                "path": path,
            }
        )
        graph_v2_nodes.append(
            {
                "concept_id": node_id,
                "x_kos_id": _stable_kos(node_id),
                "title": node["title"],
                "description": f"Daniel blog {node_type.lower()} structural node",
                "type": node_type,
                "audience": "public",
                "status": "published",
                "confidence": 1.0,
                "tags": ["daniel-blog", node_type.lower()],
                "aliases": [],
                "path": path,
                "provenance_record": (
                    "_documents/daniel-blog-en-156/admission.json"
                ),
            }
        )
        if node_type != "Section":
            continue
        if article is None:
            raise IntegrityError(
                "M25-BLOG-LIVE-021 Section node lacks article inventory"
            )
        locator = node["source_locator"]
        body = _body_lines(
            source_bytes[source_id],
            locator["start_line"],
            locator["end_line"],
        )
        description = article.get("description") or article["title"]
        searchable = " ".join(
            (article["title"], node["title"], str(description), body)
        )
        lexical.append(
            {
                "concept_id": node["parent_article_node_id"],
                "section_id": node_id,
                "x_kos_id": _stable_kos(node_id),
                "title": article["title"],
                "section_title": node["title"],
                "description": description,
                "excerpt": _excerpt(body),
                "body": body,
                "audience": "public",
                "path": path,
                "terms": _tokens(searchable),
                "node_type": "Section",
                "source_id": source_id,
                "article_node_id": node["parent_article_node_id"],
                "series_id": article["series_id"],
                "canonical_url": article["canonical_url"],
                "source_locator": locator,
            }
        )
        semantic.append(
            {
                "section_id": node_id,
                "text": searchable,
                "payload": {
                    "release_id": release_id,
                    "node_type": "Section",
                    "source_id": source_id,
                    "article_node_id": node["parent_article_node_id"],
                    "section_node_id": node_id,
                    "series_id": article["series_id"],
                    "title": article["title"],
                    "section_title": node["title"],
                    "canonical_url": article["canonical_url"],
                    "audience": "public",
                    "source_commit_sha": article["origin_commit"],
                    "source_path": article["origin_path"],
                    "start_line": locator["start_line"],
                    "end_line": locator["end_line"],
                    "content_sha256": node["content_sha256"],
                },
            }
        )

    graph_edges = [
        {
            "from_concept_id": edge["source"],
            "to_concept_id": edge["target"],
            "type": edge["type"],
        }
        for edge in edges
    ]
    graph_v2_edges = [
        {
            "edge_id": edge["edge_id"],
            "source": edge["source"],
            "target": edge["target"],
            "relation_type": edge["type"],
            "directed": True,
            "audience": "public",
            "confidence": 1.0,
            "qualifiers": {},
            "review_status": "approved",
            "review_id": "m25-10-blog-source-admission",
            "provenance_record": (
                "_documents/daniel-blog-en-156/admission.json"
            ),
            "provenance_ref": "structural-source-layout",
            "generated_inverse": False,
        }
        for edge in edges
    ]
    lexical.sort(key=lambda item: (item["concept_id"], item["section_id"]))
    semantic.sort(key=lambda item: item["section_id"])
    if len(semantic) != COUNTS["semantic_documents"]:
        raise IntegrityError(
            "M25-BLOG-LIVE-022 semantic document population drift"
        )
    return {
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
        "graph_v2_nodes": graph_v2_nodes,
        "graph_v2_edges": graph_v2_edges,
        "lexical_documents": lexical,
        "semantic_inputs": semantic,
        "source_index": source_index,
        "provenance": provenance,
    }


def augment_release(
    compiled: CompiledRelease,
    pack_root: Path,
    release_time: datetime,
) -> tuple[CompiledRelease, dict[str, Any]]:
    pack = validate_pack(pack_root)
    base_manifest = compiled.manifest
    base_content = base_manifest["okf"]["content_sha256"]
    identity = hashlib.sha256(
        (base_content + pack["admission"]["admission_sha256"]).encode()
    ).hexdigest()
    stamp = release_time.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    release_id = f"{stamp}-{identity[:12]}"
    if compiled.release_id != release_id:
        target = compiled.release_root.parent / release_id
        if target.exists():
            shutil.rmtree(target)
        compiled.release_root.rename(target)
        compiled = CompiledRelease(
            release_id=release_id,
            release_root=target,
            manifest=compiled.manifest,
        )
    release_root = compiled.release_root
    bundle_documents = (
        release_root / "bundle" / "_documents" / "daniel-blog-en-156"
    )
    shutil.copytree(pack_root, bundle_documents)

    artifacts = build_pack_artifacts(pack, release_id)
    artifact_root = release_root / "artifacts"
    graph = _load(artifact_root / "graph.json")
    graph["nodes"].extend(artifacts["graph_nodes"])
    graph["edges"].extend(artifacts["graph_edges"])
    graph["nodes"].sort(key=lambda item: item["concept_id"])
    graph["edges"].sort(
        key=lambda item: (
            item["from_concept_id"],
            item["to_concept_id"],
            item["type"],
        )
    )
    _write(artifact_root / "graph.json", graph)

    graph_v2 = _load(artifact_root / "graph-v2.json")
    graph_v2["release"]["release_id"] = release_id
    graph_v2["nodes"].extend(artifacts["graph_v2_nodes"])
    graph_v2["edges"].extend(artifacts["graph_v2_edges"])
    graph_v2["nodes"].sort(key=lambda item: item["concept_id"])
    graph_v2["edges"].sort(key=lambda item: item["edge_id"])
    _write(artifact_root / "graph-v2.json", graph_v2)

    lexical = _load(artifact_root / "lexical-index.json")
    lexical["documents"].extend(artifacts["lexical_documents"])
    lexical["documents"].sort(
        key=lambda item: (item["concept_id"], item["section_id"])
    )
    _write(artifact_root / "lexical-index.json", lexical)

    provenance = _load(artifact_root / "provenance.json")
    provenance["records"].extend(artifacts["provenance"])
    _write(artifact_root / "provenance.json", provenance)
    _write(
        artifact_root / "source-index.json",
        {
            "schema_version": "knowledge-source-document-index/v1",
            "release_id": release_id,
            "sources": artifacts["source_index"],
        },
    )
    _write(
        artifact_root / "semantic-inputs.json",
        {
            "schema_version": "knowledge-engine-semantic-inputs/v1",
            "release_id": release_id,
            "model": CLOUDFLARE_MODEL,
            "vector_dimension": VECTOR_DIMENSION,
            "documents": artifacts["semantic_inputs"],
        },
    )
    _write(
        artifact_root / "blog-pack-admission.json",
        pack["admission"],
    )

    manifest = compiled.manifest
    manifest["release_id"] = release_id
    manifest["builder"]["build_id"] = f"build_{stamp}_{identity[:8]}"
    manifest["okf"]["bundle_prefix"] = f"releases/{release_id}/bundle/"
    manifest["okf"]["root_index"] = f"releases/{release_id}/bundle/index.md"
    manifest["okf"]["content_sha256"] = identity
    manifest["counts"].update(
        {
            "document_sources": COUNTS["sources"],
            "document_series": COUNTS["series"],
            "document_articles": COUNTS["articles"],
            "document_sections": COUNTS["sections"],
            "document_graph_nodes": COUNTS["nodes"],
            "document_graph_edges": COUNTS["edges"],
            "semantic_documents": COUNTS["semantic_documents"],
        }
    )
    manifest["document_pack"] = {
        "pack_id": "daniel-blog-en-156",
        "admission_sha256": pack["admission"]["admission_sha256"],
        "master_inventory_sha256": EXPECTED["master_inventory_sha256"],
        "combined_nodes_sha256": EXPECTED["combined_nodes_sha256"],
        "combined_edges_sha256": EXPECTED["combined_edges_sha256"],
    }
    replaced = {
        "graph",
        "graph_v2",
        "lexical_index",
        "provenance",
        "source_snapshot",
    }
    manifest["artifacts"] = [
        item for item in manifest["artifacts"] if item["kind"] not in replaced
    ]
    specs = [
        ("graph", "artifacts/graph.json"),
        ("graph_v2", "artifacts/graph-v2.json"),
        ("lexical_index", "artifacts/lexical-index.json"),
        ("provenance", "artifacts/provenance.json"),
        ("source_snapshot", "artifacts/source-snapshot.json"),
        ("document_source_index", "artifacts/source-index.json"),
        ("semantic_inputs", "artifacts/semantic-inputs.json"),
        ("document_pack_admission", "artifacts/blog-pack-admission.json"),
    ]
    for kind, relative in specs:
        path = release_root / relative
        data = path.read_bytes()
        manifest["artifacts"].append(
            {
                "kind": kind,
                "key": f"releases/{release_id}/{relative}",
                "sha256": sha256_bytes(data),
                "bytes": len(data),
                "media_type": "application/json",
                "audiences": ["public"],
                "required": True,
            }
        )
    for item in manifest["artifacts"]:
        key = item["key"]
        if key.startswith("releases/"):
            suffix = key.split("/", 2)[2]
            item["key"] = f"releases/{release_id}/{suffix}"
    manifest["artifacts"].sort(key=lambda item: item["kind"])
    _write(release_root / "manifest.json", manifest)
    return compiled, {
        "release_id": release_id,
        "manifest": manifest,
        "semantic_inputs": artifacts["semantic_inputs"],
    }


def create_candidate_collection(
    config: QdrantConfig,
    client: httpx.Client | None = None,
) -> None:
    owned = client is None
    http = client or httpx.Client(timeout=config.timeout_seconds)
    try:
        response = http.put(
            f"{config.base_url.rstrip('/')}/collections/{config.collection_name}",
            headers={
                "api-key": config.api_key,
                "Content-Type": "application/json",
            },
            json={
                "vectors": {
                    QDRANT_VECTOR_NAME: {
                        "size": VECTOR_DIMENSION,
                        "distance": QDRANT_DISTANCE,
                    }
                }
            },
        )
        if response.status_code not in {200, 201}:
            raise IntegrityError(
                "M25-BLOG-LIVE-023 Qdrant collection create failed: "
                f"{response.status_code}"
            )
    finally:
        if owned:
            http.close()


def deploy_candidate(
    *,
    source_url: str,
    source_sha: str,
    foundation_sha: str,
    channel: str,
    work_dir: Path,
    release_time: datetime,
    allow_live: bool,
) -> dict[str, Any]:
    if not channel.startswith("candidate-blog-"):
        raise IntegrityError("M25-BLOG-LIVE-024 candidate channel prefix required")
    compiled, snapshot = build_source_release(
        repository_url=source_url,
        repository="danielcanfly/knowledge-source",
        source_commit_sha=source_sha,
        foundation_commit_sha=foundation_sha,
        work_root=work_dir,
        release_time=release_time,
    )
    pack_root = work_dir / "source-checkout" / PACK_RELATIVE
    compiled, augmented = augment_release(compiled, pack_root, release_time)
    settings = Settings.from_env()
    store = create_object_store(settings)

    semantic_rows = augmented["semantic_inputs"]
    sections = [
        SectionInput(
            section_id=row["section_id"],
            text=row["text"],
            payload=row["payload"],
        )
        for row in semantic_rows
    ]
    qdrant_receipt: dict[str, Any] = {
        "executed": False,
        "point_count": len(sections),
    }
    if allow_live:
        cf = CloudflareConfig(
            account_id=os.environ["CLOUDFLARE_ACCOUNT_ID"],
            api_token=os.environ["CLOUDFLARE_API_TOKEN"],
        )
        collection_name = (
            f"m25_blog_{augmented['release_id'].replace('-', '_').lower()}"
        )
        qd = QdrantConfig(
            base_url=os.environ["QDRANT_URL"],
            api_key=os.environ["QDRANT_API_KEY"],
            collection_name=collection_name,
        )
        create_candidate_collection(qd)
        vectors = embed_sections(sections, cf)
        points = build_qdrant_points(sections, vectors)
        for point in points:
            point["payload"].update(
                {
                    "canonical_knowledge": False,
                    "candidate_release_eligible": True,
                    "candidate_release_id": augmented["release_id"],
                    "candidate_channel": channel,
                    "production_authority": False,
                }
            )
        response = upsert_qdrant_points(points, qd, allow_write=True)
        readback = preflight_qdrant_collection(qd)
        if readback.get("points_count") != len(points):
            raise IntegrityError(
                "M25-BLOG-LIVE-025 Qdrant point count readback mismatch"
            )
        qdrant_receipt = {
            "executed": True,
            "collection": collection_name,
            "point_count": len(points),
            "vector_dimension": VECTOR_DIMENSION,
            "model": CLOUDFLARE_MODEL,
            "points_sha256": hashlib.sha256(_canonical(points)).hexdigest(),
            "vector_sha256": hashlib.sha256(_canonical(vectors)).hexdigest(),
            "response": response,
            "readback": readback,
        }

    publication = publish_release(
        store=store,
        compiled=compiled,
        channel=channel,
        promoted_at=(
            release_time.astimezone(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
    )
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": (
            "candidate_release_published_and_indexed"
            if allow_live
            else "candidate_release_preview_built"
        ),
        "source_sha": source_sha,
        "source_snapshot_sha256": snapshot["content_sha256"],
        "release_id": augmented["release_id"],
        "manifest_sha256": publication.manifest_sha256,
        "channel": channel,
        "r2_published": settings.object_store_backend == "r2",
        "qdrant": qdrant_receipt,
        "document_sources": 156,
        "semantic_documents": 4197,
        "graph_nodes": 4222,
        "graph_edges": 8525,
        "production_pointer_mutated": False,
        "production_traffic_mutated": False,
    }
    receipt["receipt_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    _write(work_dir / "m25-10-deployment-receipt.json", receipt)
    return receipt


def _time(value: str) -> datetime:
    if not value.endswith("Z"):
        raise argparse.ArgumentTypeError("time must end in Z")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge-m25-blog-deploy")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--foundation-sha", required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--release-time", type=_time, required=True)
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args(argv)
    result = deploy_candidate(
        source_url=args.source_url,
        source_sha=args.source_sha,
        foundation_sha=args.foundation_sha,
        channel=args.channel,
        work_dir=args.work_dir,
        release_time=args.release_time,
        allow_live=args.allow_live,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
