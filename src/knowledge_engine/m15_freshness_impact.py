from __future__ import annotations

import hashlib
import json
from collections import deque
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

M15_FRESHNESS_IMPACT_SCHEMA = "knowledge-engine-freshness-impact/v1"
MAX_NODES = 10000
MAX_EDGES = 50000


class Audience(StrEnum):
    PRIVATE = "private"
    INTERNAL = "internal"
    PUBLIC = "public"


class NodeKind(StrEnum):
    SOURCE_FACT = "source_fact"
    CONCEPT = "concept"
    PAGE = "page"
    INDEX = "index"
    RELEASE = "release"
    CACHE = "cache"
    PUBLIC_SURFACE = "public_surface"


class EdgeKind(StrEnum):
    DERIVES = "derives"
    REFERENCES = "references"
    MATERIALIZES = "materializes"
    PUBLISHES = "publishes"
    CACHES = "caches"


class ImpactState(StrEnum):
    DIRECT = "direct"
    TRANSITIVE = "transitive"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    UNAFFECTED = "unaffected"


class ImpactReason(StrEnum):
    CHANGED_SOURCE = "changed_source"
    DEPENDENCY = "dependency"
    AUDIENCE_BOUNDARY = "audience_boundary"
    DEPTH_LIMIT = "depth_limit"
    CYCLE = "cycle"
    IDENTITY_DRIFT = "identity_drift"


_AUDIENCE_RANK = {Audience.PRIVATE: 0, Audience.INTERNAL: 1, Audience.PUBLIC: 2}


class ImpactNode(BaseModel):
    node_id: str = Field(min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9._:-]+$")
    kind: NodeKind
    audience: Audience
    engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    expected_engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class ImpactEdge(BaseModel):
    source_id: str
    target_id: str
    kind: EdgeKind


class ImpactGraph(BaseModel):
    nodes: list[ImpactNode]
    edges: list[ImpactEdge]

    @model_validator(mode="after")
    def validate_graph(self) -> "ImpactGraph":
        if len(self.nodes) > MAX_NODES or len(self.edges) > MAX_EDGES:
            raise ValueError("freshness graph exceeds bounded limits")
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate freshness node_id")
        known = set(ids)
        for edge in self.edges:
            if edge.source_id not in known or edge.target_id not in known:
                raise ValueError("freshness edge references unknown node")
        return self


class ImpactRecord(BaseModel):
    node_id: str
    state: ImpactState
    reason: ImpactReason
    depth: int = Field(ge=0)


class FreshnessImpactReport(BaseModel):
    schema_version: str = M15_FRESHNESS_IMPACT_SCHEMA
    changed_node_ids: list[str]
    impacts: list[ImpactRecord]
    cycle_detected: bool
    truncated: bool
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class FreshnessAuthority(BaseModel):
    source_write_allowed: bool = False
    candidate_creation_allowed: bool = False
    release_rebuild_allowed: bool = False
    cache_purge_allowed: bool = False
    production_write_allowed: bool = False
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def reject_authority(self) -> "FreshnessAuthority":
        enabled = sorted(name for name, value in self.model_dump().items() if value)
        if enabled:
            raise ValueError(f"M15.5 is advisory-only; authority enabled: {enabled}")
        return self


def evaluate_freshness_impact(
    graph: ImpactGraph,
    *,
    changed_node_ids: list[str],
    max_depth: int = 8,
) -> FreshnessImpactReport:
    if max_depth < 0 or max_depth > 64:
        raise ValueError("max_depth must be between 0 and 64")
    nodes = {node.node_id: node for node in graph.nodes}
    missing = sorted(set(changed_node_ids) - set(nodes))
    if missing:
        raise ValueError(f"unknown changed nodes: {missing}")
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in graph.edges:
        adjacency[edge.source_id].append(edge.target_id)
    for values in adjacency.values():
        values.sort()

    records: dict[tuple[str, ImpactState, ImpactReason], ImpactRecord] = {}
    queue: deque[tuple[str, int, tuple[str, ...]]] = deque()
    cycle_detected = False
    truncated = False

    for node_id in sorted(set(changed_node_ids)):
        node = nodes[node_id]
        reason = ImpactReason.IDENTITY_DRIFT if node.engine_sha != node.expected_engine_sha else ImpactReason.CHANGED_SOURCE
        state = ImpactState.UNKNOWN if reason == ImpactReason.IDENTITY_DRIFT else ImpactState.DIRECT
        records[(node_id, state, reason)] = ImpactRecord(node_id=node_id, state=state, reason=reason, depth=0)
        queue.append((node_id, 0, (node_id,)))

    while queue:
        source_id, depth, path = queue.popleft()
        for target_id in adjacency[source_id]:
            target = nodes[target_id]
            source = nodes[source_id]
            if target_id in path:
                cycle_detected = True
                records[(target_id, ImpactState.UNKNOWN, ImpactReason.CYCLE)] = ImpactRecord(
                    node_id=target_id, state=ImpactState.UNKNOWN, reason=ImpactReason.CYCLE, depth=depth + 1
                )
                continue
            if _AUDIENCE_RANK[target.audience] > _AUDIENCE_RANK[source.audience]:
                records[(target_id, ImpactState.BLOCKED, ImpactReason.AUDIENCE_BOUNDARY)] = ImpactRecord(
                    node_id=target_id,
                    state=ImpactState.BLOCKED,
                    reason=ImpactReason.AUDIENCE_BOUNDARY,
                    depth=depth + 1,
                )
                continue
            if depth + 1 > max_depth:
                truncated = True
                records[(target_id, ImpactState.UNKNOWN, ImpactReason.DEPTH_LIMIT)] = ImpactRecord(
                    node_id=target_id,
                    state=ImpactState.UNKNOWN,
                    reason=ImpactReason.DEPTH_LIMIT,
                    depth=depth + 1,
                )
                continue
            if target.engine_sha != target.expected_engine_sha:
                records[(target_id, ImpactState.UNKNOWN, ImpactReason.IDENTITY_DRIFT)] = ImpactRecord(
                    node_id=target_id,
                    state=ImpactState.UNKNOWN,
                    reason=ImpactReason.IDENTITY_DRIFT,
                    depth=depth + 1,
                )
                continue
            key = (target_id, ImpactState.TRANSITIVE, ImpactReason.DEPENDENCY)
            prior = records.get(key)
            if prior is None or depth + 1 < prior.depth:
                records[key] = ImpactRecord(
                    node_id=target_id,
                    state=ImpactState.TRANSITIVE,
                    reason=ImpactReason.DEPENDENCY,
                    depth=depth + 1,
                )
                queue.append((target_id, depth + 1, (*path, target_id)))

    impacts = sorted(records.values(), key=lambda item: (item.node_id, item.depth, item.state.value, item.reason.value))
    report = FreshnessImpactReport(
        changed_node_ids=sorted(set(changed_node_ids)),
        impacts=impacts,
        cycle_detected=cycle_detected,
        truncated=truncated,
    )
    return finalize_freshness_report(report)


def freshness_report_sha256(report: FreshnessImpactReport) -> str:
    payload = report.model_dump(mode="json")
    payload["artifact_sha256"] = None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def finalize_freshness_report(report: FreshnessImpactReport) -> FreshnessImpactReport:
    digest = freshness_report_sha256(report)
    if report.artifact_sha256 not in {None, digest}:
        raise ValueError("freshness impact report digest mismatch")
    return report.model_copy(update={"artifact_sha256": digest})
