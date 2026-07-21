from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m14_public_contracts import (
    Audience,
    PublicSearchResponse,
    SearchSort,
    public_search_response_from_runtime,
)
from .m14_retrieval import retrieve_wiki_first, validate_relation_graph_v2
from .m19_graph_api import ReadOnlyGraphService
from .m24_concept_wiki import ConceptWikiPage, build_concept_wiki_page
from .m24_graph_navigation import GraphNavigationState, build_graph_navigation_state
from .m24_obsidian_exporter import (
    ObsidianExportBundle,
    export_search_response_to_obsidian,
    load_source_document_package,
)
from .runtime import ActiveRelease
from .storage import sha256_bytes

P3_SCHEMA = "knowledge-engine-m24-p3-product-surface-integration/v1"
P3_ISSUE_NUMBER = 991
CANONICAL_RELEASE_ID = "20260720T160000Z-46137c97263e"
CANONICAL_MANIFEST_SHA256 = (
    "ef5ee828069731e3e7106e1b12fb82e3a578c377930568410bc78421d1600877"
)
CANONICAL_SOURCE_SHA = "acf78596ace8a7366688ccef72b507204d09d9f9"
CANONICAL_ROOT = Path(__file__).resolve().parents[2] / "pilot/m24/canonical-release"
P3_QUERIES = (
    "harness",
    "stopping policy",
    "canonical run authority",
    "tool call proposal",
)


class P3AuthorityBoundary(BaseModel):
    production_retrieval: Literal["lexical"] = "lexical"
    semantic_promotion_enabled: bool = False
    semantic_serving_enabled: bool = False
    hybrid_retrieval_enabled: bool = False
    production_pointer_mutation: bool = False
    production_r2_mutation: bool = False
    qdrant_mutation: bool = False
    source_mutation: bool = False
    credential_mutation: bool = False
    traffic_mutation: bool = False
    raw_evidence_exposed: bool = False


class P3SurfaceEvidence(BaseModel):
    surface: Literal[
        "lexical_search",
        "source_viewer",
        "concept_wiki",
        "sigma_graph",
        "obsidian_export",
    ]
    release_id: str
    request_id: str | None = None
    concept_count: int = Field(default=0, ge=0)
    source_viewer_count: int = Field(default=0, ge=0)
    edge_count: int = Field(default=0, ge=0)
    file_count: int = Field(default=0, ge=0)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class P3ProductSurfaceReport(BaseModel):
    schema_version: str = P3_SCHEMA
    status: Literal["product_surface_integration_complete"]
    issue_number: int
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str
    graph_v2_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lexical_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_surfaces: list[P3SurfaceEvidence]
    shared_exit_gate: dict[str, Any]
    authority: P3AuthorityBoundary
    self_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


@dataclass(frozen=True)
class CanonicalReleaseBundle:
    root: Path
    manifest: dict[str, Any]
    graph: dict[str, Any]
    graph_v2: dict[str, Any]
    lexical_index: dict[str, Any]
    provenance: dict[str, Any]
    source_snapshot: dict[str, Any]
    manifest_sha256: str
    artifact_sha256: dict[str, str]

    @property
    def release_id(self) -> str:
        value = self.manifest.get("release_id")
        if not isinstance(value, str):
            raise ValueError("canonical manifest is missing release_id")
        return value


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest_model(value: BaseModel | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _artifact_by_kind(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("canonical manifest artifacts must be a list")
    by_kind: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("canonical artifact entry must be an object")
        kind = artifact.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ValueError("canonical artifact entry is missing kind")
        by_kind[kind] = artifact
    return by_kind


def load_canonical_release(root: Path | None = None) -> CanonicalReleaseBundle:
    release_root = (root or CANONICAL_ROOT).resolve()
    manifest_path = release_root / "manifest.json"
    manifest_data = manifest_path.read_bytes()
    manifest_sha256 = sha256_bytes(manifest_data)
    if manifest_sha256 != CANONICAL_MANIFEST_SHA256:
        raise ValueError("canonical manifest digest does not match P2 evidence")

    manifest = _load_json(manifest_path)
    if manifest.get("release_id") != CANONICAL_RELEASE_ID:
        raise ValueError("canonical release ID does not match P2 evidence")
    if manifest.get("source", {}).get("commit_sha") != CANONICAL_SOURCE_SHA:
        raise ValueError("canonical Source SHA does not match adopted Source")

    artifacts = _artifact_by_kind(manifest)
    local_artifacts = {
        "graph": release_root / "artifacts/graph.json",
        "graph_v2": release_root / "artifacts/graph-v2.json",
        "lexical_index": release_root / "artifacts/lexical-index.json",
        "provenance": release_root / "artifacts/provenance.json",
        "source_snapshot": release_root / "artifacts/source-snapshot.json",
    }
    artifact_sha256: dict[str, str] = {}
    for kind, path in local_artifacts.items():
        data = path.read_bytes()
        digest = sha256_bytes(data)
        expected = artifacts.get(kind, {}).get("sha256")
        if digest != expected:
            raise ValueError(f"canonical artifact digest mismatch: {kind}")
        artifact_sha256[kind] = digest

    graph = _load_json(local_artifacts["graph"])
    graph_v2 = _load_json(local_artifacts["graph_v2"])
    validate_relation_graph_v2(
        graph_v2,
        expected_release_id=CANONICAL_RELEASE_ID,
        compatibility_graph=graph,
    )
    return CanonicalReleaseBundle(
        root=release_root,
        manifest=manifest,
        graph=graph,
        graph_v2=graph_v2,
        lexical_index=_load_json(local_artifacts["lexical_index"]),
        provenance=_load_json(local_artifacts["provenance"]),
        source_snapshot=_load_json(local_artifacts["source_snapshot"]),
        manifest_sha256=manifest_sha256,
        artifact_sha256=artifact_sha256,
    )


def active_canonical_release(
    bundle: CanonicalReleaseBundle | None = None,
) -> ActiveRelease:
    loaded = bundle or load_canonical_release()
    return ActiveRelease(
        release_id=loaded.release_id,
        manifest_sha256=loaded.manifest_sha256,
        loaded_at="2026-07-20T16:00:00Z",
        manifest=loaded.manifest,
        lexical_index=loaded.lexical_index,
        graph=loaded.graph,
        graph_v2=loaded.graph_v2,
        provenance=loaded.provenance,
        semantic_index=None,
        semantic_runtime=None,
    )


def _release_identity(bundle: CanonicalReleaseBundle) -> dict[str, str]:
    return {
        "release_id": bundle.release_id,
        "manifest_sha256": bundle.manifest_sha256,
    }


def canonical_runtime_search(
    *,
    query: str,
    max_results: int = 5,
    audience: Audience = "internal",
    sort_by: SearchSort = "relevance",
    source_kind: str | None = None,
    bundle: CanonicalReleaseBundle | None = None,
) -> PublicSearchResponse:
    loaded = bundle or load_canonical_release()
    runtime_result = retrieve_wiki_first(
        query=query,
        allowed_audiences={"public", "internal"},
        lexical_index=loaded.lexical_index,
        graph=loaded.graph,
        relation_graph=loaded.graph_v2,
        relation_aware_expansion=True,
        provenance=loaded.provenance,
        semantic_index=None,
        limit=max_results,
    )
    runtime_result["release"] = _release_identity(loaded)
    return public_search_response_from_runtime(
        runtime_result,
        query=query,
        max_results=max_results,
        audience=audience,
        sort_by=sort_by,
        source_kind=source_kind,
    )


def graph_service(bundle: CanonicalReleaseBundle | None = None) -> ReadOnlyGraphService:
    return ReadOnlyGraphService(
        active_canonical_release(bundle),
        allowed_audiences={"public", "internal"},
    )


def canonical_concept_wiki_page(
    *,
    concept_id: str,
    query: str = "harness",
    bundle: CanonicalReleaseBundle | None = None,
) -> ConceptWikiPage:
    loaded = bundle or load_canonical_release()
    response = canonical_runtime_search(query=query, max_results=20, bundle=loaded)
    service = graph_service(loaded)
    neighborhood = service.neighborhood(
        concept_id,
        depth=1,
        relation_types=[],
        max_nodes=25,
        max_edges=50,
    )
    return build_concept_wiki_page(
        response,
        concept_id=concept_id,
        graph_neighborhood=neighborhood,
    )


def canonical_graph_navigation_state(
    *,
    selected_concept_id: str,
    bundle: CanonicalReleaseBundle | None = None,
) -> GraphNavigationState:
    loaded = bundle or load_canonical_release()
    service = graph_service(loaded)
    overview = service.overview(cluster_level="none", max_nodes=50, max_edges=100)
    neighborhood = service.neighborhood(
        selected_concept_id,
        depth=1,
        relation_types=[],
        max_nodes=25,
        max_edges=50,
    )
    return build_graph_navigation_state(
        overview,
        selected_concept_id=selected_concept_id,
        focus_neighborhood=neighborhood,
    )


def _record_by_concept(bundle: CanonicalReleaseBundle) -> dict[str, dict[str, Any]]:
    return {
        record["subject"]["concept_id"]: record
        for record in bundle.provenance.get("records", [])
        if isinstance(record, dict)
        and isinstance(record.get("subject"), dict)
        and isinstance(record["subject"].get("concept_id"), str)
    }


def _first_document_by_concept(bundle: CanonicalReleaseBundle) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    documents = bundle.lexical_index.get("documents")
    if not isinstance(documents, list):
        raise ValueError("canonical lexical index documents must be a list")
    for document in documents:
        if not isinstance(document, dict):
            raise ValueError("canonical lexical document must be an object")
        concept_id = document.get("concept_id")
        section_id = document.get("section_id")
        if not isinstance(concept_id, str) or not isinstance(section_id, str):
            raise ValueError("canonical lexical document identity is invalid")
        previous = selected.get(concept_id)
        if previous is None or section_id < str(previous.get("section_id")):
            selected[concept_id] = document
    return selected


def _citation_from_source(
    *,
    source: dict[str, Any],
    record: dict[str, Any],
    document: dict[str, Any],
) -> dict[str, Any]:
    claims = record.get("claims") if isinstance(record.get("claims"), list) else []
    first_claim = next((item for item in claims if isinstance(item, dict)), {})
    evidence = first_claim.get("evidence") if isinstance(first_claim, dict) else None
    evidence_items = evidence if isinstance(evidence, list) else []
    first_evidence = next((item for item in evidence_items if isinstance(item, dict)), {})
    locator: dict[str, Any] = {}
    if isinstance(first_evidence, dict):
        heading = first_evidence.get("locator")
        if isinstance(heading, str) and heading:
            locator["heading"] = heading
        source_lines = first_evidence.get("source_lines")
        if isinstance(source_lines, str) and source_lines:
            locator["anchor"] = f"source_lines:{source_lines}"
    return {
        "source_id": source.get("source_id"),
        "source_kind": source.get("source_kind", "web"),
        "source_title": source.get("origin_path") or source.get("uri"),
        "publisher": "LLM Wiki Source",
        "uri": source.get("uri") or source.get("locator"),
        "retrieved_at": source.get("retrieved_at"),
        "concept_id": document["concept_id"],
        "section_id": document["section_id"],
        "citation_scope": "claim" if first_claim else "concept",
        "support": "supporting",
        "locator": locator or None,
        "claim_id": first_claim.get("claim_id") if isinstance(first_claim, dict) else None,
        "claim_confidence": record.get("confidence"),
        "review_status": record.get("review_status")
        or record.get("review_decision_id"),
        "derivation_type": record.get("method"),
        "content_sha256": source.get("content_sha256"),
        "snapshot_available": True,
    }


def canonical_all_concepts_response(
    *,
    bundle: CanonicalReleaseBundle | None = None,
) -> PublicSearchResponse:
    loaded = bundle or load_canonical_release()
    documents = _first_document_by_concept(loaded)
    records = _record_by_concept(loaded)
    nodes = sorted(
        loaded.graph_v2["nodes"],
        key=lambda item: str(item.get("title") or item.get("concept_id")),
    )
    results: list[dict[str, Any]] = []
    for node in nodes:
        concept_id = node["concept_id"]
        document = documents[concept_id]
        record = records.get(concept_id, {})
        citations = [
            _citation_from_source(source=source, record=record, document=document)
            for source in record.get("sources", [])
            if isinstance(source, dict)
        ]
        results.append(
            {
                "concept_id": concept_id,
                "section_id": document["section_id"],
                "x_kos_id": node.get("x_kos_id"),
                "title": node.get("title") or document["title"],
                "section_title": document.get("section_title") or node.get("title"),
                "description": node.get("description") or document.get("description"),
                "excerpt": document.get("excerpt") or document.get("body"),
                "audience": node.get("audience"),
                "score": 1.0,
                "citations": citations,
            }
        )
    runtime_result = {
        "status": "answered",
        "results": results,
        "release": _release_identity(loaded),
    }
    return public_search_response_from_runtime(
        runtime_result,
        query="canonical concept export",
        max_results=20,
        audience="internal",
        sort_by="title",
    )


def canonical_obsidian_export(
    bundle: CanonicalReleaseBundle | None = None,
) -> ObsidianExportBundle:
    return export_search_response_to_obsidian(
        canonical_all_concepts_response(bundle=bundle),
        source_documents=load_source_document_package(),
    )


def build_p3_product_surface_report(
    *,
    bundle: CanonicalReleaseBundle | None = None,
    include_self_digest: bool = True,
) -> P3ProductSurfaceReport:
    loaded = bundle or load_canonical_release()
    search = canonical_runtime_search(query=P3_QUERIES[0], max_results=5, bundle=loaded)
    source_digest = _digest_model(
        {
            "release_id": search.release_id,
            "source_viewers": [
                viewer.model_dump(mode="json") for viewer in search.source_viewers
            ],
        }
    )
    concept_id = search.results[0].concept_id
    concept_page = canonical_concept_wiki_page(
        concept_id=concept_id,
        query=P3_QUERIES[0],
        bundle=loaded,
    )
    graph_state = canonical_graph_navigation_state(
        selected_concept_id=concept_id,
        bundle=loaded,
    )
    obsidian = canonical_obsidian_export(bundle=loaded)
    surfaces = [
        P3SurfaceEvidence(
            surface="lexical_search",
            release_id=search.release_id,
            request_id=search.request_id,
            concept_count=len(search.results),
            source_viewer_count=len(search.source_viewers),
            digest=_digest_model(search),
        ),
        P3SurfaceEvidence(
            surface="source_viewer",
            release_id=search.release_id,
            request_id=search.request_id,
            concept_count=len(search.concept_ids),
            source_viewer_count=len(search.source_viewers),
            digest=source_digest,
        ),
        P3SurfaceEvidence(
            surface="concept_wiki",
            release_id=concept_page.release_id,
            request_id=concept_page.request_id,
            concept_count=1,
            source_viewer_count=len(concept_page.source_viewers),
            edge_count=len(concept_page.relationships),
            digest=_digest_model(concept_page),
        ),
        P3SurfaceEvidence(
            surface="sigma_graph",
            release_id=graph_state.release_id,
            concept_count=len(graph_state.nodes),
            edge_count=len(graph_state.edges),
            digest=_digest_model(graph_state),
        ),
        P3SurfaceEvidence(
            surface="obsidian_export",
            release_id=obsidian.release_id,
            request_id=obsidian.request_id,
            concept_count=len(
                [item for item in obsidian.files if item.path.startswith("concepts/")]
            ),
            source_viewer_count=len(
                [item for item in obsidian.files if item.path.startswith("sources/")]
            ),
            file_count=len(obsidian.files),
            digest=obsidian.manifest_sha256,
        ),
    ]
    report = P3ProductSurfaceReport(
        status="product_surface_integration_complete",
        issue_number=P3_ISSUE_NUMBER,
        release_id=loaded.release_id,
        manifest_sha256=loaded.manifest_sha256,
        source_commit_sha=CANONICAL_SOURCE_SHA,
        graph_v2_sha256=loaded.artifact_sha256["graph_v2"],
        lexical_index_sha256=loaded.artifact_sha256["lexical_index"],
        provenance_sha256=loaded.artifact_sha256["provenance"],
        source_snapshot_sha256=loaded.artifact_sha256["source_snapshot"],
        product_surfaces=surfaces,
        shared_exit_gate={
            "same_canonical_candidate_release": True,
            "surface_count": len(surfaces),
            "queries": list(P3_QUERIES),
            "semantic_promotion_required_before_production_semantic_or_hybrid": True,
        },
        authority=P3AuthorityBoundary(),
    )
    if include_self_digest:
        payload = report.model_dump(mode="json", exclude={"self_sha256"})
        report.self_sha256 = _digest_model(payload)
    return report
