from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from . import m25_blog_candidate_release as candidate_release
from . import m25_blog_live_candidate as live_candidate
from .errors import IntegrityError
from .m26_production_answer_bundle import ProductionAnswerBundle
from .m26_verified_answer_citation_gate import canonical_sha256

SEMANTIC_ARCH_REPAIR_KIND = "aqv2-semantic-architecture-repair-v1"
SEMANTIC_ARCH_REPAIR_PARENT_SHA = "897004afad0215313ef3ba32516dc0ce291015d8"
SEMANTIC_ARCH_REPAIR_COUNTS = {
    "graph_nodes": 4363,
    "graph_edges": 8807,
    "lexical_documents": 4338,
    "semantic_documents": 4338,
    "sections": 4182,
    "sources": 156,
}

_ARTIFACT_FILENAMES = {
    "graph": "graph.json",
    "graph_v2": "graph-v2.json",
    "lexical_index": "lexical-index.json",
    "semantic_inputs": "semantic-inputs.json",
    "document_source_index": "source-index.json",
    "provenance": "provenance.json",
    "source_documents": "source-documents.json",
}


def _pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _source_bound_candidate_release_id(
    *,
    engine_sha: str,
    source_commit_sha: str,
    admission_sha256: str,
) -> str:
    return (
        f"m25blog-{source_commit_sha[:12]}-{admission_sha256[:12]}-"
        f"{live_candidate._engine_sha_suffix(engine_sha)}"
    )


def _pack_population(pack: Mapping[str, Any]) -> dict[str, int]:
    nodes = list(pack["nodes"])
    edges = list(pack["edges"])
    node_types = {
        kind: sum(1 for node in nodes if node.get("node_type") == kind)
        for kind in ("Series", "Article", "Section")
    }
    source_count = len(pack["article_by_id"])
    if node_types["Article"] != source_count:
        raise IntegrityError("PA7_ARCH_REPAIR_CANDIDATE_ARTICLE_POPULATION_MISMATCH")
    return {
        "sources": source_count,
        "series": node_types["Series"],
        "articles": node_types["Article"],
        "sections": node_types["Section"],
        "graph_nodes": len(nodes),
        "graph_edges": len(edges),
        "semantic_documents": node_types["Article"] + node_types["Section"],
    }


def build_semantic_arch_repair_candidate_bundle(
    pack: Mapping[str, Any],
    *,
    engine_sha: str,
    source_repository: str | None = None,
    source_commit_sha: str | None = None,
    admission_sha256: str | None = None,
    pack_id: str | None = None,
) -> ProductionAnswerBundle:
    explicit_identity = any(
        value is not None
        for value in (source_repository, source_commit_sha, admission_sha256)
    )
    if explicit_identity and not all(
        value is not None
        for value in (source_repository, source_commit_sha, admission_sha256)
    ):
        raise IntegrityError("PA7_ARCH_REPAIR_CANDIDATE_SOURCE_IDENTITY_INCOMPLETE")
    if not explicit_identity:
        source_repository = live_candidate.SOURCE_REPOSITORY
        source_commit_sha = live_candidate.SOURCE_SHA
        admission_sha256 = live_candidate.ADMISSION_SHA
    else:
        repositories = {
            str(article.get("origin_repository", ""))
            for article in pack["article_by_id"].values()
        }
        commits = {
            str(article.get("origin_commit", ""))
            for article in pack["article_by_id"].values()
        }
        if repositories != {str(source_repository)} or commits != {str(source_commit_sha)}:
            raise IntegrityError("PA7_ARCH_REPAIR_CANDIDATE_SOURCE_IDENTITY_MISMATCH")
    assert source_repository is not None
    assert source_commit_sha is not None
    assert admission_sha256 is not None
    normalized_pack = candidate_release.normalize_pack_series_precedes(pack)
    counts = _pack_population(normalized_pack)
    if pack_id is None:
        if not explicit_identity:
            pack_id = "daniel-blog-en-156"
        else:
            pack_id = f"daniel-blog-en-{counts['sources']}-{source_commit_sha[:8]}"
    release_id = _source_bound_candidate_release_id(
        engine_sha=engine_sha,
        source_commit_sha=source_commit_sha,
        admission_sha256=admission_sha256,
    )
    artifacts = candidate_release.build_pack_artifacts(
        normalized_pack,
        release_id,
        expected_semantic_documents=counts["semantic_documents"],
        pack_id=pack_id,
    )
    counts["lexical_documents"] = len(artifacts["lexical_documents"])
    counts["semantic_documents"] = len(artifacts["semantic_inputs"])
    payloads: dict[str, dict[str, Any]] = {
        "graph": {
            "schema_version": "knowledge-engine-document-graph/v1",
            "release_id": release_id,
            "nodes": artifacts["graph_nodes"],
            "edges": artifacts["graph_edges"],
        },
        "graph_v2": {
            "schema_version": "knowledge-engine-graph-v2/v1",
            "release": {
                "release_id": release_id,
                "engine_commit_sha": engine_sha,
                "source_commit_sha": source_commit_sha,
                "foundation_commit_sha": live_candidate.FOUNDATION_SHA,
            },
            "nodes": artifacts["graph_v2_nodes"],
            "edges": artifacts["graph_v2_edges"],
        },
        "lexical_index": {
            "schema_version": "knowledge-engine-lexical-index/v2",
            "release_id": release_id,
            "documents": artifacts["lexical_documents"],
        },
        "semantic_inputs": {
            "schema_version": "knowledge-engine-semantic-inputs/v1",
            "release_id": release_id,
            "model": live_candidate.CLOUDFLARE_MODEL,
            "vector_dimension": live_candidate.VECTOR_DIMENSION,
            "documents": artifacts["semantic_inputs"],
        },
        "document_source_index": {
            "schema_version": "knowledge-source-document-index/v1",
            "release_id": release_id,
            "source_repository": source_repository,
            "source_commit_sha": source_commit_sha,
            "source_count": counts["sources"],
            "sources": artifacts["source_index"],
        },
        "provenance": {
            "schema_version": "knowledge-source-document-provenance-collection/v1",
            "release_id": release_id,
            "records": artifacts["provenance"],
        },
        "source_documents": live_candidate._source_documents(normalized_pack),
    }
    payload_bytes = {
        kind: _pretty_bytes(value)
        for kind, value in payloads.items()
    }
    artifact_sha256 = {
        kind: hashlib.sha256(data).hexdigest()
        for kind, data in payload_bytes.items()
    }
    source_graph = {
        "nodes": normalized_pack["nodes"],
        "edges": normalized_pack["edges"],
    }
    manifest: dict[str, Any] = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": release_id,
        "status": "candidate",
        "authority": {
            "source_admitted": True,
            "candidate_release_authorized": True,
            "semantic_serving_authorized": True,
            "production_pointer_authorized": False,
            "public_production_traffic_authorized": False,
            "qualification_only": True,
        },
        "identities": {
            "engine_commit_sha": engine_sha,
            "repair_parent_sha": SEMANTIC_ARCH_REPAIR_PARENT_SHA,
            "source_repository": source_repository,
            "source_commit_sha": source_commit_sha,
            "foundation_commit_sha": live_candidate.FOUNDATION_SHA,
            "admission_sha256": admission_sha256,
            "repair_kind": SEMANTIC_ARCH_REPAIR_KIND,
            "repaired_source_graph_canonical_sha256": canonical_sha256(source_graph),
        },
        "counts": {
            "document_sources": counts["sources"],
            "document_series": counts["series"],
            "document_articles": counts["articles"],
            "document_sections": counts["sections"],
            "document_graph_nodes": counts["graph_nodes"],
            "document_graph_edges": counts["graph_edges"],
            "lexical_documents": counts["lexical_documents"],
            "semantic_documents": counts["semantic_documents"],
        },
        "retrieval": {
            "lexical": True,
            "semantic_candidate": True,
            "embedding_provider": "cloudflare-workers-ai",
            "embedding_model": live_candidate.CLOUDFLARE_MODEL,
            "vector_dimension": live_candidate.VECTOR_DIMENSION,
        },
        "artifacts": [],
    }
    for kind in sorted(_ARTIFACT_FILENAMES):
        data = payload_bytes[kind]
        manifest["artifacts"].append(
            {
                "kind": kind,
                "key": f"releases/{release_id}/artifacts/{_ARTIFACT_FILENAMES[kind]}",
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "media_type": "application/json",
                "audiences": ["authenticated_internal"],
                "required": True,
            }
        )
    artifact_keys = {
        str(entry["kind"]): str(entry["key"])
        for entry in manifest["artifacts"]
    }
    bundle = ProductionAnswerBundle(
        manifest=manifest,
        graph=payloads["graph"],
        graph_v2=payloads["graph_v2"],
        lexical_index=payloads["lexical_index"],
        provenance=payloads["provenance"],
        manifest_sha256=hashlib.sha256(_pretty_bytes(manifest)).hexdigest(),
        artifact_sha256=artifact_sha256,
        artifact_keys=artifact_keys,
        loaded_at="qualification",
        source_documents=payloads["source_documents"],
        document_source_index=payloads["document_source_index"],
        semantic_inputs=payloads["semantic_inputs"],
    )
    mismatch = semantic_arch_repair_candidate_mismatch(bundle)
    if mismatch is not None:
        raise IntegrityError(mismatch)
    return bundle


def semantic_arch_repair_candidate_mismatch(
    bundle: ProductionAnswerBundle,
) -> str | None:
    identities = bundle.manifest.get("identities")
    authority = bundle.manifest.get("authority")
    counts = bundle.manifest.get("counts")
    if (
        not isinstance(identities, Mapping)
        or not isinstance(authority, Mapping)
        or not isinstance(counts, Mapping)
    ):
        return "PA7_ARCH_REPAIR_CANDIDATE_MANIFEST_IDENTITY_MISMATCH"
    if identities.get("repair_kind") != SEMANTIC_ARCH_REPAIR_KIND:
        return "PA7_ARCH_REPAIR_CANDIDATE_REPAIR_KIND_MISMATCH"
    engine_sha = str(identities.get("engine_commit_sha", ""))
    source_commit_sha = str(identities.get("source_commit_sha", ""))
    admission_sha256 = str(identities.get("admission_sha256", ""))
    try:
        expected_release_id = _source_bound_candidate_release_id(
            engine_sha=engine_sha,
            source_commit_sha=source_commit_sha,
            admission_sha256=admission_sha256,
        )
    except IntegrityError:
        return "PA7_ARCH_REPAIR_CANDIDATE_ENGINE_SHA_MISMATCH"
    if bundle.release_id != expected_release_id:
        return "PA7_ARCH_REPAIR_CANDIDATE_RELEASE_MISMATCH"
    if identities.get("repair_parent_sha") != SEMANTIC_ARCH_REPAIR_PARENT_SHA:
        return "PA7_ARCH_REPAIR_CANDIDATE_PARENT_MISMATCH"
    if authority.get("qualification_only") is not True:
        return "PA7_ARCH_REPAIR_CANDIDATE_AUTHORITY_MISMATCH"
    if authority.get("production_pointer_authorized") is not False:
        return "PA7_ARCH_REPAIR_CANDIDATE_AUTHORITY_MISMATCH"
    if authority.get("public_production_traffic_authorized") is not False:
        return "PA7_ARCH_REPAIR_CANDIDATE_AUTHORITY_MISMATCH"

    semantic_inputs = bundle.semantic_inputs or {}
    graph_nodes = list(bundle.graph_v2.get("nodes", []))
    actual = {
        "document_sources": len((bundle.document_source_index or {}).get("sources", [])),
        "document_series": sum(1 for node in graph_nodes if node.get("type") == "Series"),
        "document_articles": sum(1 for node in graph_nodes if node.get("type") == "Article"),
        "document_sections": sum(1 for node in graph_nodes if node.get("type") == "Section"),
        "document_graph_nodes": len(graph_nodes),
        "document_graph_edges": len(bundle.graph_v2.get("edges", [])),
        "lexical_documents": len(bundle.lexical_index.get("documents", [])),
        "semantic_documents": len(semantic_inputs.get("documents", [])),
    }
    try:
        expected = {key: int(counts[key]) for key in actual}
    except (KeyError, TypeError, ValueError):
        return "PA7_ARCH_REPAIR_CANDIDATE_POPULATION_MISMATCH"
    if actual != expected:
        return "PA7_ARCH_REPAIR_CANDIDATE_POPULATION_MISMATCH"
    source_index = bundle.document_source_index or {}
    if int(source_index.get("source_count", -1)) != actual["document_sources"]:
        return "PA7_ARCH_REPAIR_CANDIDATE_POPULATION_MISMATCH"
    source_documents = bundle.source_documents or {}
    documents = source_documents.get("documents", {})
    if not isinstance(documents, Mapping) or len(documents) != actual["document_sources"]:
        return "PA7_ARCH_REPAIR_CANDIDATE_POPULATION_MISMATCH"

    release = bundle.graph_v2.get("release")
    if not isinstance(release, Mapping):
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    if release.get("release_id") != bundle.release_id:
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    if release.get("engine_commit_sha") != engine_sha:
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    if release.get("source_commit_sha") != source_commit_sha:
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    if bundle.graph.get("release_id") != bundle.release_id:
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    if bundle.lexical_index.get("release_id") != bundle.release_id:
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    if semantic_inputs.get("release_id") != bundle.release_id:
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    return None
