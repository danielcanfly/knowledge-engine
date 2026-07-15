import type { ExplorerGraph } from "./index.js";

export const CANDIDATE_EXPLORER_SCHEMA = "knowledge-engine-m23-candidate-explorer-overlay/v1";
export const CANDIDATE_MODEL_SCHEMA = "knowledge-engine-m23-candidate-explorer-model/v1";
export const SEMANTIC_OVERLAY_SCHEMA = "knowledge-engine-m23-semantic-neighborhood-overlay/v1";
export const MAX_SEMANTIC_NEIGHBORS = 20;

export interface CandidateExplorerOverlay {
  schema_version: typeof CANDIDATE_EXPLORER_SCHEMA;
  candidate_release_id: string;
  candidate_release_manifest_sha256: string;
  graph_api_payload_sha256: string;
  semantic_anchor_map_sha256: string;
  view_mode: "candidate-preview";
  label: string;
  warning: string;
  feature_flag: "GRAPH_EXPLORER_ENABLED";
  feature_flag_default: false;
  internal_only: true;
  read_only: true;
  node_count: number;
  typed_edge_count: number;
  semantic_section_count: number;
  semantic_anchor_counts: Record<string, number>;
  semantic_edge_count: 0;
  typed_graph_and_semantic_overlay_conflated: false;
  node_level_semantic_counts_claimed: false;
  production_authority: false;
}

export interface CandidateSemanticMapping {
  candidate_id: string;
  semantic_anchor_graph_node_id: string;
  anchor_point_count: number;
  mapping_basis: "evidence-derivative-part";
  per_concept_section_attribution_available: false;
}

export interface CandidateExplorerNodeDescriptor {
  candidateId: string;
  title: string;
  semanticAnchorGraphNodeId: string;
  anchorPointCount: number;
  semanticEvidenceScope: "anchor-shared-not-node-attributed";
  pendingHumanReview: true;
  canonicalKnowledge: false;
  productionAuthority: false;
}

export interface CandidateExplorerModel {
  schemaVersion: typeof CANDIDATE_MODEL_SCHEMA;
  releaseId: string;
  manifestSha256: string;
  label: string;
  warning: string;
  viewMode: "candidate-preview";
  internalOnly: true;
  readOnly: true;
  featureFlag: "GRAPH_EXPLORER_ENABLED";
  featureFlagDefault: false;
  nodeCount: number;
  typedEdgeCount: number;
  semanticSectionCount: number;
  semanticEdgeCount: 0;
  typedGraphAndSemanticOverlayConflated: false;
  nodes: CandidateExplorerNodeDescriptor[];
}

export interface SemanticNeighborInput {
  candidateId: string;
  semanticAnchorGraphNodeId: string;
  score: number;
}

export interface SemanticNeighborOverlayEdge {
  overlayId: string;
  focusCandidateId: string;
  candidateId: string;
  semanticAnchorGraphNodeId: string;
  score: number;
  kind: "semantic-neighbor";
  rendererOnly: true;
  typedRelationship: false;
  readOnly: true;
}

export interface SemanticNeighborhoodOverlay {
  schemaVersion: typeof SEMANTIC_OVERLAY_SCHEMA;
  releaseId: string;
  manifestSha256: string;
  focusCandidateId: string;
  edges: SemanticNeighborOverlayEdge[];
  typedGraphMutated: false;
  semanticEdgesMaterialized: false;
  readOnly: true;
}

function requiredString(value: unknown, label: string, maximum = 500): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maximum) {
    throw new TypeError(`${label} must be a non-empty string of at most ${maximum} characters`);
  }
  return value;
}

function requiredSha256(value: unknown, label: string): string {
  const text = requiredString(value, label, 64);
  if (!/^[0-9a-f]{64}$/.test(text)) throw new TypeError(`${label} must be a lowercase sha256`);
  return text;
}

function graphReleaseIdentity(graph: ExplorerGraph): { releaseId: string; manifestSha256: string } {
  if (graph.getAttribute("readOnly") !== true) {
    throw new TypeError("candidate Explorer accepts only a read-only graph");
  }
  if (graph.getAttribute("rendererNeutral") !== true) {
    throw new TypeError("candidate Explorer accepts only a renderer-neutral graph");
  }
  return {
    releaseId: requiredString(graph.getAttribute("releaseId"), "graph.releaseId"),
    manifestSha256: requiredSha256(graph.getAttribute("manifestSha256"), "graph.manifestSha256"),
  };
}

function boundedCount(value: unknown, label: string, maximum: number): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > maximum) {
    throw new TypeError(`${label} is outside the bounded range`);
  }
  return value as number;
}

function validateOverlay(graph: ExplorerGraph, overlay: CandidateExplorerOverlay): void {
  const release = graphReleaseIdentity(graph);
  if (overlay.schema_version !== CANDIDATE_EXPLORER_SCHEMA) {
    throw new TypeError("unsupported candidate Explorer overlay schema");
  }
  if (
    overlay.candidate_release_id !== release.releaseId ||
    overlay.candidate_release_manifest_sha256 !== release.manifestSha256
  ) {
    throw new TypeError("candidate Explorer release identity mismatch");
  }
  if (
    overlay.view_mode !== "candidate-preview" ||
    overlay.internal_only !== true ||
    overlay.read_only !== true ||
    overlay.production_authority !== false
  ) {
    throw new TypeError("candidate Explorer authority boundary drift");
  }
  if (
    overlay.feature_flag !== "GRAPH_EXPLORER_ENABLED" ||
    overlay.feature_flag_default !== false
  ) {
    throw new TypeError("candidate Explorer feature flag must default false");
  }
  if (
    overlay.typed_graph_and_semantic_overlay_conflated !== false ||
    overlay.semantic_edge_count !== 0
  ) {
    throw new TypeError("typed graph and semantic overlay cannot be conflated");
  }
  if (overlay.node_level_semantic_counts_claimed !== false) {
    throw new TypeError("node-level semantic counts are not evidenced");
  }
  if (overlay.node_count !== graph.order || overlay.typed_edge_count !== graph.size) {
    throw new TypeError("candidate Explorer graph counts mismatch");
  }
  boundedCount(overlay.semantic_section_count, "semantic_section_count", 100_000);
  requiredString(overlay.label, "overlay.label", 200);
  requiredString(overlay.warning, "overlay.warning", 500);
  requiredSha256(overlay.graph_api_payload_sha256, "graph_api_payload_sha256");
  requiredSha256(overlay.semantic_anchor_map_sha256, "semantic_anchor_map_sha256");
  const anchorEntries = Object.entries(overlay.semantic_anchor_counts);
  if (anchorEntries.length === 0 || anchorEntries.length > 100) {
    throw new TypeError("candidate Explorer semantic anchors are invalid");
  }
  const total = anchorEntries.reduce((sum, [anchor, count]) => {
    requiredString(anchor, "semantic anchor", 300);
    return sum + boundedCount(count, "semantic anchor count", 100_000);
  }, 0);
  if (total !== overlay.semantic_section_count) {
    throw new TypeError("candidate Explorer semantic anchor total mismatch");
  }
}

export function createCandidateExplorerModel(
  graph: ExplorerGraph,
  overlay: CandidateExplorerOverlay,
  mappings: readonly CandidateSemanticMapping[],
): CandidateExplorerModel {
  validateOverlay(graph, overlay);
  if (mappings.length !== graph.order) {
    throw new TypeError("candidate semantic mapping count mismatch");
  }
  const seen = new Set<string>();
  const descriptors: CandidateExplorerNodeDescriptor[] = [];
  for (const mapping of mappings) {
    const candidateId = requiredString(mapping.candidate_id, "mapping.candidate_id");
    const anchor = requiredString(
      mapping.semantic_anchor_graph_node_id,
      "mapping.semantic_anchor_graph_node_id",
    );
    if (seen.has(candidateId) || !graph.hasNode(candidateId)) {
      throw new TypeError("candidate semantic mapping identity mismatch");
    }
    seen.add(candidateId);
    if (mapping.mapping_basis !== "evidence-derivative-part") {
      throw new TypeError("candidate semantic mapping basis mismatch");
    }
    if (mapping.per_concept_section_attribution_available !== false) {
      throw new TypeError("per-concept semantic attribution must not be claimed");
    }
    const expectedAnchorCount = overlay.semantic_anchor_counts[anchor];
    if (expectedAnchorCount === undefined || mapping.anchor_point_count !== expectedAnchorCount) {
      throw new TypeError("candidate semantic anchor count mismatch");
    }
    descriptors.push({
      candidateId,
      title: requiredString(graph.getNodeAttribute(candidateId, "title"), "node.title", 300),
      semanticAnchorGraphNodeId: anchor,
      anchorPointCount: expectedAnchorCount,
      semanticEvidenceScope: "anchor-shared-not-node-attributed",
      pendingHumanReview: true,
      canonicalKnowledge: false,
      productionAuthority: false,
    });
  }
  if (seen.size !== graph.order) throw new TypeError("candidate semantic mapping coverage mismatch");
  descriptors.sort((left, right) => left.candidateId.localeCompare(right.candidateId));
  const release = graphReleaseIdentity(graph);
  return {
    schemaVersion: CANDIDATE_MODEL_SCHEMA,
    releaseId: release.releaseId,
    manifestSha256: release.manifestSha256,
    label: overlay.label,
    warning: overlay.warning,
    viewMode: "candidate-preview",
    internalOnly: true,
    readOnly: true,
    featureFlag: "GRAPH_EXPLORER_ENABLED",
    featureFlagDefault: false,
    nodeCount: graph.order,
    typedEdgeCount: graph.size,
    semanticSectionCount: overlay.semantic_section_count,
    semanticEdgeCount: 0,
    typedGraphAndSemanticOverlayConflated: false,
    nodes: descriptors,
  };
}

export function createSemanticNeighborhoodOverlay(
  graph: ExplorerGraph,
  focusCandidateId: string,
  neighbors: readonly SemanticNeighborInput[],
): SemanticNeighborhoodOverlay {
  const release = graphReleaseIdentity(graph);
  const focus = requiredString(focusCandidateId, "focusCandidateId");
  if (!graph.hasNode(focus)) throw new TypeError("focus candidate is outside the ACL-safe graph");
  if (neighbors.length > MAX_SEMANTIC_NEIGHBORS) {
    throw new TypeError(`semantic overlay supports at most ${MAX_SEMANTIC_NEIGHBORS} neighbors`);
  }
  const seen = new Set<string>();
  const edges: SemanticNeighborOverlayEdge[] = [];
  for (const neighbor of neighbors) {
    const candidateId = requiredString(neighbor.candidateId, "neighbor.candidateId");
    const anchor = requiredString(
      neighbor.semanticAnchorGraphNodeId,
      "neighbor.semanticAnchorGraphNodeId",
    );
    if (candidateId === focus || seen.has(candidateId) || !graph.hasNode(candidateId)) {
      throw new TypeError("semantic neighbor identity is invalid or duplicated");
    }
    if (
      typeof neighbor.score !== "number" ||
      !Number.isFinite(neighbor.score) ||
      neighbor.score < -1 ||
      neighbor.score > 1
    ) {
      throw new TypeError("semantic neighbor score is outside cosine bounds");
    }
    seen.add(candidateId);
    edges.push({
      overlayId: `semantic:${focus}:${candidateId}`,
      focusCandidateId: focus,
      candidateId,
      semanticAnchorGraphNodeId: anchor,
      score: neighbor.score,
      kind: "semantic-neighbor",
      rendererOnly: true,
      typedRelationship: false,
      readOnly: true,
    });
  }
  edges.sort((left, right) => right.score - left.score || left.candidateId.localeCompare(right.candidateId));
  return {
    schemaVersion: SEMANTIC_OVERLAY_SCHEMA,
    releaseId: release.releaseId,
    manifestSha256: release.manifestSha256,
    focusCandidateId: focus,
    edges,
    typedGraphMutated: false,
    semanticEdgesMaterialized: false,
    readOnly: true,
  };
}
