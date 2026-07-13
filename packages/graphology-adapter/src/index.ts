import * as Graphology from "graphology";

export const KNOWLEDGE_GRAPH_V2_SCHEMA = "knowledge-os-graph/v2";
export const GRAPH_API_SCHEMA = "knowledge-engine-graph-api/v1";

const AUDIENCES = new Set(["public", "internal", "confidential", "restricted"]);
const RENDERER_FIELDS = new Set([
  "camera",
  "color",
  "coordinates",
  "hidden",
  "label_color",
  "layout",
  "reducer",
  "sigma_color",
  "size",
  "x",
  "y",
]);

type UnknownRecord = Record<string, unknown>;

export interface AdapterOptions {
  expectedReleaseId?: string;
  expectedManifestSha256?: string;
}

export interface KnowledgeGraphV2Release {
  release_id: string;
  source_commit_sha: string;
  foundation_commit_sha: string;
  content_sha256: string;
}

export interface KnowledgeGraphV2Node extends UnknownRecord {
  concept_id: string;
  x_kos_id: string;
  title: string;
  description: string;
  type: string;
  audience: string;
  status: string;
  confidence: number;
  tags: string[];
  aliases: string[];
  path: string;
}

export interface KnowledgeGraphV2Edge extends UnknownRecord {
  edge_id: string;
  source: string;
  target: string;
  relation_type: string;
  directed: boolean;
  audience: string;
  confidence: number;
  generated_inverse: boolean;
}

export interface KnowledgeGraphV2 {
  schema_version: string;
  release: KnowledgeGraphV2Release;
  nodes: KnowledgeGraphV2Node[];
  edges: KnowledgeGraphV2Edge[];
  renderer_neutral: boolean;
}

export interface GraphApiRelease {
  release_id: string;
  manifest_sha256: string;
  loaded_at?: string | null;
  created_at?: string | null;
  source_commit_sha?: string | null;
  foundation_commit_sha?: string | null;
  content_sha256?: string | null;
}

export interface GraphApiNode extends UnknownRecord {
  concept_id: string;
  x_kos_id: string;
  title: string;
  description: string;
  type: string;
  audience: string;
  status: string;
  confidence: number;
  tags: string[];
  aliases: string[];
  source_path: string;
}

export interface GraphApiEdge extends UnknownRecord {
  edge_id: string;
  source: string;
  target: string;
  relation_type: string;
  directed: boolean;
  audience: string;
  confidence: number;
  generated_inverse: boolean;
}

export interface GraphApiPayload extends UnknownRecord {
  schema_version: string;
  release: GraphApiRelease;
  read_only: boolean;
  nodes: GraphApiNode[];
  edges: GraphApiEdge[];
}

export interface GraphNodeAttributes {
  conceptId: string;
  xKosId: string;
  title: string;
  description: string;
  type: string;
  audience: string;
  status: string;
  confidence: number;
  tags: string[];
  aliases: string[];
  sourcePath: string;
}

export interface GraphEdgeAttributes {
  edgeId: string;
  relationType: string;
  directed: boolean;
  audience: string;
  confidence: number;
  generatedInverse: boolean;
}

export interface KnowledgeGraphAttributes {
  adapterSchemaVersion: string;
  sourceSchemaVersion: string;
  releaseId: string;
  manifestSha256?: string;
  sourceCommitSha?: string;
  foundationCommitSha?: string;
  contentSha256?: string;
  readOnly: true;
  rendererNeutral: true;
}

export type KnowledgeGraphology = Graphology.default<
  GraphNodeAttributes,
  GraphEdgeAttributes,
  KnowledgeGraphAttributes
>;

interface NormalizedInput {
  sourceSchemaVersion: string;
  release: GraphApiRelease;
  nodes: GraphApiNode[];
  edges: GraphApiEdge[];
}

function record(value: unknown, label: string): UnknownRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
  return value as UnknownRecord;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${label} must be a non-empty string`);
  }
  return value;
}

function optionalString(value: unknown, label: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  return requiredString(value, label);
}

function stringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new TypeError(`${label} must be a string array`);
  }
  return [...new Set(value)].sort();
}

function finiteNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(`${label} must be a finite number`);
  }
  return value;
}

function audience(value: unknown, label: string): string {
  const normalized = requiredString(value, label);
  if (!AUDIENCES.has(normalized)) throw new TypeError(`${label} is unknown`);
  return normalized;
}

function rejectRendererFields(value: UnknownRecord, label: string): void {
  const found = Object.keys(value).filter((key) => RENDERER_FIELDS.has(key));
  if (found.length > 0) {
    throw new TypeError(`${label} contains renderer fields: ${found.sort().join(",")}`);
  }
}

function validateExpectedRelease(release: GraphApiRelease, options: AdapterOptions): void {
  if (options.expectedReleaseId !== undefined && release.release_id !== options.expectedReleaseId) {
    throw new TypeError("adapter release identity mismatch");
  }
  if (
    options.expectedManifestSha256 !== undefined &&
    release.manifest_sha256 !== options.expectedManifestSha256
  ) {
    throw new TypeError("adapter manifest identity mismatch");
  }
}

function normalizeNode(value: unknown, pathField: "path" | "source_path"): GraphApiNode {
  const node = record(value, "node");
  rejectRendererFields(node, "node");
  return {
    concept_id: requiredString(node.concept_id, "node.concept_id"),
    x_kos_id: requiredString(node.x_kos_id, "node.x_kos_id"),
    title: requiredString(node.title, "node.title"),
    description: requiredString(node.description, "node.description"),
    type: requiredString(node.type, "node.type"),
    audience: audience(node.audience, "node.audience"),
    status: requiredString(node.status, "node.status"),
    confidence: finiteNumber(node.confidence, "node.confidence"),
    tags: stringArray(node.tags, "node.tags"),
    aliases: stringArray(node.aliases, "node.aliases"),
    source_path: requiredString(node[pathField], `node.${pathField}`),
  };
}

function normalizeEdge(value: unknown): GraphApiEdge {
  const edge = record(value, "edge");
  rejectRendererFields(edge, "edge");
  if (typeof edge.directed !== "boolean") {
    throw new TypeError("edge.directed must be a boolean");
  }
  if (typeof edge.generated_inverse !== "boolean") {
    throw new TypeError("edge.generated_inverse must be a boolean");
  }
  return {
    edge_id: requiredString(edge.edge_id, "edge.edge_id"),
    source: requiredString(edge.source, "edge.source"),
    target: requiredString(edge.target, "edge.target"),
    relation_type: requiredString(edge.relation_type, "edge.relation_type"),
    directed: edge.directed,
    audience: audience(edge.audience, "edge.audience"),
    confidence: finiteNumber(edge.confidence, "edge.confidence"),
    generated_inverse: edge.generated_inverse,
  };
}

function canonicalInput(input: KnowledgeGraphV2, options: AdapterOptions): NormalizedInput {
  const root = record(input, "KnowledgeGraphV2");
  rejectRendererFields(root, "KnowledgeGraphV2");
  if (root.schema_version !== KNOWLEDGE_GRAPH_V2_SCHEMA) {
    throw new TypeError("unsupported KnowledgeGraphV2 schema");
  }
  if (root.renderer_neutral !== true) {
    throw new TypeError("KnowledgeGraphV2 must be renderer neutral");
  }
  const sourceRelease = record(root.release, "KnowledgeGraphV2.release");
  const release: GraphApiRelease = {
    release_id: requiredString(sourceRelease.release_id, "release.release_id"),
    manifest_sha256: "",
    source_commit_sha: requiredString(
      sourceRelease.source_commit_sha,
      "release.source_commit_sha",
    ),
    foundation_commit_sha: requiredString(
      sourceRelease.foundation_commit_sha,
      "release.foundation_commit_sha",
    ),
    content_sha256: requiredString(sourceRelease.content_sha256, "release.content_sha256"),
  };
  if (options.expectedManifestSha256 !== undefined) {
    throw new TypeError("canonical graph input has no manifest identity");
  }
  validateExpectedRelease(release, options);
  if (!Array.isArray(root.nodes) || !Array.isArray(root.edges)) {
    throw new TypeError("KnowledgeGraphV2 nodes and edges must be arrays");
  }
  return {
    sourceSchemaVersion: KNOWLEDGE_GRAPH_V2_SCHEMA,
    release,
    nodes: root.nodes.map((node) => normalizeNode(node, "path")),
    edges: root.edges.map(normalizeEdge),
  };
}

function apiInput(input: GraphApiPayload, options: AdapterOptions): NormalizedInput {
  const root = record(input, "GraphApiPayload");
  rejectRendererFields(root, "GraphApiPayload");
  if (root.schema_version !== GRAPH_API_SCHEMA) {
    throw new TypeError("unsupported Graph API schema");
  }
  if (root.read_only !== true) throw new TypeError("Graph API payload must be read-only");
  const sourceRelease = record(root.release, "GraphApiPayload.release");
  const release: GraphApiRelease = {
    release_id: requiredString(sourceRelease.release_id, "release.release_id"),
    manifest_sha256: requiredString(
      sourceRelease.manifest_sha256,
      "release.manifest_sha256",
    ),
    loaded_at: optionalString(sourceRelease.loaded_at, "release.loaded_at"),
    created_at: optionalString(sourceRelease.created_at, "release.created_at"),
    source_commit_sha: optionalString(
      sourceRelease.source_commit_sha,
      "release.source_commit_sha",
    ),
    foundation_commit_sha: optionalString(
      sourceRelease.foundation_commit_sha,
      "release.foundation_commit_sha",
    ),
    content_sha256: optionalString(sourceRelease.content_sha256, "release.content_sha256"),
  };
  validateExpectedRelease(release, options);
  if (!Array.isArray(root.nodes) || !Array.isArray(root.edges)) {
    throw new TypeError("Graph API payload nodes and edges must be arrays");
  }
  return {
    sourceSchemaVersion: GRAPH_API_SCHEMA,
    release,
    nodes: root.nodes.map((node) => normalizeNode(node, "source_path")),
    edges: root.edges.map(normalizeEdge),
  };
}

function buildGraph(input: NormalizedInput): KnowledgeGraphology {
  const GraphConstructor = Graphology.default as unknown as new (options: {
    allowSelfLoops: boolean;
    multi: boolean;
    type: "mixed";
  }) => KnowledgeGraphology;
  const graph = new GraphConstructor({
    allowSelfLoops: false,
    multi: true,
    type: "mixed",
  });
  graph.replaceAttributes({
    adapterSchemaVersion: "knowledge-os-graphology-adapter/v1",
    sourceSchemaVersion: input.sourceSchemaVersion,
    releaseId: input.release.release_id,
    ...(input.release.manifest_sha256
      ? { manifestSha256: input.release.manifest_sha256 }
      : {}),
    ...(input.release.source_commit_sha
      ? { sourceCommitSha: input.release.source_commit_sha }
      : {}),
    ...(input.release.foundation_commit_sha
      ? { foundationCommitSha: input.release.foundation_commit_sha }
      : {}),
    ...(input.release.content_sha256
      ? { contentSha256: input.release.content_sha256 }
      : {}),
    readOnly: true,
    rendererNeutral: true,
  });

  const nodeIds = new Set<string>();
  for (const node of [...input.nodes].sort((left, right) =>
    left.concept_id.localeCompare(right.concept_id),
  )) {
    if (nodeIds.has(node.concept_id)) throw new TypeError("duplicate concept identity");
    nodeIds.add(node.concept_id);
    graph.addNode(node.concept_id, {
      conceptId: node.concept_id,
      xKosId: node.x_kos_id,
      title: node.title,
      description: node.description,
      type: node.type,
      audience: node.audience,
      status: node.status,
      confidence: node.confidence,
      tags: [...node.tags],
      aliases: [...node.aliases],
      sourcePath: node.source_path,
    });
  }

  const edgeIds = new Set<string>();
  for (const edge of [...input.edges].sort((left, right) =>
    left.edge_id.localeCompare(right.edge_id),
  )) {
    if (edgeIds.has(edge.edge_id)) throw new TypeError("duplicate edge identity");
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
      throw new TypeError("edge endpoint is missing");
    }
    if (edge.source === edge.target) throw new TypeError("self-loop edge is forbidden");
    edgeIds.add(edge.edge_id);
    const attributes: GraphEdgeAttributes = {
      edgeId: edge.edge_id,
      relationType: edge.relation_type,
      directed: edge.directed,
      audience: edge.audience,
      confidence: edge.confidence,
      generatedInverse: edge.generated_inverse,
    };
    if (edge.directed) {
      graph.addDirectedEdgeWithKey(edge.edge_id, edge.source, edge.target, attributes);
    } else {
      graph.addUndirectedEdgeWithKey(edge.edge_id, edge.source, edge.target, attributes);
    }
  }
  return graph;
}

export function knowledgeGraphV2ToGraphology(
  input: KnowledgeGraphV2,
  options: AdapterOptions = {},
): KnowledgeGraphology {
  return buildGraph(canonicalInput(input, options));
}

export function graphApiPayloadToGraphology(
  input: GraphApiPayload,
  options: AdapterOptions = {},
): KnowledgeGraphology {
  return buildGraph(apiInput(input, options));
}
