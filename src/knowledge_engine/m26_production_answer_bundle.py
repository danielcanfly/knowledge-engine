from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .errors import IntegrityError
from .m26_real_corpus_binding import POLICY_PATH, canonical_sha256, load_json
from .storage import create_object_store, sha256_bytes

FULL_PRODUCTION_RELEASE_ID = "m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043"
FULL_PRODUCTION_MANIFEST_KEY = f"releases/{FULL_PRODUCTION_RELEASE_ID}/manifest.json"
FULL_PRODUCTION_PROMOTION_MANIFEST_KEY = (
    f"releases/{FULL_PRODUCTION_RELEASE_ID}/promotion/m25-10-production-manifest.json"
)
FULL_PRODUCTION_PROMOTION_MANIFEST_SHA256 = (
    "72bb03e3fa22e453735719ab43898adfd4c7f186f818ed71685efb4fcd87de2b"
)
FULL_PRODUCTION_GRAPH_V2_SHA256 = (
    "ddaceb89bfda15618fdf9360953d9f66a5c8b33c3853480c1db7abe41ba32869"
)
FULL_PRODUCTION_POINTER_KEY = "channels/production.json"
FULL_PRODUCTION_POINTER_SHA256 = (
    "4a2cf8cc16d598cc2c6928491cf2c3b926e57e571297c61a8c3ff7a4ae396ff9"
)
FULL_PRODUCTION_QDRANT_COLLECTION = (
    "m25_blog_m25blog_5250f8422f4f_f5f01d82c7a1_fe499db2e043_fe499db2e043"
)
FULL_PRODUCTION_NODE_COUNT = 4222
FULL_PRODUCTION_EDGE_COUNT = 8525
FULL_PRODUCTION_SEMANTIC_POINT_COUNT = 4197
FULL_PRODUCTION_SOURCE_SHA = "5250f8422f4fa08c1f3dc84840dc756850817635"
FULL_PRODUCTION_ADMISSION_SHA256 = (
    "f5f01d82c7a1a38cf15fc54c890b904c4c015f608e2d25e294f9469f9b1927f2"
)

RUNTIME_REQUIRED_KINDS = frozenset({"graph", "graph_v2", "lexical_index", "provenance"})
COMPATIBILITY_REQUIRED_KINDS = frozenset(
    {
        "document_source_index",
        "graph",
        "graph_v2",
        "lexical_index",
        "provenance",
        "semantic_inputs",
        "source_documents",
    }
)


class ProductionAnswerBundleError(IntegrityError):
    """Fail-closed production answer bundle binding error."""


class ReadOnlyObjectGetter(Protocol):
    def get(self, key: str) -> bytes: ...


@dataclass(frozen=True)
class ProductionAnswerBundle:
    manifest: dict[str, Any]
    graph: dict[str, Any]
    graph_v2: dict[str, Any]
    lexical_index: dict[str, Any]
    provenance: dict[str, Any]
    manifest_sha256: str
    artifact_sha256: dict[str, str]
    artifact_keys: dict[str, str]
    loaded_at: str
    production_pointer: dict[str, Any] | None = None
    production_pointer_sha256: str | None = None
    production_manifest: dict[str, Any] | None = None
    production_manifest_sha256: str | None = None
    source_documents: dict[str, Any] | None = None
    document_source_index: dict[str, Any] | None = None
    semantic_inputs: dict[str, Any] | None = None

    @property
    def release_id(self) -> str:
        value = self.manifest.get("release_id")
        if not isinstance(value, str) or not value:
            raise ProductionAnswerBundleError("production answer manifest missing release_id")
        return value


def load_production_answer_bundle(
    *,
    store: ReadOnlyObjectGetter | None = None,
) -> ProductionAnswerBundle:
    if store is None:
        return _load_production_answer_bundle_from_env()
    return _load_production_answer_bundle_from_store(store)


@lru_cache(maxsize=1)
def _load_production_answer_bundle_from_env() -> ProductionAnswerBundle:
    settings = Settings.from_env()
    return _load_production_answer_bundle_from_store(create_object_store(settings))


def build_production_answer_compatibility_report(
    bundle: ProductionAnswerBundle,
    *,
    root: Path | None = None,
    qdrant_payload_samples: list[Mapping[str, Any]] | None = None,
    qdrant_point_count: int | None = None,
) -> dict[str, Any]:
    lexical_documents = _list(bundle.lexical_index.get("documents"), "lexical documents")
    graph_nodes = _graph_node_ids(bundle.graph)
    graph_v2_nodes = _graph_v2_node_ids(bundle.graph_v2)
    graph_v2_edges = _list(bundle.graph_v2.get("edges"), "graph_v2 edges")
    lexical_section_ids = {
        str(item.get("section_id", ""))
        for item in lexical_documents
        if isinstance(item, Mapping) and item.get("section_id")
    }
    lexical_concept_ids = {
        str(item.get("concept_id", ""))
        for item in lexical_documents
        if isinstance(item, Mapping) and item.get("concept_id")
    }
    provenance_concept_ids = _provenance_concept_ids(bundle.provenance)
    semantic_documents = _semantic_documents(bundle)
    semantic_section_ids = {
        str(item.get("section_id", ""))
        for item in semantic_documents
        if isinstance(item, Mapping) and item.get("section_id")
    }
    source_ids = _source_ids(bundle)
    lexical_source_ids = {
        str(item.get("source_id", ""))
        for item in lexical_documents
        if isinstance(item, Mapping) and item.get("source_id")
    }
    source_ids_from_provenance = _provenance_source_ids(bundle.provenance)
    qdrant_samples = qdrant_payload_samples or []
    qdrant_section_ids = {
        str(sample.get("section_id", ""))
        for sample in qdrant_samples
        if sample.get("section_id")
    }
    qdrant_mismatches = [
        dict(sample)
        for sample in qdrant_samples
        if not _qdrant_payload_matches_production(sample)
        or (
            sample.get("section_id")
            and semantic_section_ids
            and str(sample["section_id"]) not in semantic_section_ids
        )
    ]
    old_m24_concepts = _old_m24_concepts(root) if root is not None else set()
    outside_old_20_count = len(graph_v2_nodes - old_m24_concepts) if old_m24_concepts else None
    artifact_family = _artifact_family_report(bundle)
    expected_counts = _expected_counts(bundle)
    status = "compatible"
    mismatch_counts = {
        "graph_v1_v2_node_mismatch": len(graph_nodes ^ graph_v2_nodes),
        "lexical_concepts_missing_from_graph": len(lexical_concept_ids - graph_v2_nodes),
        "provenance_concepts_missing_from_graph": len(provenance_concept_ids - graph_v2_nodes)
        if provenance_concept_ids
        else 0,
        "lexical_sections_missing_from_semantic_inputs": len(
            lexical_section_ids - semantic_section_ids
        )
        if semantic_section_ids
        else 0,
        "semantic_sections_missing_from_lexical": len(semantic_section_ids - lexical_section_ids)
        if lexical_section_ids
        else 0,
        "lexical_sources_missing_from_source_index": len(lexical_source_ids - source_ids)
        if source_ids and lexical_source_ids
        else 0,
        "provenance_sources_missing_from_source_index": len(source_ids_from_provenance - source_ids)
        if source_ids and source_ids_from_provenance
        else 0,
        "qdrant_payload_sample_mismatches": len(qdrant_mismatches),
        "qdrant_point_count_mismatch": int(
            qdrant_point_count is not None
            and qdrant_point_count != FULL_PRODUCTION_SEMANTIC_POINT_COUNT
        ),
        "artifact_family_mismatches": len(artifact_family["mismatches"]),
        "manifest_count_mismatches": len(expected_counts["mismatches"]),
    }
    if any(mismatch_counts.values()):
        status = "incompatible"
    return {
        "schema_version": "knowledge-engine-m26-production-answer-compatibility/v1",
        "status": status,
        "release": {
            "release_id": bundle.release_id,
            "manifest_key": FULL_PRODUCTION_MANIFEST_KEY,
            "manifest_sha256": bundle.manifest_sha256,
            "promotion_manifest_key": FULL_PRODUCTION_PROMOTION_MANIFEST_KEY,
            "promotion_manifest_sha256": _promotion_manifest_sha(bundle),
            "pointer_key": FULL_PRODUCTION_POINTER_KEY,
            "pointer_sha256": _pointer_sha(bundle),
        },
        "artifacts": {
            "keys": dict(sorted(bundle.artifact_keys.items())),
            "sha256": dict(sorted(bundle.artifact_sha256.items())),
            "family": artifact_family,
        },
        "counts": {
            "graph_nodes": len(graph_v2_nodes),
            "graph_edges": len(graph_v2_edges),
            "lexical_sections": len(lexical_section_ids),
            "lexical_concepts": len(lexical_concept_ids),
            "provenance_concepts": len(provenance_concept_ids),
            "semantic_documents": len(semantic_section_ids),
            "source_ids": len(source_ids),
            "old_m24_concepts": len(old_m24_concepts) if old_m24_concepts else None,
            "outside_old_m24_concepts": outside_old_20_count,
            "manifest_expected": expected_counts["observed"],
        },
        "expected": {
            "release_id": FULL_PRODUCTION_RELEASE_ID,
            "graph_v2_sha256": FULL_PRODUCTION_GRAPH_V2_SHA256,
            "graph_nodes": FULL_PRODUCTION_NODE_COUNT,
            "graph_edges": FULL_PRODUCTION_EDGE_COUNT,
            "qdrant_collection": FULL_PRODUCTION_QDRANT_COLLECTION,
            "qdrant_points": FULL_PRODUCTION_SEMANTIC_POINT_COUNT,
        },
        "mismatch_counts": mismatch_counts,
        "qdrant": {
            "collection": FULL_PRODUCTION_QDRANT_COLLECTION,
            "observed_point_count": qdrant_point_count,
            "payload_required_fields": _qdrant_required_fields(root),
            "payload_sample_count": len(qdrant_samples),
            "payload_section_ids_sha256": canonical_sha256(sorted(qdrant_section_ids))
            if qdrant_section_ids
            else None,
        },
        "authority": {
            "read_only": True,
            "r2_writes": 0,
            "qdrant_writes": 0,
            "production_pointer_writes": 0,
            "canonical_writes": 0,
            "source_writes": 0,
            "answer_to_canonical_writes": 0,
        },
    }


def _load_production_answer_bundle_from_store(
    store: ReadOnlyObjectGetter,
) -> ProductionAnswerBundle:
    manifest_data = store.get(FULL_PRODUCTION_MANIFEST_KEY)
    manifest_sha256 = sha256_bytes(manifest_data)
    manifest = _json_object(manifest_data, "accepted production answer manifest")
    if manifest.get("release_id") != FULL_PRODUCTION_RELEASE_ID:
        raise ProductionAnswerBundleError("accepted production release identity mismatch")
    artifacts = _artifact_by_kind(manifest)
    missing = sorted(RUNTIME_REQUIRED_KINDS - set(artifacts))
    if missing:
        raise ProductionAnswerBundleError(
            "accepted production answer manifest missing runtime artifacts: " + ",".join(missing)
        )
    artifact_payloads: dict[str, dict[str, Any]] = {}
    artifact_sha256: dict[str, str] = {}
    artifact_keys: dict[str, str] = {}
    for kind in sorted(RUNTIME_REQUIRED_KINDS | (COMPATIBILITY_REQUIRED_KINDS & set(artifacts))):
        payload, digest, key = _load_artifact_json(store, manifest, kind)
        artifact_payloads[kind] = payload
        artifact_sha256[kind] = digest
        artifact_keys[kind] = key
    if artifact_sha256["graph_v2"] != FULL_PRODUCTION_GRAPH_V2_SHA256:
        raise ProductionAnswerBundleError("accepted production graph_v2 digest mismatch")
    graph = artifact_payloads["graph"]
    graph_v2 = artifact_payloads["graph_v2"]
    _validate_full_production_graphs(graph=graph, graph_v2=graph_v2)
    if len(_list(graph_v2.get("nodes"), "graph_v2 nodes")) != FULL_PRODUCTION_NODE_COUNT:
        raise ProductionAnswerBundleError("accepted production graph node count mismatch")
    if len(_list(graph_v2.get("edges"), "graph_v2 edges")) != FULL_PRODUCTION_EDGE_COUNT:
        raise ProductionAnswerBundleError("accepted production graph edge count mismatch")
    pointer, pointer_sha256 = _optional_json(store, FULL_PRODUCTION_POINTER_KEY)
    production_manifest, production_manifest_sha256 = _optional_json(
        store,
        FULL_PRODUCTION_PROMOTION_MANIFEST_KEY,
    )
    _validate_pointer_and_promotion_manifest(pointer, production_manifest, manifest)
    return ProductionAnswerBundle(
        manifest=manifest,
        graph=graph,
        graph_v2=graph_v2,
        lexical_index=artifact_payloads["lexical_index"],
        provenance=artifact_payloads["provenance"],
        manifest_sha256=manifest_sha256,
        artifact_sha256=artifact_sha256,
        artifact_keys=artifact_keys,
        loaded_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        production_pointer=pointer,
        production_pointer_sha256=pointer_sha256,
        production_manifest=production_manifest,
        production_manifest_sha256=production_manifest_sha256,
        source_documents=artifact_payloads.get("source_documents"),
        document_source_index=artifact_payloads.get("document_source_index"),
        semantic_inputs=artifact_payloads.get("semantic_inputs"),
    )


def _artifact_by_kind(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ProductionAnswerBundleError("production answer manifest artifacts must be a list")
    by_kind: dict[str, Mapping[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise ProductionAnswerBundleError("production answer artifact entry must be an object")
        kind = artifact.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ProductionAnswerBundleError("production answer artifact missing kind")
        if kind in by_kind:
            raise ProductionAnswerBundleError("production answer artifact kind duplicated")
        by_kind[kind] = artifact
    return by_kind


def _load_artifact_json(
    store: ReadOnlyObjectGetter,
    manifest: Mapping[str, Any],
    kind: str,
) -> tuple[dict[str, Any], str, str]:
    entry = _artifact_by_kind(manifest).get(kind)
    if entry is None:
        raise ProductionAnswerBundleError(f"production answer artifact missing: {kind}")
    key = str(entry.get("key", ""))
    if not key.startswith(f"releases/{FULL_PRODUCTION_RELEASE_ID}/"):
        raise ProductionAnswerBundleError(f"production answer artifact key escapes release: {kind}")
    data = store.get(key)
    expected_bytes = entry.get("bytes")
    if isinstance(expected_bytes, int) and len(data) != expected_bytes:
        raise ProductionAnswerBundleError(f"production answer artifact byte mismatch: {kind}")
    digest = sha256_bytes(data)
    if digest != entry.get("sha256"):
        raise ProductionAnswerBundleError(f"production answer artifact digest mismatch: {kind}")
    return _json_object(data, f"production answer artifact {kind}"), digest, key


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionAnswerBundleError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ProductionAnswerBundleError(f"{label} must be a JSON object")
    return value


def _optional_json(
    store: ReadOnlyObjectGetter,
    key: str,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = store.get(key)
    except FileNotFoundError:
        return None, None
    except KeyError:
        return None, None
    return _json_object(data, key), sha256_bytes(data)


def _validate_pointer_and_promotion_manifest(
    pointer: Mapping[str, Any] | None,
    production_manifest: Mapping[str, Any] | None,
    direct_manifest: Mapping[str, Any],
) -> None:
    if pointer is not None:
        if pointer.get("release_id") != FULL_PRODUCTION_RELEASE_ID:
            raise ProductionAnswerBundleError("production pointer release identity mismatch")
        if pointer.get("manifest_key") != FULL_PRODUCTION_PROMOTION_MANIFEST_KEY:
            raise ProductionAnswerBundleError("production pointer manifest key mismatch")
        if pointer.get("manifest_sha256") != FULL_PRODUCTION_PROMOTION_MANIFEST_SHA256:
            raise ProductionAnswerBundleError("production pointer manifest digest mismatch")
    if production_manifest is None:
        return
    if production_manifest.get("release_id") != FULL_PRODUCTION_RELEASE_ID:
        raise ProductionAnswerBundleError("production promotion manifest release mismatch")
    production_artifacts = _artifact_by_kind(production_manifest)
    direct_artifacts = _artifact_by_kind(direct_manifest)
    for kind in RUNTIME_REQUIRED_KINDS:
        prod = production_artifacts.get(kind)
        direct = direct_artifacts.get(kind)
        if prod is None or direct is None or prod.get("sha256") != direct.get("sha256"):
            raise ProductionAnswerBundleError(
                f"production/direct manifest artifact family mismatch: {kind}"
            )


def _validate_full_production_graphs(
    *,
    graph: Mapping[str, Any],
    graph_v2: Mapping[str, Any],
) -> None:
    if graph.get("schema_version") != "knowledge-engine-document-graph/v1":
        raise ProductionAnswerBundleError("production graph schema mismatch")
    if graph_v2.get("schema_version") != "knowledge-engine-graph-v2/v1":
        raise ProductionAnswerBundleError("production graph_v2 schema mismatch")
    if graph.get("release_id") != FULL_PRODUCTION_RELEASE_ID:
        raise ProductionAnswerBundleError("production graph release mismatch")
    release = graph_v2.get("release")
    if not isinstance(release, Mapping) or release.get("release_id") != FULL_PRODUCTION_RELEASE_ID:
        raise ProductionAnswerBundleError("production graph_v2 release mismatch")
    graph_nodes = _graph_node_ids(graph)
    graph_v2_nodes = _graph_v2_node_ids(graph_v2)
    if graph_nodes != graph_v2_nodes:
        raise ProductionAnswerBundleError("production graph node family mismatch")
    seen_edges: set[str] = set()
    for edge in _list(graph_v2.get("edges"), "graph_v2 edges"):
        if not isinstance(edge, Mapping):
            raise ProductionAnswerBundleError("production graph_v2 edge must be an object")
        edge_id = edge.get("edge_id")
        source = edge.get("source")
        target = edge.get("target")
        if not isinstance(edge_id, str) or not edge_id or edge_id in seen_edges:
            raise ProductionAnswerBundleError("production graph_v2 edge identity invalid")
        if source not in graph_v2_nodes or target not in graph_v2_nodes:
            raise ProductionAnswerBundleError("production graph_v2 edge endpoint missing")
        if not isinstance(edge.get("relation_type"), str) or not edge.get("relation_type"):
            raise ProductionAnswerBundleError("production graph_v2 edge relation invalid")
        if edge.get("review_status") != "approved":
            raise ProductionAnswerBundleError("production graph_v2 edge is not approved")
        if not isinstance(edge.get("directed"), bool):
            raise ProductionAnswerBundleError("production graph_v2 edge directed flag invalid")
        confidence = edge.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ProductionAnswerBundleError("production graph_v2 edge confidence invalid")
        if not 0 <= float(confidence) <= 1:
            raise ProductionAnswerBundleError("production graph_v2 edge confidence invalid")
        seen_edges.add(edge_id)


def _graph_node_ids(graph: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("concept_id", ""))
        for item in _list(graph.get("nodes"), "graph nodes")
        if isinstance(item, Mapping) and item.get("concept_id")
    }


def _graph_v2_node_ids(graph_v2: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("concept_id", ""))
        for item in _list(graph_v2.get("nodes"), "graph_v2 nodes")
        if isinstance(item, Mapping) and item.get("concept_id")
    }


def _provenance_concept_ids(provenance: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for record in provenance.get("records", []):
        if not isinstance(record, Mapping):
            continue
        subject = record.get("subject")
        if isinstance(subject, Mapping) and isinstance(subject.get("concept_id"), str):
            ids.add(str(subject["concept_id"]))
    return ids


def _provenance_source_ids(provenance: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for record in provenance.get("records", []):
        if not isinstance(record, Mapping):
            continue
        sources = record.get("sources")
        if not isinstance(sources, list):
            continue
        for source in sources:
            if isinstance(source, Mapping) and isinstance(source.get("source_id"), str):
                ids.add(str(source["source_id"]))
    return ids


def _semantic_documents(bundle: ProductionAnswerBundle) -> list[Any]:
    semantic_inputs = bundle.semantic_inputs or {}
    documents = semantic_inputs.get("documents")
    return documents if isinstance(documents, list) else []


def _source_ids(bundle: ProductionAnswerBundle) -> set[str]:
    ids: set[str] = set()
    for container in (bundle.document_source_index, bundle.source_documents):
        if not isinstance(container, Mapping):
            continue
        for key in ("sources", "documents"):
            rows = container.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, Mapping) and isinstance(row.get("source_id"), str):
                    ids.add(str(row["source_id"]))
    return ids


def _expected_counts(bundle: ProductionAnswerBundle) -> dict[str, Any]:
    counts = bundle.manifest.get("counts")
    if not isinstance(counts, Mapping):
        return {"observed": {}, "mismatches": ["counts_missing"]}
    expected = {
        "document_graph_nodes": FULL_PRODUCTION_NODE_COUNT,
        "document_graph_edges": FULL_PRODUCTION_EDGE_COUNT,
        "semantic_documents": FULL_PRODUCTION_SEMANTIC_POINT_COUNT,
    }
    mismatches = [
        key
        for key, value in expected.items()
        if counts.get(key) != value
    ]
    return {"observed": dict(counts), "mismatches": mismatches}


def _qdrant_payload_matches_production(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("release_id") == FULL_PRODUCTION_RELEASE_ID
        and payload.get("source_commit_sha") == FULL_PRODUCTION_SOURCE_SHA
        and payload.get("admission_sha256") == FULL_PRODUCTION_ADMISSION_SHA256
        and payload.get("candidate_release_eligible") is True
        and payload.get("production_authority") is False
    )


def _old_m24_concepts(root: Path) -> set[str]:
    path = root / "pilot/m24/canonical-release/artifacts/graph-v2.json"
    if not path.exists():
        return set()
    graph = json.loads(path.read_text(encoding="utf-8"))
    return _graph_v2_node_ids(graph)


def _qdrant_required_fields(root: Path | None) -> list[str]:
    if root is None:
        return [
            "section_id",
            "source_id",
            "release_id",
            "source_commit_sha",
            "admission_sha256",
            "candidate_release_eligible",
            "production_authority",
            "text_sha256",
        ]
    try:
        policy = load_json(root / POLICY_PATH)
        fields = policy["payload"]["required_fields"]
    except Exception:
        return []
    return [str(item) for item in fields] if isinstance(fields, list) else []


def _artifact_family_report(bundle: ProductionAnswerBundle) -> dict[str, Any]:
    mismatches: list[str] = []
    production = bundle.production_manifest
    if production is not None:
        production_artifacts = _artifact_by_kind(production)
        direct_artifacts = _artifact_by_kind(bundle.manifest)
        for kind in sorted(RUNTIME_REQUIRED_KINDS):
            if production_artifacts.get(kind, {}).get("sha256") != direct_artifacts.get(
                kind, {}
            ).get("sha256"):
                mismatches.append(kind)
    return {
        "direct_manifest_key": FULL_PRODUCTION_MANIFEST_KEY,
        "production_manifest_key": FULL_PRODUCTION_PROMOTION_MANIFEST_KEY,
        "runtime_required_kinds": sorted(RUNTIME_REQUIRED_KINDS),
        "compatibility_required_kinds": sorted(COMPATIBILITY_REQUIRED_KINDS),
        "mismatches": mismatches,
    }


def _promotion_manifest_sha(bundle: ProductionAnswerBundle) -> str | None:
    return bundle.production_manifest_sha256


def _pointer_sha(bundle: ProductionAnswerBundle) -> str | None:
    return bundle.production_pointer_sha256


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProductionAnswerBundleError(f"{label} must be a list")
    return value
