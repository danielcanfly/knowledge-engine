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

SEMANTIC_R3_ENGINE_SHA = "45fd829578eb7976e2303827225b8628ea26891a"
SEMANTIC_R3_PARENT_SHA = "757fa1f30b8d899ab7ef088d630ba14b1c5a9cda"
SEMANTIC_R3_RELEASE_ID = live_candidate._candidate_release_id(SEMANTIC_R3_ENGINE_SHA)
SEMANTIC_R3_MANIFEST_SHA256 = (
    "d0c34c5031772b87397c15a5d9b6d4ec9e928c47808ea7ccf1caae4767068652"
)
SEMANTIC_R3_SOURCE_GRAPH_CANONICAL_SHA256 = (
    "6f2effc0716aedf7962c53f263395d9dfae5979a6b5615d71e6f21c9c694230e"
)
SEMANTIC_R3_COUNTS = {
    "graph_nodes": 4363,
    "graph_edges": 8807,
    "lexical_documents": 4338,
    "semantic_documents": 4338,
    "sections": 4182,
    "sources": 156,
}
SEMANTIC_R3_ARTIFACT_SHA256 = {
    "document_source_index": "65bd041c1f4f239ba339878e14b24b3f1e8d664f8b1a3068fb10044ee4602581",
    "graph": "dbd73a8b72961d1357ba5b7edc762c3790677b69dd3c659fac09e56b981d0abe",
    "graph_v2": "16c1c2ca7d467095f7702c47e97eb6cd8786dd861523354cff7c3b5f0242d493",
    "lexical_index": "7f6a8ec1422f2f90190f2de236b3bd40288b7aaf598a875cff1b9aecfc7165c8",
    "provenance": "6cf4c8731902831291bc9cb3d9b354ba59bb5e49abcae662c99c3c443d3db114",
    "semantic_inputs": "14be9f0e2b5b76bdce7d9940c11f88909bc53fd8b6e8f58e1c1990068acb0c6c",
    "source_documents": "e3b5e8a4473a5f9e3a68f375b5eea5d054c4576b604e126ed1b99556713c7743",
}
SEMANTIC_R3_CANONICAL_SHA256 = {
    "document_source_index": "9cc9b0929785cdc89cb75b07bb1a1ada931e962d6d5906fac96f74afc62d6b6e",
    "graph": "0d48400e6d18a13e418a8ea23761d276fd6be7acb0e6f493216607c01c0c4bcd",
    "graph_v2": "4c45ebbaf64296b1a0597427c8773d8f741c625093329c19c4f044f0c8a48b13",
    "lexical_index": "9059f1571dbb9a3c3da784661e3fefe4fdda3275e565ebe8a697fe28f030656b",
    "provenance": "2cf18fea1110ca4cf7c4eb0b0e28d8ac23de8a5ac765b74cda04601c674a02ed",
    "semantic_inputs": "7cb80bd8c0195699b1abe156f6e4d912ec9b964ceb6e90212ed52353d229dcea",
    "source_documents": "7f3c91f5243f01b18b0a26a58a46a01cd3b1fee708bb61b139862ffdf649633a",
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


def _payloads(pack: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = candidate_release.build_pack_artifacts(
        pack,
        SEMANTIC_R3_RELEASE_ID,
        expected_semantic_documents=SEMANTIC_R3_COUNTS["semantic_documents"],
    )
    return {
        "graph": {
            "schema_version": "knowledge-engine-document-graph/v1",
            "release_id": SEMANTIC_R3_RELEASE_ID,
            "nodes": artifacts["graph_nodes"],
            "edges": artifacts["graph_edges"],
        },
        "graph_v2": {
            "schema_version": "knowledge-engine-graph-v2/v1",
            "release": {
                "release_id": SEMANTIC_R3_RELEASE_ID,
                "engine_commit_sha": SEMANTIC_R3_ENGINE_SHA,
                "source_commit_sha": live_candidate.SOURCE_SHA,
                "foundation_commit_sha": live_candidate.FOUNDATION_SHA,
            },
            "nodes": artifacts["graph_v2_nodes"],
            "edges": artifacts["graph_v2_edges"],
        },
        "lexical_index": {
            "schema_version": "knowledge-engine-lexical-index/v2",
            "release_id": SEMANTIC_R3_RELEASE_ID,
            "documents": artifacts["lexical_documents"],
        },
        "semantic_inputs": {
            "schema_version": "knowledge-engine-semantic-inputs/v1",
            "release_id": SEMANTIC_R3_RELEASE_ID,
            "model": live_candidate.CLOUDFLARE_MODEL,
            "vector_dimension": live_candidate.VECTOR_DIMENSION,
            "documents": artifacts["semantic_inputs"],
        },
        "document_source_index": {
            "schema_version": "knowledge-source-document-index/v1",
            "release_id": SEMANTIC_R3_RELEASE_ID,
            "source_repository": live_candidate.SOURCE_REPOSITORY,
            "source_commit_sha": live_candidate.SOURCE_SHA,
            "source_count": SEMANTIC_R3_COUNTS["sources"],
            "sources": artifacts["source_index"],
        },
        "provenance": {
            "schema_version": "knowledge-engine-document-provenance/v1",
            "release_id": SEMANTIC_R3_RELEASE_ID,
            "records": artifacts["provenance"],
        },
        "source_documents": live_candidate._source_documents(pack),
    }


def _manifest(
    *,
    pack: Mapping[str, Any],
    payload_bytes: Mapping[str, bytes],
) -> dict[str, Any]:
    source_graph = {"nodes": pack["nodes"], "edges": pack["edges"]}
    manifest: dict[str, Any] = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": SEMANTIC_R3_RELEASE_ID,
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
            "engine_commit_sha": SEMANTIC_R3_ENGINE_SHA,
            "repair_parent_sha": SEMANTIC_R3_PARENT_SHA,
            "source_repository": live_candidate.SOURCE_REPOSITORY,
            "source_commit_sha": live_candidate.SOURCE_SHA,
            "foundation_commit_sha": live_candidate.FOUNDATION_SHA,
            "admission_sha256": live_candidate.ADMISSION_SHA,
            "repair_kind": "aqv2-semantic-evidence-preservation-r3",
            "repaired_source_graph_canonical_sha256": canonical_sha256(source_graph),
        },
        "counts": {
            "document_sources": 156,
            "document_series": 25,
            "document_articles": 156,
            "document_sections": SEMANTIC_R3_COUNTS["sections"],
            "document_graph_nodes": SEMANTIC_R3_COUNTS["graph_nodes"],
            "document_graph_edges": SEMANTIC_R3_COUNTS["graph_edges"],
            "lexical_documents": SEMANTIC_R3_COUNTS["lexical_documents"],
            "semantic_documents": SEMANTIC_R3_COUNTS["semantic_documents"],
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
        filename = _ARTIFACT_FILENAMES[kind]
        data = payload_bytes[kind]
        manifest["artifacts"].append(
            {
                "kind": kind,
                "key": f"releases/{SEMANTIC_R3_RELEASE_ID}/artifacts/{filename}",
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "media_type": "application/json",
                "audiences": ["authenticated_internal"],
                "required": True,
            }
        )
    return manifest


def build_semantic_r3_candidate_bundle(pack: Mapping[str, Any]) -> ProductionAnswerBundle:
    payloads = _payloads(pack)
    payload_bytes = {kind: _pretty_bytes(value) for kind, value in payloads.items()}
    artifact_sha256 = {
        kind: hashlib.sha256(data).hexdigest() for kind, data in payload_bytes.items()
    }
    manifest = _manifest(pack=pack, payload_bytes=payload_bytes)
    manifest_sha256 = hashlib.sha256(_pretty_bytes(manifest)).hexdigest()
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
        manifest_sha256=manifest_sha256,
        artifact_sha256=artifact_sha256,
        artifact_keys=artifact_keys,
        loaded_at="qualification",
        source_documents=payloads["source_documents"],
        document_source_index=payloads["document_source_index"],
        semantic_inputs=payloads["semantic_inputs"],
    )
    reason = semantic_r3_authority_mismatch(bundle)
    if reason is not None:
        raise IntegrityError(reason)
    return bundle


def _populations(bundle: ProductionAnswerBundle) -> dict[str, int]:
    semantic_inputs = bundle.semantic_inputs or {}
    return {
        "graph_nodes": len(bundle.graph_v2.get("nodes", [])),
        "graph_edges": len(bundle.graph_v2.get("edges", [])),
        "lexical_documents": len(bundle.lexical_index.get("documents", [])),
        "semantic_documents": len(semantic_inputs.get("documents", [])),
    }


def semantic_r3_authority_mismatch(bundle: ProductionAnswerBundle) -> str | None:
    if bundle.release_id != SEMANTIC_R3_RELEASE_ID:
        return "PA7_SEMANTIC_R3_CANDIDATE_RELEASE_MISMATCH"
    if bundle.manifest_sha256 != SEMANTIC_R3_MANIFEST_SHA256:
        return "PA7_SEMANTIC_R3_CANDIDATE_MANIFEST_DIGEST_MISMATCH"
    identities = bundle.manifest.get("identities")
    if not isinstance(identities, Mapping):
        return "PA7_SEMANTIC_R3_CANDIDATE_MANIFEST_IDENTITY_MISMATCH"
    if identities.get("engine_commit_sha") != SEMANTIC_R3_ENGINE_SHA:
        return "PA7_SEMANTIC_R3_CANDIDATE_MANIFEST_IDENTITY_MISMATCH"
    if identities.get("repair_parent_sha") != SEMANTIC_R3_PARENT_SHA:
        return "PA7_SEMANTIC_R3_CANDIDATE_MANIFEST_IDENTITY_MISMATCH"
    if (
        identities.get("repaired_source_graph_canonical_sha256")
        != SEMANTIC_R3_SOURCE_GRAPH_CANONICAL_SHA256
    ):
        return "PA7_SEMANTIC_R3_CANDIDATE_SOURCE_GRAPH_MISMATCH"
    if dict(bundle.artifact_sha256) != SEMANTIC_R3_ARTIFACT_SHA256:
        return "PA7_SEMANTIC_R3_CANDIDATE_ARTIFACT_DIGEST_MISMATCH"
    payloads = {
        "graph": bundle.graph,
        "graph_v2": bundle.graph_v2,
        "lexical_index": bundle.lexical_index,
        "semantic_inputs": bundle.semantic_inputs or {},
        "document_source_index": bundle.document_source_index or {},
        "provenance": bundle.provenance,
        "source_documents": bundle.source_documents or {},
    }
    canonical = {kind: canonical_sha256(value) for kind, value in payloads.items()}
    if canonical != SEMANTIC_R3_CANONICAL_SHA256:
        return "PA7_SEMANTIC_R3_CANDIDATE_RUNTIME_ARTIFACT_MISMATCH"
    if _populations(bundle) != {
        key: SEMANTIC_R3_COUNTS[key]
        for key in (
            "graph_nodes",
            "graph_edges",
            "lexical_documents",
            "semantic_documents",
        )
    }:
        return "PA7_SEMANTIC_R3_CANDIDATE_POPULATION_MISMATCH"
    if bundle.graph.get("schema_version") != "knowledge-engine-document-graph/v1":
        return "PA7_SEMANTIC_R3_CANDIDATE_SCHEMA_MISMATCH"
    if bundle.graph.get("release_id") != SEMANTIC_R3_RELEASE_ID:
        return "PA7_SEMANTIC_R3_CANDIDATE_SCHEMA_MISMATCH"
    if bundle.graph_v2.get("schema_version") != "knowledge-engine-graph-v2/v1":
        return "PA7_SEMANTIC_R3_CANDIDATE_SCHEMA_MISMATCH"
    graph_v2_release = bundle.graph_v2.get("release")
    if not isinstance(graph_v2_release, Mapping):
        return "PA7_SEMANTIC_R3_CANDIDATE_SCHEMA_MISMATCH"
    if graph_v2_release.get("release_id") != SEMANTIC_R3_RELEASE_ID:
        return "PA7_SEMANTIC_R3_CANDIDATE_SCHEMA_MISMATCH"
    if bundle.lexical_index.get("release_id") != SEMANTIC_R3_RELEASE_ID:
        return "PA7_SEMANTIC_R3_CANDIDATE_SCHEMA_MISMATCH"
    semantic_inputs = bundle.semantic_inputs or {}
    if semantic_inputs.get("release_id") != SEMANTIC_R3_RELEASE_ID:
        return "PA7_SEMANTIC_R3_CANDIDATE_SCHEMA_MISMATCH"
    graph_ids = {
        str(item.get("concept_id", ""))
        for item in bundle.graph.get("nodes", [])
        if isinstance(item, Mapping)
    }
    graph_v2_ids = {
        str(item.get("concept_id", ""))
        for item in bundle.graph_v2.get("nodes", [])
        if isinstance(item, Mapping)
    }
    if graph_ids != graph_v2_ids:
        return "PA7_SEMANTIC_R3_CANDIDATE_GRAPH_FAMILY_MISMATCH"
    return None
