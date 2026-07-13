# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .errors import IntegrityError

SCHEMA_VERSION = "knowledge-os-graph/v2"
AUDIENCE_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
RENDERER_FIELDS = {"color", "coordinates", "hidden", "label_color", "size", "sigma_color", "x", "y"}


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _edge_id(source: str, target: str, relation_type: str, directed: bool, qualifiers: dict[str, str]) -> str:
    identity = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "target": target,
        "relation_type": relation_type,
        "directed": directed,
        "qualifiers": dict(sorted(qualifiers.items())),
    }
    return "edge_" + hashlib.sha256(_canonical_bytes(identity)).hexdigest()[:32]


def _profile(bundle_root: Path) -> dict[str, Any]:
    path = bundle_root / "_meta" / "graph-profile.json"
    if not path.is_file():
        return {"authoring_relation_types": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"invalid graph profile: {path}") from exc
    if not isinstance(value, dict):
        raise IntegrityError("graph profile must be an object")
    return value


def compile_graph_v2(
    concepts: list[dict[str, Any]],
    *,
    bundle_root: Path,
    release_id: str,
    source_commit_sha: str,
    foundation_commit_sha: str,
    content_sha256: str,
) -> dict[str, Any]:
    profile = _profile(bundle_root)
    relation_types = {
        item["type"]: item for item in profile.get("authoring_relation_types", [])
        if isinstance(item, dict) and isinstance(item.get("type"), str)
    }
    by_id = {item["concept_id"]: item for item in concepts}
    if len(by_id) != len(concepts):
        raise IntegrityError("duplicate graph v2 concept identity")

    alias_owners: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    for concept_id, item in sorted(by_id.items()):
        metadata = item["metadata"]
        forbidden = RENDERER_FIELDS.intersection(metadata)
        if forbidden:
            raise IntegrityError(f"renderer-specific concept fields: {sorted(forbidden)}")
        tags = metadata.get("tags") or []
        aliases = metadata.get("x-kos-aliases") or []
        if not isinstance(tags, list) or any(not isinstance(value, str) for value in tags):
            raise IntegrityError(f"{concept_id}: tags must be a string list")
        if not isinstance(aliases, list) or any(not isinstance(value, str) for value in aliases):
            raise IntegrityError(f"{concept_id}: aliases must be a string list")
        normalized_aliases = sorted({" ".join(value.casefold().strip().split()) for value in aliases})
        for alias in normalized_aliases:
            owner = alias_owners.get(alias)
            if not alias or (owner is not None and owner != concept_id):
                raise IntegrityError(f"ambiguous graph v2 alias: {alias!r}")
            alias_owners[alias] = concept_id
        nodes.append({
            "concept_id": concept_id,
            "x_kos_id": metadata["x-kos-id"],
            "title": metadata["title"],
            "description": metadata["description"],
            "type": metadata["type"],
            "audience": metadata["x-kos-audience"],
            "status": metadata["x-kos-status"],
            "confidence": metadata["x-kos-confidence"],
            "tags": sorted(set(tags)),
            "aliases": normalized_aliases,
            "path": item["path"].relative_to(bundle_root).as_posix(),
            "provenance_record": str(metadata["x-kos-provenance"]),
        })

    edges: list[dict[str, Any]] = []
    edge_ids: set[str] = set()
    for source_id, item in sorted(by_id.items()):
        source_metadata = item["metadata"]
        relations = source_metadata.get("x-kos-relations") or []
        if not isinstance(relations, list):
            raise IntegrityError(f"{source_id}: x-kos-relations must be a list")
        for relation in relations:
            if not isinstance(relation, dict) or RENDERER_FIELDS.intersection(relation):
                raise IntegrityError(f"{source_id}: invalid or renderer-specific relation")
            target_id = relation.get("target")
            target = by_id.get(target_id)
            if target is None:
                raise IntegrityError(f"{source_id}: missing relation target: {target_id}")
            definition = relation_types.get(relation.get("type"))
            if definition is None:
                raise IntegrityError(f"{source_id}: unknown authoring relation type")
            directed = relation.get("direction") == "directed"
            if directed != (definition.get("direction") == "directed"):
                raise IntegrityError(f"{source_id}: relation direction/profile mismatch")
            qualifiers = relation.get("qualifiers") or {}
            if not isinstance(qualifiers, dict):
                raise IntegrityError(f"{source_id}: qualifiers must be an object")
            audience = max(
                (source_metadata["x-kos-audience"], target["metadata"]["x-kos-audience"]),
                key=AUDIENCE_RANK.__getitem__,
            )
            provenance = relation.get("provenance") or {}
            review = relation.get("review") or {}
            edge = {
                "source": source_id,
                "target": target_id,
                "relation_type": relation["type"],
                "directed": directed,
                "audience": audience,
                "confidence": relation["confidence"],
                "qualifiers": dict(sorted(qualifiers.items())),
                "review_status": review.get("status"),
                "review_id": review.get("review_id"),
                "provenance_record": provenance.get("record"),
                "provenance_ref": provenance.get("claim_id") or provenance.get("structural_basis"),
                "generated_inverse": False,
            }
            edge["edge_id"] = _edge_id(source_id, target_id, relation["type"], directed, edge["qualifiers"])
            if edge["edge_id"] in edge_ids:
                raise IntegrityError(f"duplicate graph v2 edge: {edge['edge_id']}")
            edge_ids.add(edge["edge_id"])
            edges.append(edge)
            inverse_type = definition["inverse"]
            if directed:
                inverse = dict(edge)
                inverse.update({
                    "source": target_id,
                    "target": source_id,
                    "relation_type": inverse_type,
                    "generated_inverse": True,
                })
                inverse["edge_id"] = _edge_id(target_id, source_id, inverse_type, True, inverse["qualifiers"])
                if inverse["edge_id"] in edge_ids:
                    raise IntegrityError(f"duplicate graph v2 inverse edge: {inverse['edge_id']}")
                edge_ids.add(inverse["edge_id"])
                edges.append(inverse)

    return {
        "schema_version": SCHEMA_VERSION,
        "release": {
            "release_id": release_id,
            "source_commit_sha": source_commit_sha,
            "foundation_commit_sha": foundation_commit_sha,
            "content_sha256": content_sha256,
        },
        "nodes": nodes,
        "edges": sorted(edges, key=lambda item: item["edge_id"]),
        "generic_edges_artifact": "graph.json",
        "renderer_neutral": True,
    }
