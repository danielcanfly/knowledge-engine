import type { Attributes } from "graphology-types";

import type { ExplorerGraph, ExplorerNodeSummary, ExplorerSelection } from "./index.js";

export const EXPLORER_DETAILS_SCHEMA = "knowledge-os-explorer-details/v1";
export const MAX_PROVENANCE_REFERENCES = 20;

export interface ExplorerReleaseIdentity {
  releaseId: string;
  manifestSha256?: string;
  sourceCommitSha?: string;
  foundationCommitSha?: string;
  contentSha256?: string;
}

export interface ExplorerProvenanceReference {
  referenceId: string;
  label: string;
  sourcePath: string;
  anchor?: string;
  reviewStatus: "approved";
}

export interface ExplorerNodeDetailsRecord {
  nodeId: string;
  provenance: ExplorerProvenanceReference[];
}

export interface ExplorerEdgeDetailsRecord {
  edgeId: string;
  provenance: ExplorerProvenanceReference[];
}

export interface ExplorerDetailsBundle {
  schemaVersion: typeof EXPLORER_DETAILS_SCHEMA;
  release: ExplorerReleaseIdentity;
  nodes: ExplorerNodeDetailsRecord[];
  edges: ExplorerEdgeDetailsRecord[];
  readOnly: true;
}

export interface ExplorerNodeDetail {
  kind: "node";
  release: ExplorerReleaseIdentity;
  node: ExplorerSelection;
  markdownHref: string;
  provenance: ExplorerProvenanceReference[];
}

export interface ExplorerEdgeDetail {
  kind: "edge";
  release: ExplorerReleaseIdentity;
  edge: {
    id: string;
    source: ExplorerNodeSummary;
    target: ExplorerNodeSummary;
    relationType: string;
    directed: boolean;
    audience: string;
    confidence: number;
    generatedInverse: boolean;
  };
  provenance: ExplorerProvenanceReference[];
}

export type ExplorerDetailPanel = ExplorerNodeDetail | ExplorerEdgeDetail | null;

export interface ExplorerDetailsState {
  release: ExplorerReleaseIdentity;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  panel: ExplorerDetailPanel;
  readOnly: true;
}

export interface ExplorerDetailsControllerOptions {
  graph: ExplorerGraph;
  details?: ExplorerDetailsBundle;
  onChange?: (panel: ExplorerDetailPanel) => void;
}

export interface ExplorerDetailsController {
  clear(): void;
  edgeReducer(edgeId: string, attributes: Attributes): Attributes;
  getState(): ExplorerDetailsState;
  nodeReducer(nodeId: string, attributes: Attributes): Attributes;
  reconcileVisible(visibleNodeIds: Iterable<string>, visibleEdgeIds: Iterable<string>): void;
  selectEdge(edgeId: string): void;
  selectNode(nodeId: string): void;
}

function requiredString(value: unknown, label: string, maximum: number): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maximum) {
    throw new TypeError(`${label} must be a non-empty string of at most ${maximum} characters`);
  }
  return value;
}

function requiredGraphString(graph: ExplorerGraph, name: string): string {
  return requiredString(graph.getAttribute(name), `graph.${name}`, 300);
}

function optionalGraphString(graph: ExplorerGraph, name: string): string | undefined {
  const value = graph.getAttribute(name);
  if (value === undefined || value === null) return undefined;
  return requiredString(value, `graph.${name}`, 300);
}

function boundedString(value: unknown, maximum: number): string {
  return typeof value === "string" ? value.slice(0, maximum) : "";
}

function stringArray(value: unknown, maximum: number): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === "string")
    .slice(0, maximum)
    .map((item) => item.slice(0, 120));
}

function finiteNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function releaseIdentity(graph: ExplorerGraph): ExplorerReleaseIdentity {
  if (graph.getAttribute("readOnly") !== true) {
    throw new TypeError("details controller accepts only a read-only graph");
  }
  if (graph.getAttribute("rendererNeutral") !== true) {
    throw new TypeError("details controller accepts only a renderer-neutral graph");
  }
  const optional = (name: string): string | undefined => optionalGraphString(graph, name);
  const manifestSha256 = optional("manifestSha256");
  const sourceCommitSha = optional("sourceCommitSha");
  const foundationCommitSha = optional("foundationCommitSha");
  const contentSha256 = optional("contentSha256");
  return {
    releaseId: requiredGraphString(graph, "releaseId"),
    ...(manifestSha256 !== undefined ? { manifestSha256 } : {}),
    ...(sourceCommitSha !== undefined ? { sourceCommitSha } : {}),
    ...(foundationCommitSha !== undefined ? { foundationCommitSha } : {}),
    ...(contentSha256 !== undefined ? { contentSha256 } : {}),
  };
}

function cloneIdentity(identity: ExplorerReleaseIdentity): ExplorerReleaseIdentity {
  return { ...identity };
}

function safeMarkdownPath(value: unknown, label: string): string {
  const path = requiredString(value, label, 300);
  if (
    path.startsWith("/") ||
    path.includes("\\") ||
    path.includes("?") ||
    path.includes("#") ||
    /^[a-z][a-z0-9+.-]*:/i.test(path)
  ) {
    throw new TypeError(`${label} must be a safe relative Markdown path`);
  }
  const segments = path.split("/");
  if (segments.some((segment) => segment.length === 0 || segment === "." || segment === "..")) {
    throw new TypeError(`${label} must not contain empty or traversal segments`);
  }
  if (!path.toLocaleLowerCase("en-US").endsWith(".md")) {
    throw new TypeError(`${label} must end in .md`);
  }
  return path;
}

function optionalAnchor(value: unknown, label: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  const anchor = requiredString(value, label, 120);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(anchor)) {
    throw new TypeError(`${label} is invalid`);
  }
  return anchor;
}

function provenance(value: unknown, label: string): ExplorerProvenanceReference[] {
  if (!Array.isArray(value) || value.length > MAX_PROVENANCE_REFERENCES) {
    throw new TypeError(`${label} must contain at most ${MAX_PROVENANCE_REFERENCES} references`);
  }
  const seen = new Set<string>();
  return value.map((candidate, index) => {
    if (candidate === null || typeof candidate !== "object" || Array.isArray(candidate)) {
      throw new TypeError(`${label}[${index}] must be an object`);
    }
    const item = candidate as Record<string, unknown>;
    const referenceId = requiredString(item.referenceId, `${label}[${index}].referenceId`, 160);
    if (seen.has(referenceId)) throw new TypeError(`${label} contains duplicate reference IDs`);
    seen.add(referenceId);
    if (item.reviewStatus !== "approved") {
      throw new TypeError(`${label}[${index}] must be approved`);
    }
    const anchor = optionalAnchor(item.anchor, `${label}[${index}].anchor`);
    return {
      referenceId,
      label: requiredString(item.label, `${label}[${index}].label`, 200),
      sourcePath: safeMarkdownPath(item.sourcePath, `${label}[${index}].sourcePath`),
      ...(anchor !== undefined ? { anchor } : {}),
      reviewStatus: "approved" as const,
    };
  });
}

function validateIdentity(actual: ExplorerReleaseIdentity, supplied: ExplorerReleaseIdentity): void {
  const fields: Array<keyof ExplorerReleaseIdentity> = [
    "releaseId",
    "manifestSha256",
    "sourceCommitSha",
    "foundationCommitSha",
    "contentSha256",
  ];
  for (const field of fields) {
    if (actual[field] !== supplied[field]) {
      throw new TypeError(`details ${field} identity mismatch`);
    }
  }
}

interface ValidatedDetails {
  nodes: Map<string, ExplorerProvenanceReference[]>;
  edges: Map<string, ExplorerProvenanceReference[]>;
}

function validateBundle(
  graph: ExplorerGraph,
  identity: ExplorerReleaseIdentity,
  bundle: ExplorerDetailsBundle | undefined,
): ValidatedDetails {
  const nodes = new Map<string, ExplorerProvenanceReference[]>();
  const edges = new Map<string, ExplorerProvenanceReference[]>();
  if (bundle === undefined) return { nodes, edges };
  if (bundle.schemaVersion !== EXPLORER_DETAILS_SCHEMA) {
    throw new TypeError("unsupported explorer details schema");
  }
  if (bundle.readOnly !== true) throw new TypeError("details bundle must be read-only");
  validateIdentity(identity, bundle.release);
  if (!Array.isArray(bundle.nodes) || !Array.isArray(bundle.edges)) {
    throw new TypeError("details nodes and edges must be arrays");
  }
  bundle.nodes.forEach((record, index) => {
    const nodeId = requiredString(record?.nodeId, `details node[${index}].nodeId`, 300);
    if (!graph.hasNode(nodeId)) throw new TypeError("details node is outside the ACL-safe graph");
    if (nodes.has(nodeId)) throw new TypeError("details contains duplicate node records");
    nodes.set(nodeId, provenance(record.provenance, `node ${nodeId} provenance`));
  });
  bundle.edges.forEach((record, index) => {
    const edgeId = requiredString(record?.edgeId, `details edge[${index}].edgeId`, 300);
    if (!graph.hasEdge(edgeId)) throw new TypeError("details edge is outside the ACL-safe graph");
    if (edges.has(edgeId)) throw new TypeError("details contains duplicate edge records");
    edges.set(edgeId, provenance(record.provenance, `edge ${edgeId} provenance`));
  });
  return { nodes, edges };
}

function nodeSummary(graph: ExplorerGraph, nodeId: string): ExplorerNodeSummary {
  return {
    id: nodeId,
    title: boundedString(graph.getNodeAttribute(nodeId, "title"), 200) || nodeId,
    type: boundedString(graph.getNodeAttribute(nodeId, "type"), 80),
  };
}

function nodeSelection(graph: ExplorerGraph, nodeId: string): ExplorerSelection {
  return {
    id: nodeId,
    title: boundedString(graph.getNodeAttribute(nodeId, "title"), 200) || nodeId,
    description: boundedString(graph.getNodeAttribute(nodeId, "description"), 400),
    type: boundedString(graph.getNodeAttribute(nodeId, "type"), 80),
    audience: boundedString(graph.getNodeAttribute(nodeId, "audience"), 40),
    sourcePath: boundedString(graph.getNodeAttribute(nodeId, "sourcePath"), 300),
    tags: stringArray(graph.getNodeAttribute(nodeId, "tags"), 20),
  };
}

function cloneProvenance(items: ExplorerProvenanceReference[]): ExplorerProvenanceReference[] {
  return items.map((item) => ({ ...item }));
}

export function createExplorerDetailsController(
  options: ExplorerDetailsControllerOptions,
): ExplorerDetailsController {
  const identity = releaseIdentity(options.graph);
  const details = validateBundle(options.graph, identity, options.details);
  let selectedNodeId: string | null = null;
  let selectedEdgeId: string | null = null;

  const panel = (): ExplorerDetailPanel => {
    if (selectedNodeId !== null) {
      const node = nodeSelection(options.graph, selectedNodeId);
      return {
        kind: "node",
        release: cloneIdentity(identity),
        node,
        markdownHref: safeMarkdownPath(node.sourcePath, `node ${selectedNodeId} sourcePath`),
        provenance: cloneProvenance(details.nodes.get(selectedNodeId) ?? []),
      };
    }
    if (selectedEdgeId !== null) {
      return {
        kind: "edge",
        release: cloneIdentity(identity),
        edge: {
          id: selectedEdgeId,
          source: nodeSummary(options.graph, options.graph.source(selectedEdgeId)),
          target: nodeSummary(options.graph, options.graph.target(selectedEdgeId)),
          relationType: boundedString(options.graph.getEdgeAttribute(selectedEdgeId, "relationType"), 80),
          directed: options.graph.getEdgeAttribute(selectedEdgeId, "directed") === true,
          audience: boundedString(options.graph.getEdgeAttribute(selectedEdgeId, "audience"), 40),
          confidence: finiteNumber(options.graph.getEdgeAttribute(selectedEdgeId, "confidence")),
          generatedInverse: options.graph.getEdgeAttribute(selectedEdgeId, "generatedInverse") === true,
        },
        provenance: cloneProvenance(details.edges.get(selectedEdgeId) ?? []),
      };
    }
    return null;
  };

  const emit = (): void => options.onChange?.(panel());
  const clear = (): void => {
    selectedNodeId = null;
    selectedEdgeId = null;
    emit();
  };

  return {
    clear,
    edgeReducer: (edgeId: string, attributes: Attributes): Attributes =>
      edgeId === selectedEdgeId
        ? { ...attributes, color: "#0f766e", highlighted: true, size: 3, zIndex: 2 }
        : attributes,
    getState: () => ({
      release: cloneIdentity(identity),
      selectedNodeId,
      selectedEdgeId,
      panel: panel(),
      readOnly: true,
    }),
    nodeReducer: (nodeId: string, attributes: Attributes): Attributes =>
      nodeId === selectedNodeId
        ? {
            ...attributes,
            color: "#0f766e",
            forceLabel: true,
            highlighted: true,
            size: 8,
            zIndex: 2,
          }
        : attributes,
    reconcileVisible: (
      visibleNodeIds: Iterable<string>,
      visibleEdgeIds: Iterable<string>,
    ): void => {
      const nodes = new Set(visibleNodeIds);
      const edges = new Set(visibleEdgeIds);
      if (
        (selectedNodeId !== null && !nodes.has(selectedNodeId)) ||
        (selectedEdgeId !== null && !edges.has(selectedEdgeId))
      ) {
        clear();
      }
    },
    selectEdge: (edgeId: string): void => {
      if (!options.graph.hasEdge(edgeId)) {
        throw new TypeError("selected edge is outside the ACL-safe graph");
      }
      selectedNodeId = null;
      selectedEdgeId = edgeId;
      emit();
    },
    selectNode: (nodeId: string): void => {
      if (!options.graph.hasNode(nodeId)) {
        throw new TypeError("selected node is outside the ACL-safe graph");
      }
      selectedNodeId = nodeId;
      selectedEdgeId = null;
      emit();
    },
  };
}
