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


def build_semantic_arch_repair_candidate_bundle(
    pack: Mapping[str, Any],
    *,
    engine_sha: str,
) -> ProductionAnswerBundle:
    release_id = live_candidate._candidate_release_id(engine_sha)
    normalized_pack = candidate_release.normalize_pack_series_precedes(pack)
    artifacts = candidate_release.build_pack_artifacts(
        normalized_pack,
        release_id,
        expected_semantic_documents=SEMANTIC_ARCH_REPAIR_COUNTS["semantic_documents"],
    )
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
                "source_commit_sha": live_candidate.SOURCE_SHA,
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
            "source_repository": live_candidate.SOURCE_REPOSITORY,
            "source_commit_sha": live_candidate.SOURCE_SHA,
            "source_count": SEMANTIC_ARCH_REPAIR_COUNTS["sources"],
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
            "source_repository": live_candidate.SOURCE_REPOSITORY,
            "source_commit_sha": live_candidate.SOURCE_SHA,
            "foundation_commit_sha": live_candidate.FOUNDATION_SHA,
            "admission_sha256": live_candidate.ADMISSION_SHA,
            "repair_kind": SEMANTIC_ARCH_REPAIR_KIND,
            "repaired_source_graph_canonical_sha256": canonical_sha256(source_graph),
        },
        "counts": {
            "document_sources": SEMANTIC_ARCH_REPAIR_COUNTS["sources"],
            "document_series": 25,
            "document_articles": 156,
            "document_sections": SEMANTIC_ARCH_REPAIR_COUNTS["sections"],
            "document_graph_nodes": SEMANTIC_ARCH_REPAIR_COUNTS["graph_nodes"],
            "document_graph_edges": SEMANTIC_ARCH_REPAIR_COUNTS["graph_edges"],
            "lexical_documents": SEMANTIC_ARCH_REPAIR_COUNTS["lexical_documents"],
            "semantic_documents": SEMANTIC_ARCH_REPAIR_COUNTS["semantic_documents"],
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
    if not isinstance(identities, Mapping) or not isinstance(authority, Mapping):
        return "PA7_ARCH_REPAIR_CANDIDATE_MANIFEST_IDENTITY_MISMATCH"
    if identities.get("repair_kind") != SEMANTIC_ARCH_REPAIR_KIND:
        return "PA7_ARCH_REPAIR_CANDIDATE_REPAIR_KIND_MISMATCH"
    engine_sha = str(identities.get("engine_commit_sha", ""))
    try:
        expected_release_id = live_candidate._candidate_release_id(engine_sha)
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
    populations = {
        "graph_nodes": len(bundle.graph_v2.get("nodes", [])),
        "graph_edges": len(bundle.graph_v2.get("edges", [])),
        "lexical_documents": len(bundle.lexical_index.get("documents", [])),
        "semantic_documents": len(semantic_inputs.get("documents", [])),
    }
    expected = {
        key: SEMANTIC_ARCH_REPAIR_COUNTS[key]
        for key in populations
    }
    if populations != expected:
        return "PA7_ARCH_REPAIR_CANDIDATE_POPULATION_MISMATCH"
    release = bundle.graph_v2.get("release")
    if not isinstance(release, Mapping):
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    if release.get("release_id") != bundle.release_id:
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    if release.get("engine_commit_sha") != engine_sha:
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    if bundle.graph.get("release_id") != bundle.release_id:
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    if bundle.lexical_index.get("release_id") != bundle.release_id:
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    if semantic_inputs.get("release_id") != bundle.release_id:
        return "PA7_ARCH_REPAIR_CANDIDATE_SCHEMA_MISMATCH"
    return None
