import type { ExplorerGraph } from "./index.js";

export const EXPLORER_SCALE_SCHEMA = "knowledge-os-explorer-scale/v1";
export const EXPLORER_LAYOUT_SCHEMA = "knowledge-os-graph-layout/v1";
export const EXPLORER_OVERVIEW_SCHEMA = "knowledge-os-graph-overview/v1";
export const LAYOUT_ALGORITHM_NAME = "knowledge-os-deterministic-hash-ring";
export const LAYOUT_ALGORITHM_VERSION = "1.0.0";
export const DEFAULT_LAYOUT_SEED = 1906;
export const MAX_SCALE_NODES = 50_000;
export const MAX_SCALE_EDGES = 250_000;
export const MAX_OVERVIEW_CLUSTERS = 500;
export const MAX_OVERVIEW_EDGES = 2_000;
export const MAX_PROGRESSIVE_BATCH_NODES = 500;
export const MAX_PROGRESSIVE_BATCH_EDGES = 1_000;
export const MAX_PROGRESSIVE_DEPTH = 2;

export interface ScaleReleaseIdentity {
  releaseId: string;
  manifestSha256?: string;
  sourceCommitSha?: string;
  foundationCommitSha?: string;
  contentSha256?: string;
}

export interface LayoutPosition {
  nodeId: string;
  x: number;
  y: number;
}

export interface GraphLayoutArtifact {
  schemaVersion: typeof EXPLORER_LAYOUT_SCHEMA;
  release: ScaleReleaseIdentity;
  algorithm: {
    name: typeof LAYOUT_ALGORITHM_NAME;
    version: typeof LAYOUT_ALGORITHM_VERSION;
    seed: number;
  };
  nodeCount: number;
  edgeCount: number;
  positions: LayoutPosition[];
  readOnly: true;
}

export interface LayoutOptions {
  seed?: number;
}

export interface OverviewCluster {
  clusterId: string;
  label: string;
  representativeNodeId: string;
  memberCount: number;
  x: number;
  y: number;
}

export interface OverviewEdge {
  edgeId: string;
  sourceClusterId: string;
  targetClusterId: string;
  directed: boolean;
  weight: number;
  relationTypes: string[];
}

export interface GraphOverviewArtifact {
  schemaVersion: typeof EXPLORER_OVERVIEW_SCHEMA;
  release: ScaleReleaseIdentity;
  layoutAlgorithm: GraphLayoutArtifact["algorithm"];
  sourceNodeCount: number;
  sourceEdgeCount: number;
  clusters: OverviewCluster[];
  edges: OverviewEdge[];
  suppressedNodeCount: number;
  suppressedEdgeCount: number;
  readOnly: true;
}

export interface OverviewOptions {
  maxClusters?: number;
  maxEdges?: number;
}

export type SemanticZoomMode = "overview" | "context" | "detail";

export interface SemanticZoomPolicy {
  mode: SemanticZoomMode;
  useOverviewArtifact: boolean;
  nodeLabelBudget: number;
  edgeBudget: number;
  labels: "selected-only" | "representatives" | "bounded";
  showEdgeLabels: boolean;
}

export interface SemanticZoomInput {
  cameraRatio: number;
  nodeCount: number;
  selected: boolean;
}

export interface ProgressiveExpansionOptions {
  rootNodeId: string;
  depth?: 1 | 2;
  batchNodeLimit?: number;
  batchEdgeLimit?: number;
  relationTypes?: string[];
  cursor?: string;
}

export interface ProgressiveExpansionPage {
  schemaVersion: typeof EXPLORER_SCALE_SCHEMA;
  release: ScaleReleaseIdentity;
  rootNodeId: string;
  depth: 1 | 2;
  nodeIds: string[];
  edgeIds: string[];
  loadedNodeCount: number;
  loadedEdgeCount: number;
  complete: boolean;
  nextCursor: string | null;
  readOnly: true;
}

export type PerformanceTierName = "1k" | "10k" | "50k";

export interface PerformanceBudget {
  tier: PerformanceTierName;
  nodeCount: number;
  maxEdgeCount: number;
  maxPayloadBytes: number;
  maxParseMs: number;
  maxImportMs: number;
  maxLayoutMs: number;
  maxOverviewMs: number;
  maxFirstMeaningfulRenderMs: number;
  maxPanZoomP95Ms: number;
  maxSelectionP95Ms: number;
  maxNeighborhoodP95Ms: number;
  maxMemoryMiB: number;
  minLabelSuppressionRatio: number;
  minEdgeReductionRatio: number;
}

export interface PerformanceSample {
  tier: PerformanceTierName;
  nodeCount: number;
  edgeCount: number;
  payloadBytes: number;
  parseMs: number;
  importMs: number;
  layoutMs: number;
  overviewMs: number;
  firstMeaningfulRenderMs: number;
  panZoomP95Ms: number;
  selectionP95Ms: number;
  neighborhoodP95Ms: number;
  memoryMiB: number;
  labelSuppressionRatio: number;
  edgeReductionRatio: number;
}

export const PERFORMANCE_BUDGETS: Readonly<Record<PerformanceTierName, PerformanceBudget>> = {
  "1k": {
    tier: "1k",
    nodeCount: 1_000,
    maxEdgeCount: 10_000,
    maxPayloadBytes: 4_000_000,
    maxParseMs: 250,
    maxImportMs: 750,
    maxLayoutMs: 750,
    maxOverviewMs: 750,
    maxFirstMeaningfulRenderMs: 1_500,
    maxPanZoomP95Ms: 32,
    maxSelectionP95Ms: 50,
    maxNeighborhoodP95Ms: 100,
    maxMemoryMiB: 256,
    minLabelSuppressionRatio: 0.8,
    minEdgeReductionRatio: 0.5,
  },
  "10k": {
    tier: "10k",
    nodeCount: 10_000,
    maxEdgeCount: 80_000,
    maxPayloadBytes: 24_000_000,
    maxParseMs: 1_000,
    maxImportMs: 3_000,
    maxLayoutMs: 3_000,
    maxOverviewMs: 3_000,
    maxFirstMeaningfulRenderMs: 4_000,
    maxPanZoomP95Ms: 50,
    maxSelectionP95Ms: 75,
    maxNeighborhoodP95Ms: 150,
    maxMemoryMiB: 768,
    minLabelSuppressionRatio: 0.95,
    minEdgeReductionRatio: 0.75,
  },
  "50k": {
    tier: "50k",
    nodeCount: 50_000,
    maxEdgeCount: 250_000,
    maxPayloadBytes: 96_000_000,
    maxParseMs: 4_000,
    maxImportMs: 12_000,
    maxLayoutMs: 12_000,
    maxOverviewMs: 12_000,
    maxFirstMeaningfulRenderMs: 8_000,
    maxPanZoomP95Ms: 75,
    maxSelectionP95Ms: 100,
    maxNeighborhoodP95Ms: 250,
    maxMemoryMiB: 2_048,
    minLabelSuppressionRatio: 0.985,
    minEdgeReductionRatio: 0.9,
  },
};

function requiredString(value: unknown, label: string, maximum = 300): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maximum) {
    throw new TypeError(`${label} must be a non-empty string of at most ${maximum} characters`);
  }
  return value;
}

function optionalGraphString(graph: ExplorerGraph, name: string): string | undefined {
  const value = graph.getAttribute(name);
  if (value === undefined || value === null) return undefined;
  return requiredString(value, `graph.${name}`);
}

function releaseIdentity(graph: ExplorerGraph): ScaleReleaseIdentity {
  if (graph.getAttribute("readOnly") !== true) {
    throw new TypeError("scale strategy accepts only a read-only graph");
  }
  if (graph.getAttribute("rendererNeutral") !== true) {
    throw new TypeError("scale strategy accepts only a renderer-neutral graph");
  }
  if (graph.order > MAX_SCALE_NODES) {
    throw new TypeError(`scale strategy supports at most ${MAX_SCALE_NODES} nodes`);
  }
  if (graph.size > MAX_SCALE_EDGES) {
    throw new TypeError(`scale strategy supports at most ${MAX_SCALE_EDGES} edges`);
  }
  const manifestSha256 = optionalGraphString(graph, "manifestSha256");
  const sourceCommitSha = optionalGraphString(graph, "sourceCommitSha");
  const foundationCommitSha = optionalGraphString(graph, "foundationCommitSha");
  const contentSha256 = optionalGraphString(graph, "contentSha256");
  return {
    releaseId: requiredString(graph.getAttribute("releaseId"), "graph.releaseId"),
    ...(manifestSha256 !== undefined ? { manifestSha256 } : {}),
    ...(sourceCommitSha !== undefined ? { sourceCommitSha } : {}),
    ...(foundationCommitSha !== undefined ? { foundationCommitSha } : {}),
    ...(contentSha256 !== undefined ? { contentSha256 } : {}),
  };
}

function validateIdentity(actual: ScaleReleaseIdentity, supplied: ScaleReleaseIdentity): void {
  const fields: Array<keyof ScaleReleaseIdentity> = [
    "releaseId",
    "manifestSha256",
    "sourceCommitSha",
    "foundationCommitSha",
    "contentSha256",
  ];
  for (const field of fields) {
    if (actual[field] !== supplied[field]) {
      throw new TypeError(`scale ${field} identity mismatch`);
    }
  }
}

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function round6(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
}

function finiteSeed(value: number | undefined): number {
  const seed = value ?? DEFAULT_LAYOUT_SEED;
  if (!Number.isSafeInteger(seed) || seed < 0 || seed > 0xffffffff) {
    throw new TypeError("layout seed must be an unsigned 32-bit integer");
  }
  return seed;
}

export function createDeterministicLayout(
  graph: ExplorerGraph,
  options: LayoutOptions = {},
): GraphLayoutArtifact {
  const release = releaseIdentity(graph);
  const seed = finiteSeed(options.seed);
  const nodeIds = graph.nodes().sort();
  const scale = Math.max(1, Math.sqrt(nodeIds.length));
  const positions = nodeIds.map((nodeId, index): LayoutPosition => {
    const angleHash = stableHash(`${seed}:${nodeId}:angle`);
    const radiusHash = stableHash(`${seed}:${nodeId}:radius`);
    const angle = (angleHash / 0xffffffff) * Math.PI * 2;
    const radialBand = 0.25 + (radiusHash / 0xffffffff) * 0.75;
    const indexBand = 0.75 + (index % 97) / 388;
    const radius = scale * radialBand * indexBand;
    return {
      nodeId,
      x: round6(Math.cos(angle) * radius),
      y: round6(Math.sin(angle) * radius),
    };
  });
  return {
    schemaVersion: EXPLORER_LAYOUT_SCHEMA,
    release,
    algorithm: {
      name: LAYOUT_ALGORITHM_NAME,
      version: LAYOUT_ALGORITHM_VERSION,
      seed,
    },
    nodeCount: graph.order,
    edgeCount: graph.size,
    positions,
    readOnly: true,
  };
}

function validateLayout(graph: ExplorerGraph, layout: GraphLayoutArtifact): Map<string, LayoutPosition> {
  const release = releaseIdentity(graph);
  if (layout.schemaVersion !== EXPLORER_LAYOUT_SCHEMA || layout.readOnly !== true) {
    throw new TypeError("unsupported or mutable graph layout artifact");
  }
  validateIdentity(release, layout.release);
  if (
    layout.algorithm.name !== LAYOUT_ALGORITHM_NAME ||
    layout.algorithm.version !== LAYOUT_ALGORITHM_VERSION
  ) {
    throw new TypeError("layout algorithm identity mismatch");
  }
  finiteSeed(layout.algorithm.seed);
  if (layout.nodeCount !== graph.order || layout.edgeCount !== graph.size) {
    throw new TypeError("layout graph counts mismatch");
  }
  if (!Array.isArray(layout.positions) || layout.positions.length !== graph.order) {
    throw new TypeError("layout must contain exactly one position per graph node");
  }
  const positions = new Map<string, LayoutPosition>();
  for (const item of layout.positions) {
    const nodeId = requiredString(item?.nodeId, "layout position nodeId");
    if (!graph.hasNode(nodeId)) throw new TypeError("layout position is outside the ACL-safe graph");
    if (positions.has(nodeId)) throw new TypeError("layout contains duplicate node positions");
    if (!Number.isFinite(item.x) || !Number.isFinite(item.y)) {
      throw new TypeError("layout coordinates must be finite");
    }
    positions.set(nodeId, { nodeId, x: item.x, y: item.y });
  }
  return positions;
}

function normalized(value: string): string {
  return value.normalize("NFKC").trim().toLocaleLowerCase("en-US");
}

function graphStrings(value: unknown, maximum: number): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === "string")
    .slice(0, maximum)
    .map(normalized)
    .filter((item) => item.length > 0)
    .sort();
}

function rawClusterKey(graph: ExplorerGraph, nodeId: string): string {
  const tags = graphStrings(graph.getNodeAttribute(nodeId, "tags"), 100);
  if (tags[0] !== undefined) return `tag:${tags[0]}`;
  const typeValue = graph.getNodeAttribute(nodeId, "type");
  const type = typeof typeValue === "string" ? normalized(typeValue) : "unknown";
  return `type:${type || "unknown"}`;
}

function boundedInteger(
  value: number | undefined,
  fallback: number,
  maximum: number,
  label: string,
): number {
  const result = value ?? fallback;
  if (!Number.isSafeInteger(result) || result < 1 || result > maximum) {
    throw new TypeError(`${label} must be an integer between 1 and ${maximum}`);
  }
  return result;
}

interface ClusterAccumulator {
  memberIds: string[];
  sumX: number;
  sumY: number;
}

export function createOverviewArtifact(
  graph: ExplorerGraph,
  layout: GraphLayoutArtifact,
  options: OverviewOptions = {},
): GraphOverviewArtifact {
  const release = releaseIdentity(graph);
  const positions = validateLayout(graph, layout);
  const maxClusters = boundedInteger(
    options.maxClusters,
    200,
    MAX_OVERVIEW_CLUSTERS,
    "maxClusters",
  );
  const maxEdges = boundedInteger(options.maxEdges, 800, MAX_OVERVIEW_EDGES, "maxEdges");
  const rawMembers = new Map<string, string[]>();
  for (const nodeId of graph.nodes().sort()) {
    const key = rawClusterKey(graph, nodeId);
    const members = rawMembers.get(key) ?? [];
    members.push(nodeId);
    rawMembers.set(key, members);
  }
  const rankedKeys = [...rawMembers.entries()]
    .sort((left, right) => right[1].length - left[1].length || left[0].localeCompare(right[0]))
    .map(([key]) => key);
  const retained = new Set(
    rankedKeys.slice(0, rawMembers.size > maxClusters ? Math.max(1, maxClusters - 1) : maxClusters),
  );
  const nodeToCluster = new Map<string, string>();
  const accumulators = new Map<string, ClusterAccumulator>();
  for (const [rawKey, memberIds] of rawMembers) {
    const key = retained.has(rawKey) ? rawKey : "other";
    const clusterId = `cluster:${key}`;
    const accumulator = accumulators.get(clusterId) ?? { memberIds: [], sumX: 0, sumY: 0 };
    for (const nodeId of memberIds) {
      const position = positions.get(nodeId);
      if (position === undefined) throw new TypeError("layout position missing during overview");
      nodeToCluster.set(nodeId, clusterId);
      accumulator.memberIds.push(nodeId);
      accumulator.sumX += position.x;
      accumulator.sumY += position.y;
    }
    accumulators.set(clusterId, accumulator);
  }
  const clusters = [...accumulators.entries()]
    .map(([clusterId, accumulator]): OverviewCluster => {
      const representativeNodeId = [...accumulator.memberIds].sort((left, right) => {
        const degreeDifference = graph.degree(right) - graph.degree(left);
        return degreeDifference || left.localeCompare(right);
      })[0];
      if (representativeNodeId === undefined) throw new TypeError("overview cluster is empty");
      const rawLabel = clusterId.slice("cluster:".length);
      return {
        clusterId,
        label: rawLabel === "other" ? "Other" : rawLabel.slice(rawLabel.indexOf(":") + 1),
        representativeNodeId,
        memberCount: accumulator.memberIds.length,
        x: round6(accumulator.sumX / accumulator.memberIds.length),
        y: round6(accumulator.sumY / accumulator.memberIds.length),
      };
    })
    .sort((left, right) => left.clusterId.localeCompare(right.clusterId));

  interface EdgeAccumulator {
    sourceClusterId: string;
    targetClusterId: string;
    directed: boolean;
    weight: number;
    relationTypes: Set<string>;
  }
  const aggregateEdges = new Map<string, EdgeAccumulator>();
  for (const edgeId of graph.edges().sort()) {
    const sourceNode = graph.source(edgeId);
    const targetNode = graph.target(edgeId);
    let sourceClusterId = nodeToCluster.get(sourceNode);
    let targetClusterId = nodeToCluster.get(targetNode);
    if (sourceClusterId === undefined || targetClusterId === undefined) {
      throw new TypeError("overview edge endpoint is outside a cluster");
    }
    if (sourceClusterId === targetClusterId) continue;
    const directed = graph.isDirected(edgeId);
    if (!directed && sourceClusterId > targetClusterId) {
      [sourceClusterId, targetClusterId] = [targetClusterId, sourceClusterId];
    }
    const key = `${directed ? "d" : "u"}:${sourceClusterId}->${targetClusterId}`;
    const accumulator = aggregateEdges.get(key) ?? {
      sourceClusterId,
      targetClusterId,
      directed,
      weight: 0,
      relationTypes: new Set<string>(),
    };
    accumulator.weight += 1;
    const relationType = graph.getEdgeAttribute(edgeId, "relationType");
    if (typeof relationType === "string" && relationType.length > 0) {
      accumulator.relationTypes.add(relationType.slice(0, 80));
    }
    aggregateEdges.set(key, accumulator);
  }
  const overviewEdges = [...aggregateEdges.entries()]
    .map(([edgeId, item]): OverviewEdge => ({
      edgeId,
      sourceClusterId: item.sourceClusterId,
      targetClusterId: item.targetClusterId,
      directed: item.directed,
      weight: item.weight,
      relationTypes: [...item.relationTypes].sort().slice(0, 20),
    }))
    .sort((left, right) => right.weight - left.weight || left.edgeId.localeCompare(right.edgeId))
    .slice(0, maxEdges)
    .sort((left, right) => left.edgeId.localeCompare(right.edgeId));

  return {
    schemaVersion: EXPLORER_OVERVIEW_SCHEMA,
    release,
    layoutAlgorithm: { ...layout.algorithm },
    sourceNodeCount: graph.order,
    sourceEdgeCount: graph.size,
    clusters,
    edges: overviewEdges,
    suppressedNodeCount: Math.max(0, graph.order - clusters.length),
    suppressedEdgeCount: Math.max(0, graph.size - overviewEdges.length),
    readOnly: true,
  };
}

export function semanticZoomPolicy(input: SemanticZoomInput): SemanticZoomPolicy {
  if (!Number.isFinite(input.cameraRatio) || input.cameraRatio <= 0) {
    throw new TypeError("cameraRatio must be a positive finite number");
  }
  if (!Number.isSafeInteger(input.nodeCount) || input.nodeCount < 0 || input.nodeCount > MAX_SCALE_NODES) {
    throw new TypeError(`nodeCount must be an integer between 0 and ${MAX_SCALE_NODES}`);
  }
  if (typeof input.selected !== "boolean") throw new TypeError("selected must be a boolean");
  if (input.cameraRatio >= 2 || input.nodeCount >= 25_000) {
    return {
      mode: "overview",
      useOverviewArtifact: true,
      nodeLabelBudget: input.selected ? 1 : 0,
      edgeBudget: 400,
      labels: input.selected ? "selected-only" : "representatives",
      showEdgeLabels: false,
    };
  }
  if (input.cameraRatio >= 0.8 || input.nodeCount >= 5_000) {
    return {
      mode: "context",
      useOverviewArtifact: false,
      nodeLabelBudget: input.selected ? 80 : 50,
      edgeBudget: 2_000,
      labels: "bounded",
      showEdgeLabels: false,
    };
  }
  return {
    mode: "detail",
    useOverviewArtifact: false,
    nodeLabelBudget: 250,
    edgeBudget: 5_000,
    labels: "bounded",
    showEdgeLabels: input.nodeCount <= 1_000,
  };
}

function normalizedRelationTypes(values: string[] | undefined): string[] {
  if (values === undefined) return [];
  if (!Array.isArray(values) || values.length > 50) {
    throw new TypeError("relationTypes must contain at most 50 values");
  }
  const result = new Set<string>();
  for (const value of values) {
    if (typeof value !== "string") throw new TypeError("relationTypes values must be strings");
    const candidate = normalized(value);
    if (candidate.length === 0 || candidate.length > 120) {
      throw new TypeError("relationTypes values must be between 1 and 120 characters");
    }
    result.add(candidate);
  }
  return [...result].sort();
}

function progressiveCursor(value: string | undefined): { nodeOffset: number; edgeOffset: number } {
  if (value === undefined) return { nodeOffset: 0, edgeOffset: 0 };
  const match = /^p1:(0|[1-9][0-9]*):(0|[1-9][0-9]*)$/.exec(value);
  if (match === null) throw new TypeError("progressive cursor is invalid");
  const nodeOffset = Number(match[1]);
  const edgeOffset = Number(match[2]);
  if (!Number.isSafeInteger(nodeOffset) || !Number.isSafeInteger(edgeOffset)) {
    throw new TypeError("progressive cursor is outside safe integer bounds");
  }
  return { nodeOffset, edgeOffset };
}

function eligibleProgressiveEdge(
  graph: ExplorerGraph,
  edgeId: string,
  relationTypes: string[],
): boolean {
  if (relationTypes.length === 0) return true;
  const value = graph.getEdgeAttribute(edgeId, "relationType");
  return typeof value === "string" && relationTypes.includes(normalized(value));
}

function boundedNeighborhood(
  graph: ExplorerGraph,
  rootNodeId: string,
  depth: 1 | 2,
  relationTypes: string[],
): { nodeIds: string[]; edgeIds: string[] } {
  const visited = new Set<string>([rootNodeId]);
  let frontier = [rootNodeId];
  const eligibleEdges = graph.edges().sort().filter((edgeId) =>
    eligibleProgressiveEdge(graph, edgeId, relationTypes),
  );
  const adjacency = new Map<string, Set<string>>();
  for (const edgeId of eligibleEdges) {
    const source = graph.source(edgeId);
    const target = graph.target(edgeId);
    const sourceSet = adjacency.get(source) ?? new Set<string>();
    const targetSet = adjacency.get(target) ?? new Set<string>();
    sourceSet.add(target);
    targetSet.add(source);
    adjacency.set(source, sourceSet);
    adjacency.set(target, targetSet);
  }
  for (let level = 0; level < depth; level += 1) {
    const next = new Set<string>();
    for (const nodeId of frontier.sort()) {
      for (const adjacent of [...(adjacency.get(nodeId) ?? [])].sort()) {
        if (!visited.has(adjacent)) {
          visited.add(adjacent);
          next.add(adjacent);
        }
      }
    }
    frontier = [...next].sort();
  }
  const nodeIds = [rootNodeId, ...[...visited].filter((item) => item !== rootNodeId).sort()];
  const nodeSet = new Set(nodeIds);
  const edgeIds = eligibleEdges.filter(
    (edgeId) => nodeSet.has(graph.source(edgeId)) && nodeSet.has(graph.target(edgeId)),
  );
  return { nodeIds, edgeIds };
}

export function planProgressiveExpansion(
  graph: ExplorerGraph,
  options: ProgressiveExpansionOptions,
): ProgressiveExpansionPage {
  const release = releaseIdentity(graph);
  const rootNodeId = requiredString(options.rootNodeId, "rootNodeId");
  if (!graph.hasNode(rootNodeId)) {
    throw new TypeError("progressive root is outside the ACL-safe graph");
  }
  const depth = options.depth ?? 1;
  if (depth !== 1 && depth !== MAX_PROGRESSIVE_DEPTH) {
    throw new TypeError("progressive depth must be one or two hops");
  }
  const batchNodeLimit = boundedInteger(
    options.batchNodeLimit,
    100,
    MAX_PROGRESSIVE_BATCH_NODES,
    "batchNodeLimit",
  );
  const batchEdgeLimit = boundedInteger(
    options.batchEdgeLimit,
    200,
    MAX_PROGRESSIVE_BATCH_EDGES,
    "batchEdgeLimit",
  );
  const relationTypes = normalizedRelationTypes(options.relationTypes);
  const { nodeOffset, edgeOffset } = progressiveCursor(options.cursor);
  const neighborhood = boundedNeighborhood(graph, rootNodeId, depth, relationTypes);
  if (nodeOffset > neighborhood.nodeIds.length || edgeOffset > neighborhood.edgeIds.length) {
    throw new TypeError("progressive cursor is outside the bounded neighborhood");
  }
  const nextNodeOffset = Math.min(neighborhood.nodeIds.length, nodeOffset + batchNodeLimit);
  const cumulativeNodes = new Set(neighborhood.nodeIds.slice(0, nextNodeOffset));
  const currentlyEligibleEdges = neighborhood.edgeIds.filter(
    (edgeId) => cumulativeNodes.has(graph.source(edgeId)) && cumulativeNodes.has(graph.target(edgeId)),
  );
  if (edgeOffset > currentlyEligibleEdges.length) {
    throw new TypeError("progressive edge cursor exceeds currently available edges");
  }
  const nextEdgeOffset = Math.min(currentlyEligibleEdges.length, edgeOffset + batchEdgeLimit);
  const complete =
    nextNodeOffset === neighborhood.nodeIds.length && nextEdgeOffset === neighborhood.edgeIds.length;
  return {
    schemaVersion: EXPLORER_SCALE_SCHEMA,
    release,
    rootNodeId,
    depth,
    nodeIds: neighborhood.nodeIds.slice(nodeOffset, nextNodeOffset),
    edgeIds: currentlyEligibleEdges.slice(edgeOffset, nextEdgeOffset),
    loadedNodeCount: nextNodeOffset,
    loadedEdgeCount: nextEdgeOffset,
    complete,
    nextCursor: complete ? null : `p1:${nextNodeOffset}:${nextEdgeOffset}`,
    readOnly: true,
  };
}

export function performanceViolations(sample: PerformanceSample): string[] {
  const budget = PERFORMANCE_BUDGETS[sample.tier];
  const violations: string[] = [];
  const exact = (field: "nodeCount", actual: number, expected: number): void => {
    if (actual !== expected) violations.push(`${field} must equal ${expected}`);
  };
  const maximum = (field: string, actual: number, limit: number): void => {
    if (!Number.isFinite(actual) || actual < 0 || actual > limit) {
      violations.push(`${field} exceeds ${limit}`);
    }
  };
  const minimum = (field: string, actual: number, limit: number): void => {
    if (!Number.isFinite(actual) || actual < limit || actual > 1) {
      violations.push(`${field} is below ${limit}`);
    }
  };
  exact("nodeCount", sample.nodeCount, budget.nodeCount);
  maximum("edgeCount", sample.edgeCount, budget.maxEdgeCount);
  maximum("payloadBytes", sample.payloadBytes, budget.maxPayloadBytes);
  maximum("parseMs", sample.parseMs, budget.maxParseMs);
  maximum("importMs", sample.importMs, budget.maxImportMs);
  maximum("layoutMs", sample.layoutMs, budget.maxLayoutMs);
  maximum("overviewMs", sample.overviewMs, budget.maxOverviewMs);
  maximum(
    "firstMeaningfulRenderMs",
    sample.firstMeaningfulRenderMs,
    budget.maxFirstMeaningfulRenderMs,
  );
  maximum("panZoomP95Ms", sample.panZoomP95Ms, budget.maxPanZoomP95Ms);
  maximum("selectionP95Ms", sample.selectionP95Ms, budget.maxSelectionP95Ms);
  maximum("neighborhoodP95Ms", sample.neighborhoodP95Ms, budget.maxNeighborhoodP95Ms);
  maximum("memoryMiB", sample.memoryMiB, budget.maxMemoryMiB);
  minimum("labelSuppressionRatio", sample.labelSuppressionRatio, budget.minLabelSuppressionRatio);
  minimum("edgeReductionRatio", sample.edgeReductionRatio, budget.minEdgeReductionRatio);
  return violations;
}
