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

PREAMBLE_R1_ENGINE_SHA = "6999067a4b5ce66dd80f0fac7782503d56c23ede"
PREAMBLE_R1_PARENT_SHA = "33c38536c8d6943b30cb819f00c42141cd622703"
PREAMBLE_R1_RELEASE_ID = live_candidate._candidate_release_id(PREAMBLE_R1_ENGINE_SHA)
PREAMBLE_R1_MANIFEST_SHA256 = (
    "80020ff4c83bbe35c7bd0421c471d8306b14955a283e7b4ba5646db71a232627"
)
PREAMBLE_R1_SOURCE_GRAPH_CANONICAL_SHA256 = (
    "6f2effc0716aedf7962c53f263395d9dfae5979a6b5615d71e6f21c9c694230e"
)
PREAMBLE_R1_COUNTS = {
    "graph_nodes": 4363,
    "graph_edges": 8807,
    "lexical_documents": 4338,
    "semantic_documents": 4338,
    "sections": 4182,
    "sources": 156,
}
PREAMBLE_R1_ARTIFACT_SHA256 = {
    "document_source_index": "b8514813b88ca87fecce76ef5865359e099eaa50ccab7617ab417f3be6a3b394",
    "graph": "a601502edd2662c72d15a2057c7ae2ffbc11d1f463ba4518de48b598c17a698f",
    "graph_v2": "1178ce94547f1d9fd662bfda80bd23a45869bf785fcb6fd78192d37713a48b68",
    "lexical_index": "463c2b5cd66f3c951fb3be56326583fb0b3f75af5903b03f5f56b3776fa2be48",
    "provenance": "8f00a00ac0a1620a276c29778d299ea9c71a02f8cb683e025877cdc8dafac723",
    "semantic_inputs": "4e0e25f0162e4f0477e6b93199032768f203fba85b56110f15fdd3c18097828a",
    "source_documents": "e3b5e8a4473a5f9e3a68f375b5eea5d054c4576b604e126ed1b99556713c7743",
}
PREAMBLE_R1_CANONICAL_SHA256 = {
    "document_source_index": "7bf3e2e0a3f0df6fa03a3a7eccada1a1e5814c3f6acfcc7918c3403f8b6a6d1a",
    "graph": "2b0e0272465c3bb376686a5a441de32b5c6f57e5996824cc0fd9961a1a45be74",
    "graph_v2": "4eee632441d537305c79eb09fb848da43db12fd46870b1353ae19d305deff18b",
    "lexical_index": "f281657076cf2e05c4ac675d9858645fbf555f48579b8bb982558b86038ad5f1",
    "provenance": "b3c86cf9cd8e729276bc7f3bc621bcefb24ff82c465e3303aa47237b622d7139",
    "semantic_inputs": "bcdc91d84ca659f6e43a190e2cf482ada49df282df39e80b34f681e12b5a7ba8",
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
        PREAMBLE_R1_RELEASE_ID,
        expected_semantic_documents=PREAMBLE_R1_COUNTS["semantic_documents"],
    )
    return {
        "graph": {
            "schema_version": "knowledge-engine-document-graph/v1",
            "release_id": PREAMBLE_R1_RELEASE_ID,
            "nodes": artifacts["graph_nodes"],
            "edges": artifacts["graph_edges"],
        },
        "graph_v2": {
            "schema_version": "knowledge-engine-graph-v2/v1",
            "release": {
                "release_id": PREAMBLE_R1_RELEASE_ID,
                "engine_commit_sha": PREAMBLE_R1_ENGINE_SHA,
                "source_commit_sha": live_candidate.SOURCE_SHA,
                "foundation_commit_sha": live_candidate.FOUNDATION_SHA,
            },
            "nodes": artifacts["graph_v2_nodes"],
            "edges": artifacts["graph_v2_edges"],
        },
        "lexical_index": {
            "schema_version": "knowledge-engine-lexical-index/v2",
            "release_id": PREAMBLE_R1_RELEASE_ID,
            "documents": artifacts["lexical_documents"],
        },
        "semantic_inputs": {
            "schema_version": "knowledge-engine-semantic-inputs/v1",
            "release_id": PREAMBLE_R1_RELEASE_ID,
            "model": live_candidate.CLOUDFLARE_MODEL,
            "vector_dimension": live_candidate.VECTOR_DIMENSION,
            "documents": artifacts["semantic_inputs"],
        },
        "document_source_index": {
            "schema_version": "knowledge-source-document-index/v1",
            "release_id": PREAMBLE_R1_RELEASE_ID,
            "source_repository": live_candidate.SOURCE_REPOSITORY,
            "source_commit_sha": live_candidate.SOURCE_SHA,
            "source_count": PREAMBLE_R1_COUNTS["sources"],
            "sources": artifacts["source_index"],
        },
        "provenance": {
            "schema_version": "knowledge-engine-document-provenance/v1",
            "release_id": PREAMBLE_R1_RELEASE_ID,
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
        "release_id": PREAMBLE_R1_RELEASE_ID,
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
            "engine_commit_sha": PREAMBLE_R1_ENGINE_SHA,
            "repair_parent_sha": PREAMBLE_R1_PARENT_SHA,
            "source_repository": live_candidate.SOURCE_REPOSITORY,
            "source_commit_sha": live_candidate.SOURCE_SHA,
            "foundation_commit_sha": live_candidate.FOUNDATION_SHA,
            "admission_sha256": live_candidate.ADMISSION_SHA,
            "repair_kind": "aqv2-preamble-r1",
            "repaired_source_graph_canonical_sha256": canonical_sha256(source_graph),
        },
        "counts": {
            "document_sources": 156,
            "document_series": 25,
            "document_articles": 156,
            "document_sections": PREAMBLE_R1_COUNTS["sections"],
            "document_graph_nodes": PREAMBLE_R1_COUNTS["graph_nodes"],
            "document_graph_edges": PREAMBLE_R1_COUNTS["graph_edges"],
            "lexical_documents": PREAMBLE_R1_COUNTS["lexical_documents"],
            "semantic_documents": PREAMBLE_R1_COUNTS["semantic_documents"],
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
                "key": f"releases/{PREAMBLE_R1_RELEASE_ID}/artifacts/{filename}",
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "media_type": "application/json",
                "audiences": ["authenticated_internal"],
                "required": True,
            }
        )
    return manifest


def build_preamble_r1_candidate_bundle(pack: Mapping[str, Any]) -> ProductionAnswerBundle:
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
    reason = preamble_r1_authority_mismatch(bundle)
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


def preamble_r1_authority_mismatch(bundle: ProductionAnswerBundle) -> str | None:
    if bundle.release_id != PREAMBLE_R1_RELEASE_ID:
        return "PA7_PREAMBLE_CANDIDATE_RELEASE_MISMATCH"
    if bundle.manifest_sha256 != PREAMBLE_R1_MANIFEST_SHA256:
        return "PA7_PREAMBLE_CANDIDATE_MANIFEST_DIGEST_MISMATCH"
    identities = bundle.manifest.get("identities")
    if not isinstance(identities, Mapping):
        return "PA7_PREAMBLE_CANDIDATE_MANIFEST_IDENTITY_MISMATCH"
    if identities.get("engine_commit_sha") != PREAMBLE_R1_ENGINE_SHA:
        return "PA7_PREAMBLE_CANDIDATE_MANIFEST_IDENTITY_MISMATCH"
    if identities.get("repair_parent_sha") != PREAMBLE_R1_PARENT_SHA:
        return "PA7_PREAMBLE_CANDIDATE_MANIFEST_IDENTITY_MISMATCH"
    if (
        identities.get("repaired_source_graph_canonical_sha256")
        != PREAMBLE_R1_SOURCE_GRAPH_CANONICAL_SHA256
    ):
        return "PA7_PREAMBLE_CANDIDATE_SOURCE_GRAPH_MISMATCH"
    if dict(bundle.artifact_sha256) != PREAMBLE_R1_ARTIFACT_SHA256:
        return "PA7_PREAMBLE_CANDIDATE_ARTIFACT_DIGEST_MISMATCH"
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
    if canonical != PREAMBLE_R1_CANONICAL_SHA256:
        return "PA7_PREAMBLE_CANDIDATE_RUNTIME_ARTIFACT_MISMATCH"
    if _populations(bundle) != {
        key: PREAMBLE_R1_COUNTS[key]
        for key in (
            "graph_nodes",
            "graph_edges",
            "lexical_documents",
            "semantic_documents",
        )
    }:
        return "PA7_PREAMBLE_CANDIDATE_POPULATION_MISMATCH"
    if bundle.graph.get("schema_version") != "knowledge-engine-document-graph/v1":
        return "PA7_PREAMBLE_CANDIDATE_SCHEMA_MISMATCH"
    if bundle.graph.get("release_id") != PREAMBLE_R1_RELEASE_ID:
        return "PA7_PREAMBLE_CANDIDATE_SCHEMA_MISMATCH"
    if bundle.graph_v2.get("schema_version") != "knowledge-engine-graph-v2/v1":
        return "PA7_PREAMBLE_CANDIDATE_SCHEMA_MISMATCH"
    graph_v2_release = bundle.graph_v2.get("release")
    if not isinstance(graph_v2_release, Mapping):
        return "PA7_PREAMBLE_CANDIDATE_SCHEMA_MISMATCH"
    if graph_v2_release.get("release_id") != PREAMBLE_R1_RELEASE_ID:
        return "PA7_PREAMBLE_CANDIDATE_SCHEMA_MISMATCH"
    if bundle.lexical_index.get("release_id") != PREAMBLE_R1_RELEASE_ID:
        return "PA7_PREAMBLE_CANDIDATE_SCHEMA_MISMATCH"
    semantic_inputs = bundle.semantic_inputs or {}
    if semantic_inputs.get("release_id") != PREAMBLE_R1_RELEASE_ID:
        return "PA7_PREAMBLE_CANDIDATE_SCHEMA_MISMATCH"
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
        return "PA7_PREAMBLE_CANDIDATE_GRAPH_FAMILY_MISMATCH"
    return None
