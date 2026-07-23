from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import tempfile
import urllib.parse
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .compiler import CompiledRelease
from .config import Settings
from .errors import IntegrityError
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
)
from .m25_blog_candidate_release import (
    COUNTS,
    EXPECTED,
    PACK_SCHEMA,
    build_pack_artifacts,
    validate_pack,
)
from .m25_blog_pilot import GitHubClient, write_json
from .m25_blog_pilot_batch_b import build_batch_b
from .m25_blog_series_convergence import build_converged_batch
from .publisher import publish_release
from .storage import create_object_store, sha256_bytes

SOURCE_REPOSITORY = "danielcanfly/knowledge-source"
SOURCE_SHA = "5250f8422f4fa08c1f3dc84840dc756850817635"
UPSTREAM_REPOSITORY = "huaihsuanbusiness/daniel-blog"
UPSTREAM_COMMIT = "97821b6547ce3c0b8b8acf11cbbf4795684df458"
FOUNDATION_SHA = "e53af5833193a644a4d7397b7d466ababb5e1373"
ADMISSION_SHA = EXPECTED["admission_sha256"]
ANSWER_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
RECEIPT_SCHEMA = "knowledge-engine-m25-10-live-candidate/v1"
SITE_PROJECT = "llm-wiki-m24-internal"
SITE_HOSTNAME = "m24-internal.danielcanfly.com"
RUNTIME_NAME = "llm-wiki-m25-blog-candidate-runtime"
RUNTIME_ROUTE = f"{SITE_HOSTNAME}/api/m25/*"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M25-LIVE-001 invalid JSON: {path}") from exc


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        values = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M25-LIVE-002 invalid JSONL: {path}") from exc
    if any(not isinstance(value, dict) for value in values):
        raise IntegrityError(f"M25-LIVE-003 non-object JSONL row: {path}")
    return values


def _admission() -> dict[str, Any]:
    value = {
        "article_node_count": 156,
        "authority_actor": "Daniel Huang",
        "authority_role": "knowledge_owner",
        "batch_a_edges_sha256": (
            "42bbfbf5d83ad90116e87a6ffd9d1db31d36d4109701e3f811008600ea7d6f3c"
        ),
        "batch_a_inventory_sha256": EXPECTED["batch_a_inventory_sha256"],
        "batch_a_nodes_sha256": (
            "bf6ffad153dd0914d5a790c07e45f8da18b4f651763a6092f895ccdaad71ae2a"
        ),
        "batch_a_receipt_sha256": (
            "f90bbd4db39312b5d4959c660ec65bf579dfac50208d2e6070164ce37890530b"
        ),
        "batch_b_edges_sha256": (
            "4f7e9babd503ce09c390470dc418d156adec1139e0e80a5076fb12ee91cb21d5"
        ),
        "batch_b_inventory_sha256": EXPECTED["batch_b_inventory_sha256"],
        "batch_b_nodes_sha256": (
            "a2b9af1db321e1f71ff0ff67b44fd9ea2fb7044c66b41993db57ddb856cfad36"
        ),
        "batch_b_receipt_sha256": (
            "fcfba1a7933c98c612ac2ba98825ba672c974da51f84f8df498ecfde47dd1f60"
        ),
        "candidate_release_authorized": True,
        "combined_edges_sha256": EXPECTED["combined_edges_sha256"],
        "combined_nodes_sha256": EXPECTED["combined_nodes_sha256"],
        "edge_count": 8525,
        "embedding_authorized": True,
        "internal_candidate_deployment_authorized": True,
        "issue": "danielcanfly/knowledge-engine#1092",
        "master_inventory_sha256": EXPECTED["master_inventory_sha256"],
        "node_count": 4222,
        "origin_commit": UPSTREAM_COMMIT,
        "origin_repository": UPSTREAM_REPOSITORY,
        "pack_id": "daniel-blog-en-156",
        "production_pointer_authorized": False,
        "public_production_traffic_authorized": False,
        "qdrant_candidate_write_authorized": True,
        "r2_candidate_publish_authorized": True,
        "schema_version": PACK_SCHEMA,
        "section_node_count": 4041,
        "semantic_document_count": 4197,
        "series_node_count": 25,
        "source_count": 156,
        "source_write_authorized": True,
        "status": "approved_for_source_admission_and_candidate_deployment",
    }
    value["admission_sha256"] = hashlib.sha256(_canonical(value)).hexdigest()
    if value["admission_sha256"] != ADMISSION_SHA:
        raise IntegrityError("M25-LIVE-004 admission identity drift")
    return value


def materialize_pack(output: Path, token: str | None = None) -> dict[str, Any]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="m25-live-source-") as temporary:
        root = Path(temporary)
        a_root = root / "a"
        b_root = root / "b"
        client = GitHubClient(token)
        build_converged_batch(
            repository=UPSTREAM_REPOSITORY,
            commit=UPSTREAM_COMMIT,
            expected_count=156,
            batch_size=78,
            output_dir=a_root,
            client=client,
        )
        build_batch_b(
            repository=UPSTREAM_REPOSITORY,
            commit=UPSTREAM_COMMIT,
            expected_count=156,
            batch_size=78,
            output_dir=b_root,
            client=client,
        )
        master = _json(a_root / "master-inventory.json")
        batch_a = _json(a_root / "batch-a-inventory.json")
        batch_b = _json(a_root / "batch-b-inventory.json")
        receipt_a = _json(a_root / "batch-a-receipt.json")
        receipt_b = _json(b_root / "batch-b-receipt.json")
        exact = {
            "master_inventory_sha256": master["inventory_sha256"],
            "batch_a_inventory_sha256": batch_a["batch_inventory_sha256"],
            "batch_b_inventory_sha256": batch_b["batch_inventory_sha256"],
        }
        for field, expected in exact.items():
            if expected != EXPECTED[field]:
                raise IntegrityError(f"M25-LIVE-005 inventory drift: {field}")

        source_dir = output / "sources"
        source_dir.mkdir()
        names: set[str] = set()
        for source_root in (a_root / "sources", b_root / "sources"):
            for path in sorted(source_root.glob("*.md")):
                if path.name in names:
                    raise IntegrityError("M25-LIVE-006 duplicate source snapshot")
                names.add(path.name)
                shutil.copy2(path, source_dir / path.name)
        if len(names) != 156:
            raise IntegrityError("M25-LIVE-007 source snapshot population drift")

        nodes = _read_jsonl(a_root / "candidate-nodes.jsonl")
        nodes.extend(_read_jsonl(b_root / "candidate-nodes.jsonl"))
        edges = _read_jsonl(a_root / "candidate-edges.jsonl")
        edges.extend(_read_jsonl(b_root / "candidate-edges.jsonl"))
        nodes.sort(key=lambda item: item["node_id"])
        edges.sort(key=lambda item: item["edge_id"])
        if len({item["node_id"] for item in nodes}) != 4222:
            raise IntegrityError("M25-LIVE-008 node identity drift")
        if len({item["edge_id"] for item in edges}) != 8525:
            raise IntegrityError("M25-LIVE-009 edge identity drift")

        write_json(output / "master-inventory.json", master)
        write_json(output / "batch-a-inventory.json", batch_a)
        write_json(output / "batch-b-inventory.json", batch_b)
        write_json(output / "batch-a-receipt.json", receipt_a)
        write_json(output / "batch-b-receipt.json", receipt_b)
        _write_jsonl(output / "candidate-nodes.jsonl", nodes)
        _write_jsonl(output / "candidate-edges.jsonl", edges)
        if sha256_bytes((output / "candidate-nodes.jsonl").read_bytes()) != EXPECTED[
            "combined_nodes_sha256"
        ]:
            raise IntegrityError("M25-LIVE-010 combined nodes drift")
        if sha256_bytes((output / "candidate-edges.jsonl").read_bytes()) != EXPECTED[
            "combined_edges_sha256"
        ]:
            raise IntegrityError("M25-LIVE-011 combined edges drift")
        write_json(output / "admission.json", _admission())
    return validate_pack(output)


def _source_documents(pack: Mapping[str, Any]) -> dict[str, Any]:
    documents: dict[str, Any] = {}
    for source_id, article in pack["article_by_id"].items():
        raw = pack["source_bytes"][source_id]
        text = raw.decode("utf-8")
        toc = []
        for line in text.splitlines():
            stripped = line.lstrip()
            if stripped.startswith(("## ", "### ")):
                level = 3 if stripped.startswith("### ") else 2
                toc.append({"level": level, "title": stripped[level + 1 :].strip()})
        documents[source_id] = {
            "source_id": source_id,
            "coverage_status": "full_snapshot",
            "metadata_only_reason": None,
            "document": {"body": text, "title": article["title"]},
            "origin": {
                "repo": article["origin_repository"],
                "commit": article["origin_commit"],
                "path": article["origin_path"],
                "blob_sha": article["origin_blob_sha"],
            },
            "integrity": {
                "snapshot_sha256": article["content_sha256"],
                "browser_payload_sha256": sha256_bytes(raw),
                "truncated": False,
            },
            "registry": {
                "content_sha256": article["content_sha256"],
                "content_hash_scope": "immutable-full-markdown-bytes",
            },
            "toc": toc,
            "citations": [],
        }
    return {"documents": documents}


def _manifest_artifact(path: Path, kind: str, release_id: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "kind": kind,
        "key": f"releases/{release_id}/{path.relative_to(path.parents[1]).as_posix()}",
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "media_type": "application/json",
        "audiences": ["authenticated_internal"],
        "required": True,
    }


def build_candidate_release(
    pack_root: Path,
    output_root: Path,
    engine_sha: str,
) -> tuple[CompiledRelease, dict[str, Any]]:
    pack = validate_pack(pack_root)
    release_id = f"m25blog-{SOURCE_SHA[:12]}-{ADMISSION_SHA[:12]}"
    release_root = output_root / "releases" / release_id
    if release_root.exists():
        shutil.rmtree(release_root)
    artifact_root = release_root / "artifacts"
    bundle_root = release_root / "bundle" / "_documents" / "daniel-blog-en-156"
    shutil.copytree(pack_root, bundle_root)
    artifact_root.mkdir(parents=True)

    artifacts = build_pack_artifacts(pack, release_id)
    graph = {
        "schema_version": "knowledge-engine-document-graph/v1",
        "release_id": release_id,
        "nodes": artifacts["graph_nodes"],
        "edges": artifacts["graph_edges"],
    }
    graph_v2 = {
        "schema_version": "knowledge-engine-graph-v2/v1",
        "release": {
            "release_id": release_id,
            "engine_commit_sha": engine_sha,
            "source_commit_sha": SOURCE_SHA,
            "foundation_commit_sha": FOUNDATION_SHA,
        },
        "nodes": artifacts["graph_v2_nodes"],
        "edges": artifacts["graph_v2_edges"],
    }
    lexical = {
        "schema_version": "knowledge-engine-lexical-index/v2",
        "release_id": release_id,
        "documents": artifacts["lexical_documents"],
    }
    semantic = {
        "schema_version": "knowledge-engine-semantic-inputs/v1",
        "release_id": release_id,
        "model": CLOUDFLARE_MODEL,
        "vector_dimension": VECTOR_DIMENSION,
        "documents": artifacts["semantic_inputs"],
    }
    source_index = {
        "schema_version": "knowledge-source-document-index/v1",
        "release_id": release_id,
        "source_repository": SOURCE_REPOSITORY,
        "source_commit_sha": SOURCE_SHA,
        "source_count": 156,
        "sources": artifacts["source_index"],
    }
    provenance = {
        "schema_version": "knowledge-engine-document-provenance/v1",
        "release_id": release_id,
        "records": artifacts["provenance"],
    }
    source_documents = _source_documents(pack)
    payloads = {
        "graph.json": graph,
        "graph-v2.json": graph_v2,
        "lexical-index.json": lexical,
        "semantic-inputs.json": semantic,
        "source-index.json": source_index,
        "provenance.json": provenance,
        "source-documents.json": source_documents,
        "blog-pack-admission.json": pack["admission"],
    }
    for filename, value in payloads.items():
        _write(artifact_root / filename, value)

    artifact_specs = [
        ("graph", "graph.json"),
        ("graph_v2", "graph-v2.json"),
        ("lexical_index", "lexical-index.json"),
        ("semantic_inputs", "semantic-inputs.json"),
        ("document_source_index", "source-index.json"),
        ("provenance", "provenance.json"),
        ("source_documents", "source-documents.json"),
        ("document_pack_admission", "blog-pack-admission.json"),
    ]
    manifest = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": release_id,
        "status": "candidate",
        "authority": {
            "source_admitted": True,
            "candidate_release_authorized": True,
            "semantic_serving_authorized": True,
            "production_pointer_authorized": False,
            "public_production_traffic_authorized": False,
        },
        "identities": {
            "engine_commit_sha": engine_sha,
            "source_repository": SOURCE_REPOSITORY,
            "source_commit_sha": SOURCE_SHA,
            "foundation_commit_sha": FOUNDATION_SHA,
            "upstream_repository": UPSTREAM_REPOSITORY,
            "upstream_commit_sha": UPSTREAM_COMMIT,
            "admission_sha256": ADMISSION_SHA,
            "master_inventory_sha256": EXPECTED["master_inventory_sha256"],
            "combined_nodes_sha256": EXPECTED["combined_nodes_sha256"],
            "combined_edges_sha256": EXPECTED["combined_edges_sha256"],
        },
        "counts": {
            "document_sources": 156,
            "document_series": 25,
            "document_articles": 156,
            "document_sections": 4041,
            "document_graph_nodes": 4222,
            "document_graph_edges": 8525,
            "semantic_documents": 4197,
        },
        "retrieval": {
            "lexical": True,
            "semantic_candidate": True,
            "embedding_provider": "cloudflare-workers-ai",
            "embedding_model": CLOUDFLARE_MODEL,
            "vector_dimension": VECTOR_DIMENSION,
            "answer_model": ANSWER_MODEL,
        },
        "artifacts": [],
    }
    for kind, filename in artifact_specs:
        path = artifact_root / filename
        data = path.read_bytes()
        manifest["artifacts"].append(
            {
                "kind": kind,
                "key": f"releases/{release_id}/artifacts/{filename}",
                "sha256": sha256_bytes(data),
                "bytes": len(data),
                "media_type": "application/json",
                "audiences": ["authenticated_internal"],
                "required": True,
            }
        )
    manifest["artifacts"].sort(key=lambda item: item["kind"])
    _write(release_root / "manifest.json", manifest)
    compiled = CompiledRelease(
        release_id=release_id,
        release_root=release_root,
        manifest=manifest,
    )
    return compiled, {
        "pack": pack,
        "artifacts": artifacts,
        "semantic_inputs": semantic["documents"],
        "source_documents": source_documents,
    }


def _f32_sha(values: Sequence[Any]) -> str:
    if len(values) != VECTOR_DIMENSION:
        raise IntegrityError("M25-LIVE-012 vector dimension drift")
    floats = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise IntegrityError("M25-LIVE-013 non-numeric vector value")
        number = float(value)
        if not math.isfinite(number):
            raise IntegrityError("M25-LIVE-014 non-finite vector value")
        floats.append(number)
    return hashlib.sha256(struct.pack(f"<{VECTOR_DIMENSION}f", *floats)).hexdigest()


def _point_fingerprint(point: Mapping[str, Any]) -> str:
    vector_container = point.get("vector")
    if not isinstance(vector_container, Mapping):
        raise IntegrityError("M25-LIVE-015 named vector missing")
    vector = vector_container.get(QDRANT_VECTOR_NAME)
    payload = point.get("payload")
    if not isinstance(vector, list) or not isinstance(payload, Mapping):
        raise IntegrityError("M25-LIVE-016 point payload/vector malformed")
    return hashlib.sha256(
        _canonical(
            {
                "id": str(point.get("id")),
                "payload": dict(payload),
                "vector_sha256": _f32_sha(vector),
            }
        )
    ).hexdigest()


def _aggregate_fingerprint(points: Sequence[Mapping[str, Any]]) -> str:
    values = [
        {"id": str(point["id"]), "fingerprint": _point_fingerprint(point)}
        for point in points
    ]
    values.sort(key=lambda item: item["id"])
    return hashlib.sha256(_canonical(values)).hexdigest()


def _qdrant_request(
    client: httpx.Client,
    config: QdrantConfig,
    method: str,
    path: str,
    body: Any | None = None,
) -> dict[str, Any]:
    response = client.request(
        method,
        f"{config.base_url.rstrip('/')}{path}",
        headers={"api-key": config.api_key, "Accept": "application/json"},
        json=body,
    )
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict) or value.get("status") != "ok":
        raise IntegrityError(f"M25-LIVE-017 Qdrant non-ok response: {path}")
    return value


def delete_collection(config: QdrantConfig) -> None:
    with httpx.Client(timeout=config.timeout_seconds) as client:
        response = client.delete(
            f"{config.base_url.rstrip('/')}/collections/"
            f"{urllib.parse.quote(config.collection_name, safe='')}",
            headers={"api-key": config.api_key},
        )
        if response.status_code not in {200, 404}:
            response.raise_for_status()


def index_candidate(
    semantic_rows: Sequence[Mapping[str, Any]],
    release_id: str,
    channel: str,
) -> dict[str, Any]:
    cloudflare = CloudflareConfig(
        account_id=os.environ["CLOUDFLARE_ACCOUNT_ID"],
        api_token=os.environ["CLOUDFLARE_API_TOKEN"],
    )
    collection = f"m25_blog_{release_id.replace('-', '_').lower()}"
    qdrant = QdrantConfig(
        base_url=os.environ["QDRANT_URL"],
        api_key=os.environ["QDRANT_API_KEY"],
        collection_name=collection,
    )
    sections = [
        SectionInput(
            section_id=str(row["section_id"]),
            text=str(row["text"]),
            payload=dict(row["payload"]),
        )
        for row in semantic_rows
    ]
    if len(sections) != 4197:
        raise IntegrityError("M25-LIVE-018 semantic population drift")
    vectors = embed_sections(sections, cloudflare)
    points = build_qdrant_points(sections, vectors)
    for point in points:
        point["payload"].update(
            {
                "release_id": release_id,
                "candidate_channel": channel,
                "canonical_knowledge": False,
                "candidate_release_eligible": True,
                "production_authority": False,
                "source_commit_sha": SOURCE_SHA,
                "admission_sha256": ADMISSION_SHA,
            }
        )
    expected_by_id = {str(point["id"]): point for point in points}
    if len(expected_by_id) != 4197:
        raise IntegrityError("M25-LIVE-019 deterministic point identity drift")
    expected_fingerprint = _aggregate_fingerprint(points)
    escaped = urllib.parse.quote(collection, safe="")
    with httpx.Client(timeout=180.0) as client:
        create = client.put(
            f"{qdrant.base_url.rstrip('/')}/collections/{escaped}",
            headers={"api-key": qdrant.api_key},
            json={
                "vectors": {
                    QDRANT_VECTOR_NAME: {
                        "size": VECTOR_DIMENSION,
                        "distance": QDRANT_DISTANCE,
                    }
                }
            },
        )
        if create.status_code not in {200, 201}:
            create.raise_for_status()
        snapshot = _qdrant_request(client, qdrant, "GET", f"/collections/{escaped}")
        before = snapshot["result"]
        if before.get("points_count") != 0:
            raise IntegrityError("M25-LIVE-020 candidate collection is not empty")
        for start in range(0, len(points), 64):
            result = _qdrant_request(
                client,
                qdrant,
                "PUT",
                f"/collections/{escaped}/points?wait=true&ordering=strong",
                {"points": points[start : start + 64]},
            )
            status = result.get("result", {}).get("status")
            if status not in {"completed", "acknowledged"}:
                raise IntegrityError("M25-LIVE-021 Qdrant upsert not completed")
        returned: list[dict[str, Any]] = []
        ids = sorted(expected_by_id)
        for start in range(0, len(ids), 32):
            result = _qdrant_request(
                client,
                qdrant,
                "POST",
                f"/collections/{escaped}/points?consistency=all",
                {
                    "ids": ids[start : start + 32],
                    "with_payload": True,
                    "with_vector": [QDRANT_VECTOR_NAME],
                },
            )
            rows = result.get("result")
            if not isinstance(rows, list):
                raise IntegrityError("M25-LIVE-022 Qdrant readback row drift")
            returned.extend(rows)
        actual_by_id = {str(point.get("id")): point for point in returned}
        if set(actual_by_id) != set(expected_by_id):
            raise IntegrityError("M25-LIVE-023 Qdrant readback ID set mismatch")
        mismatches = [
            point_id
            for point_id in ids
            if _point_fingerprint(actual_by_id[point_id])
            != _point_fingerprint(expected_by_id[point_id])
        ]
        if mismatches:
            raise IntegrityError(
                f"M25-LIVE-024 Qdrant readback mismatch: {mismatches[:10]}"
            )
        actual_fingerprint = _aggregate_fingerprint(returned)
        if actual_fingerprint != expected_fingerprint:
            raise IntegrityError("M25-LIVE-025 aggregate point fingerprint mismatch")
        after = _qdrant_request(client, qdrant, "GET", f"/collections/{escaped}")[
            "result"
        ]
        if after.get("points_count") != 4197 or after.get("status") != "green":
            raise IntegrityError("M25-LIVE-026 final Qdrant collection state drift")
    return {
        "collection": collection,
        "point_count": 4197,
        "point_ids_sha256": hashlib.sha256(_canonical(ids)).hexdigest(),
        "aggregate_point_fingerprint_sha256": actual_fingerprint,
        "embedding_vectors_sha256": hashlib.sha256(_canonical(vectors)).hexdigest(),
        "embedding_model": CLOUDFLARE_MODEL,
        "vector_dimension": VECTOR_DIMENSION,
        "readback": "all_ids_payloads_vectors_match",
    }


def _site_payloads(
    release_id: str,
    manifest_sha: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    pack = context["pack"]
    graph_nodes = context["artifacts"]["graph_v2_nodes"]
    graph_edges = context["artifacts"]["graph_v2_edges"]
    documents = context["source_documents"]["documents"]
    viewers = []
    coverage = []
    cards = []
    for source_id, article in sorted(pack["article_by_id"].items()):
        doc = documents[source_id]
        card = {
            "source_card_id": f"card_{source_id}",
            "source_id": source_id,
            "title": article["title"],
            "uri": article["canonical_url"],
            "display_host": "danielcanfly.com",
            "publisher": "Daniel Huang",
            "source_kind": "markdown",
            "snapshot_available": True,
            "content_bytes": article["content_bytes"],
            "coverage_status": "full_snapshot",
            "document_path": f"data/sources/{source_id}.json",
            "concept_ids": [article["series_id"]],
        }
        cards.append(card)
        viewers.append(
            {
                "viewer_id": f"viewer_{source_id}",
                "release_id": release_id,
                "source_card": card,
                "summary": {
                    "coverage_status": "full_snapshot",
                    "content_bytes": article["content_bytes"],
                    "line_count": len(
                        pack["source_bytes"][source_id].decode("utf-8").splitlines()
                    ),
                    "citation_count": 0,
                },
                "document": doc,
                "citations": [],
            }
        )
        coverage.append(
            {
                "source_id": source_id,
                "title": article["title"],
                "canonical_uri": article["canonical_url"],
                "kind": "markdown",
                "coverage_status": "full_snapshot",
                "snapshot_available": True,
                "content_bytes": article["content_bytes"],
                "line_count": len(
                    pack["source_bytes"][source_id].decode("utf-8").splitlines()
                ),
                "origin_repo": article["origin_repository"],
                "origin_commit": article["origin_commit"],
                "origin_path": article["origin_path"],
                "origin_blob_sha": article["origin_blob_sha"],
                "registry_content_sha256": article["content_sha256"],
                "document_path": f"data/sources/{source_id}.json",
                "related_concepts": [article["series_id"]],
            }
        )
    search_results = []
    for rank, item in enumerate(context["artifacts"]["lexical_documents"], start=1):
        search_results.append(
            {
                **item,
                "rank": rank,
                "score": 1.0,
                "citation_ordinals": [],
                "source_card_ids": [f"card_{item['source_id']}"],
            }
        )
    graph = {
        "release_id": release_id,
        "authority": {
            "graph_authority": "candidate_read_only",
            "retrieval_authority": "candidate_semantic",
            "production_retrieval": "lexical_unchanged",
            "semantic_serving_enabled": True,
            "hybrid_retrieval_enabled": False,
            "source_mutation_authorized": False,
        },
        "available_actions": ["select_node", "open_source_viewer", "semantic_query"],
        "focus_neighbor_ids": [],
        "focus_truncated": False,
        "nodes": [
            {
                "concept_id": node["concept_id"],
                "title": node["title"],
                "description": node.get("description", "Daniel blog structural node"),
                "type": node["type"],
                "audience": "public",
                "tags": node.get("tags", []),
                "selected": False,
                "focus_neighbor": False,
            }
            for node in graph_nodes
        ],
        "edges": [
            {
                "edge_id": edge["edge_id"],
                "source": edge["source"],
                "target": edge["target"],
                "relation_type": edge["relation_type"],
                "directed": True,
                "confidence": 1.0,
                "generated_inverse": False,
                "focus_edge": False,
            }
            for edge in graph_edges
        ],
    }
    release = {
        "release_id": release_id,
        "manifest_sha256": manifest_sha,
        "source_commit_sha": SOURCE_SHA,
        "counts": {
            "concepts": 25,
            "graph_nodes": 4222,
            "graph_edges": 8525,
            "source_snapshots": 156,
            "semantic_documents": 4197,
        },
        "production_retrieval": "candidate_semantic",
        "semantic_serving_enabled": True,
        "hybrid_retrieval_enabled": False,
        "production_pointer_mutated": False,
    }
    concept = {
        "release_id": release_id,
        "concept_id": "series_harness-theory",
        "title": "Harness Theory",
        "description": "Candidate document-series view backed by admitted Sources.",
        "sections": [],
        "relationships": [],
        "source_viewers": [],
    }
    return {
        "release-viewer.json": release,
        "concept-wiki-harness.json": concept,
        "search-harness.json": {
            "release_id": release_id,
            "results": search_results,
            "source_cards": cards,
        },
        "graph-navigation.json": graph,
        "source-viewers.json": {
            "release_id": release_id,
            "source_viewers": viewers,
            "coverage_matrix": coverage,
        },
        "source-index.json": {
            "release_id": release_id,
            "source_repository": SOURCE_REPOSITORY,
            "source_commit_sha": SOURCE_SHA,
            "source_count": 156,
            "coverage_matrix": coverage,
        },
        "source-documents.json": {
            "release_id": release_id,
            "documents": documents,
        },
        "query-answer-acceptance.json": {
            "release_id": release_id,
            "status": "candidate_semantic_runtime_enabled",
            "endpoint": "/api/m25/query",
        },
        "obsidian-export-manifest.json": {
            "release_id": release_id,
            "status": "not_in_candidate_scope",
        },
        "m24-14-6-final-acceptance.json": {
            "release_id": release_id,
            "status": "m25_candidate_pending_authenticated_acceptance",
        },
    }


def build_internal_site(
    template: Path,
    output: Path,
    compiled: CompiledRelease,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(template, output)
    manifest_sha = sha256_bytes((compiled.release_root / "manifest.json").read_bytes())
    data_root = output / "data"
    if data_root.exists():
        shutil.rmtree(data_root)
    data_root.mkdir()
    payloads = _site_payloads(compiled.release_id, manifest_sha, context)
    for filename, value in payloads.items():
        _write(data_root / filename, value)
    sources_root = data_root / "sources"
    sources_root.mkdir()
    for source_id, document in context["source_documents"]["documents"].items():
        _write(sources_root / f"{source_id}.json", document)
    app_path = output / "app.js"
    app = app_path.read_text(encoding="utf-8")
    app = app.replace(
        'const EXPECTED_RELEASE = "20260720T160000Z-46137c97263e";',
        f'const EXPECTED_RELEASE = "{compiled.release_id}";',
    )
    app = app.replace(
        'const EXPECTED_MANIFEST = '
        '"ef5ee828069731e3e7106e1b12fb82e3a578c377930568410bc78421d1600877";',
        f'const EXPECTED_MANIFEST = "{manifest_sha}";',
    )
    app = app.replace(
        'artifacts.release.production_retrieval !== "lexical"',
        'artifacts.release.production_retrieval !== "candidate_semantic"',
    )
    old_guard = """  if (
    artifacts.release.semantic_serving_enabled ||
    artifacts.release.hybrid_retrieval_enabled
  ) {
    throw new Error(\"semantic or hybrid serving is not authorized\");
  }
"""
    new_guard = """  if (
    !artifacts.release.semantic_serving_enabled ||
    artifacts.release.hybrid_retrieval_enabled
  ) {
    throw new Error(\"candidate semantic serving boundary mismatch\");
  }
"""
    if old_guard not in app:
        raise IntegrityError("M25-LIVE-027 internal app semantic guard drift")
    app = app.replace(old_guard, new_guard)
    app = app.replace("Lexical Search", "Candidate Search")
    app = app.replace("Lexical query", "Candidate query")
    app = app.replace("Release-pinned lexical results", "Release-pinned document results")
    app = app.replace(
        '<button type="submit">Search</button>',
        '<button type="submit">Filter</button>'
        '<a class="inline-action" href="/api/m25/query?q=harness" '
        'target="_blank" rel="noreferrer">Ask AI runtime</a>',
        1,
    )
    app_path.write_text(app, encoding="utf-8")
    return {
        "site_dir": output.as_posix(),
        "release_id": compiled.release_id,
        "manifest_sha256": manifest_sha,
        "source_count": 156,
        "graph_node_count": 4222,
        "graph_edge_count": 8525,
    }


def prepare(
    *,
    work_dir: Path,
    engine_sha: str,
    channel: str,
    live: bool,
) -> dict[str, Any]:
    if not channel.startswith("candidate-blog-"):
        raise IntegrityError("M25-LIVE-028 candidate channel prefix required")
    work_dir.mkdir(parents=True, exist_ok=True)
    pack_root = work_dir / "source-pack"
    materialize_pack(pack_root, os.environ.get("GITHUB_TOKEN"))
    compiled, context = build_candidate_release(pack_root, work_dir, engine_sha)
    qdrant_receipt = None
    publication = None
    settings = Settings.from_env()
    store = create_object_store(settings)
    try:
        if live:
            qdrant_receipt = index_candidate(
                context["semantic_inputs"],
                compiled.release_id,
                channel,
            )
            publication = publish_release(
                store=store,
                compiled=compiled,
                channel=channel,
                promoted_at=datetime.now(UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            )
        site = build_internal_site(
            Path("pilot/m24/internal-product-deployment/site"),
            work_dir / "internal-site",
            compiled,
            context,
        )
    except Exception:
        if qdrant_receipt is not None:
            qdrant = QdrantConfig(
                base_url=os.environ["QDRANT_URL"],
                api_key=os.environ["QDRANT_API_KEY"],
                collection_name=qdrant_receipt["collection"],
            )
            delete_collection(qdrant)
        raise
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "candidate_prepared_live" if live else "candidate_preview_ready",
        "engine_sha": engine_sha,
        "source_repository": SOURCE_REPOSITORY,
        "source_sha": SOURCE_SHA,
        "release_id": compiled.release_id,
        "manifest_sha256": sha256_bytes(
            (compiled.release_root / "manifest.json").read_bytes()
        ),
        "channel": channel,
        "qdrant": qdrant_receipt,
        "r2": (
            {
                "published": True,
                "manifest_key": publication.manifest_key,
                "manifest_sha256": publication.manifest_sha256,
            }
            if publication is not None
            else {"published": False}
        ),
        "site": site,
        "runtime": {
            "worker_name": RUNTIME_NAME,
            "route": RUNTIME_ROUTE,
            "answer_model": ANSWER_MODEL,
        },
        "counts": COUNTS,
        "production_pointer_mutated": False,
        "public_production_traffic_mutated": False,
    }
    receipt["receipt_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    _write(work_dir / "m25-10-live-candidate-receipt.json", receipt)
    return receipt


def rollback(receipt_path: Path) -> dict[str, Any]:
    receipt = _json(receipt_path)
    qdrant_data = receipt.get("qdrant")
    if isinstance(qdrant_data, dict) and qdrant_data.get("collection"):
        delete_collection(
            QdrantConfig(
                base_url=os.environ["QDRANT_URL"],
                api_key=os.environ["QDRANT_API_KEY"],
                collection_name=qdrant_data["collection"],
            )
        )
    settings = Settings.from_env()
    store = create_object_store(settings)
    store.delete(f"channels/{receipt['channel']}.json")
    result = {
        "status": "candidate_external_state_rolled_back",
        "release_id": receipt["release_id"],
        "channel": receipt["channel"],
        "qdrant_collection_deleted": bool(qdrant_data),
        "candidate_pointer_deleted": True,
        "production_pointer_mutated": False,
    }
    result["receipt_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--work-dir", type=Path, required=True)
    prepare_parser.add_argument("--engine-sha", required=True)
    prepare_parser.add_argument("--channel", required=True)
    prepare_parser.add_argument("--live", action="store_true")
    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        value = prepare(
            work_dir=args.work_dir,
            engine_sha=args.engine_sha,
            channel=args.channel,
            live=args.live,
        )
    else:
        value = rollback(args.receipt)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
