import type { AbstractGraph, Attributes } from "graphology-types";

export const EXPLORER_SCHEMA = "knowledge-os-sigma-explorer/v1";
export const MAX_TEXT_FALLBACK_NODES = 500;
export const MAX_SEARCH_QUERY_LENGTH = 160;
export const MAX_SEARCH_RESULTS = 100;
export const MAX_FILTER_VALUES = 50;

export type ExplorerGraph = AbstractGraph<Attributes, Attributes, Attributes>;
export type NeighborhoodDepth = 0 | 1 | 2;

export interface ExplorerNodeSummary {
  id: string;
  title: string;
  type: string;
}

export interface ExplorerFilters {
  relationTypes: string[];
  tags: string[];
  types: string[];
  showOrphans: boolean;
}

export interface ExplorerViewControls {
  query: string;
  focusNodeId: string | null;
  neighborhoodDepth: NeighborhoodDepth;
  filters: ExplorerFilters;
}

export interface ExplorerView {
  visibleNodeIds: string[];
  visibleEdgeIds: string[];
  searchResults: ExplorerNodeSummary[];
}

export interface ExplorerShellState {
  schemaVersion: typeof EXPLORER_SCHEMA;
  releaseId: string;
  selectedNodeId: string | null;
  nodeCount: number;
  edgeCount: number;
  visibleNodeCount: number;
  visibleEdgeCount: number;
  textualFallback: ExplorerNodeSummary[];
  textualFallbackTruncated: boolean;
  query: string;
  searchResults: ExplorerNodeSummary[];
  focusNodeId: string | null;
  neighborhoodDepth: NeighborhoodDepth;
  filters: ExplorerFilters;
  readOnly: true;
}

export interface ExplorerSelection {
  id: string;
  title: string;
  description: string;
  type: string;
  audience: string;
  sourcePath: string;
  tags: string[];
}

export interface ExplorerShellOptions {
  graph: ExplorerGraph;
  container: HTMLElement;
  rendererFactory: RendererFactory;
  onSelection?: (selection: ExplorerSelection | null) => void;
}

export type BrowserExplorerShellOptions = Omit<ExplorerShellOptions, "rendererFactory">;

interface CameraLike {
  animatedReset(options?: { duration?: number }): Promise<void> | void;
}

interface SigmaRendererLike {
  getCamera(): CameraLike;
  kill(): void;
  off(event: "clickNode", listener: (payload: { node: string }) => void): unknown;
  off(event: "clickStage", listener: () => void): unknown;
  on(event: "clickNode", listener: (payload: { node: string }) => void): unknown;
  on(event: "clickStage", listener: () => void): unknown;
  refresh(): unknown;
}

export type RendererFactory = (
  graph: ExplorerGraph,
  container: HTMLElement,
  settings: Readonly<Record<string, unknown>>,
) => SigmaRendererLike;

export interface ExplorerShell {
  clearFocus(): void;
  clearSelection(): void;
  destroy(): void;
  focusNode(nodeId: string, depth?: 1 | 2): void;
  getSelection(): ExplorerSelection | null;
  getState(): ExplorerShellState;
  resetCamera(): Promise<void>;
  selectNode(nodeId: string): void;
  setFilters(filters: Partial<ExplorerFilters>): void;
  setSearchQuery(query: string): void;
}

const DEFAULT_FILTERS: ExplorerFilters = {
  relationTypes: [],
  tags: [],
  types: [],
  showOrphans: true,
};

function requiredGraphString(graph: ExplorerGraph, name: string): string {
  const value = graph.getAttribute(name);
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`explorer graph attribute ${name} must be a non-empty string`);
  }
  return value;
}

function boundedString(value: unknown, maximum: number): string {
  if (typeof value !== "string") return "";
  return value.slice(0, maximum);
}

function stringArray(value: unknown, maximum: number): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === "string")
    .slice(0, maximum)
    .map((item) => item.slice(0, 120));
}

function validateInputGraph(graph: ExplorerGraph): string {
  if (graph.getAttribute("readOnly") !== true) {
    throw new TypeError("Sigma explorer accepts only a read-only graph");
  }
  if (graph.getAttribute("rendererNeutral") !== true) {
    throw new TypeError("Sigma explorer accepts only a renderer-neutral graph");
  }
  return requiredGraphString(graph, "releaseId");
}

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function initialPosition(nodeId: string, index: number, count: number): { x: number; y: number } {
  if (count === 1) return { x: 0, y: 0 };
  const phase = (stableHash(nodeId) / 0xffffffff) * Math.PI * 2;
  const angle = phase + (index / Math.max(count, 1)) * Math.PI * 2;
  const radius = 1 + (stableHash(`${nodeId}:radius`) % 1000) / 4000;
  return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
}

export function createRendererProjection(source: ExplorerGraph): ExplorerGraph {
  validateInputGraph(source);
  const projection = source.copy();
  const nodeIds = projection.nodes().sort();
  nodeIds.forEach((nodeId, index) => {
    const position = initialPosition(nodeId, index, nodeIds.length);
    projection.mergeNodeAttributes(nodeId, {
      color: "#64748b",
      label: boundedString(projection.getNodeAttribute(nodeId, "title"), 200) || nodeId,
      size: 5,
      x: position.x,
      y: position.y,
    });
  });
  for (const edgeId of projection.edges().sort()) {
    projection.mergeEdgeAttributes(edgeId, {
      color: "#94a3b8",
      label: boundedString(projection.getEdgeAttribute(edgeId, "relationType"), 80),
      size: 1,
    });
  }
  return projection;
}

function nodeSummary(graph: ExplorerGraph, nodeId: string): ExplorerNodeSummary {
  return {
    id: nodeId,
    title: boundedString(graph.getNodeAttribute(nodeId, "title"), 200) || nodeId,
    type: boundedString(graph.getNodeAttribute(nodeId, "type"), 80),
  };
}

function selection(graph: ExplorerGraph, nodeId: string): ExplorerSelection {
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

function normalized(value: string): string {
  return value.normalize("NFKC").trim().toLocaleLowerCase("en-US");
}

function normalizedFilterValues(values: string[], name: string): string[] {
  if (values.length > MAX_FILTER_VALUES) {
    throw new TypeError(`${name} may contain at most ${MAX_FILTER_VALUES} values`);
  }
  const result = new Set<string>();
  for (const value of values) {
    if (typeof value !== "string") throw new TypeError(`${name} values must be strings`);
    const candidate = normalized(value);
    if (candidate.length === 0 || candidate.length > 120) {
      throw new TypeError(`${name} values must be between 1 and 120 characters`);
    }
    result.add(candidate);
  }
  return [...result].sort();
}

function normalizedQuery(query: string): string {
  if (typeof query !== "string") throw new TypeError("search query must be a string");
  const candidate = normalized(query);
  if (candidate.length > MAX_SEARCH_QUERY_LENGTH) {
    throw new TypeError(`search query may contain at most ${MAX_SEARCH_QUERY_LENGTH} characters`);
  }
  return candidate;
}

function normalizedFilters(filters: ExplorerFilters): ExplorerFilters {
  if (typeof filters.showOrphans !== "boolean") {
    throw new TypeError("showOrphans must be a boolean");
  }
  return {
    relationTypes: normalizedFilterValues(filters.relationTypes, "relationTypes"),
    tags: normalizedFilterValues(filters.tags, "tags"),
    types: normalizedFilterValues(filters.types, "types"),
    showOrphans: filters.showOrphans,
  };
}

function nodePassesFilters(graph: ExplorerGraph, nodeId: string, filters: ExplorerFilters): boolean {
  const type = normalized(boundedString(graph.getNodeAttribute(nodeId, "type"), 80));
  const tags = stringArray(graph.getNodeAttribute(nodeId, "tags"), 100).map(normalized);
  const typePasses = filters.types.length === 0 || filters.types.includes(type);
  const tagPasses = filters.tags.length === 0 || filters.tags.some((tag) => tags.includes(tag));
  return typePasses && tagPasses;
}

function edgePassesFilters(graph: ExplorerGraph, edgeId: string, filters: ExplorerFilters): boolean {
  if (filters.relationTypes.length === 0) return true;
  const relationType = normalized(
    boundedString(graph.getEdgeAttribute(edgeId, "relationType"), 80),
  );
  return filters.relationTypes.includes(relationType);
}

function searchScore(graph: ExplorerGraph, nodeId: string, query: string): number | null {
  if (query.length === 0) return null;
  const title = normalized(boundedString(graph.getNodeAttribute(nodeId, "title"), 200));
  const aliases = stringArray(graph.getNodeAttribute(nodeId, "aliases"), 100).map(normalized);
  const tags = stringArray(graph.getNodeAttribute(nodeId, "tags"), 100).map(normalized);
  const type = normalized(boundedString(graph.getNodeAttribute(nodeId, "type"), 80));
  const description = normalized(
    boundedString(graph.getNodeAttribute(nodeId, "description"), 400),
  );
  const id = normalized(nodeId);
  if (title === query) return 0;
  if (id === query) return 1;
  if (aliases.includes(query)) return 2;
  if (title.startsWith(query)) return 3;
  if (aliases.some((alias) => alias.startsWith(query))) return 4;
  if (title.includes(query)) return 5;
  if (aliases.some((alias) => alias.includes(query))) return 6;
  if (tags.some((tag) => tag.includes(query))) return 7;
  if (type.includes(query)) return 8;
  if (description.includes(query)) return 9;
  if (id.includes(query)) return 10;
  return null;
}

function eligibleEdges(graph: ExplorerGraph, nodes: Set<string>, filters: ExplorerFilters): string[] {
  return graph
    .edges()
    .sort()
    .filter((edgeId) => {
      if (!edgePassesFilters(graph, edgeId, filters)) return false;
      return nodes.has(graph.source(edgeId)) && nodes.has(graph.target(edgeId));
    });
}

function neighborhoodNodes(
  graph: ExplorerGraph,
  focusNodeId: string,
  depth: 1 | 2,
  allowedNodes: Set<string>,
  allowedEdges: string[],
): Set<string> {
  const adjacency = new Map<string, Set<string>>();
  for (const nodeId of allowedNodes) adjacency.set(nodeId, new Set());
  for (const edgeId of allowedEdges) {
    const source = graph.source(edgeId);
    const target = graph.target(edgeId);
    adjacency.get(source)?.add(target);
    adjacency.get(target)?.add(source);
  }
  const visited = new Set<string>([focusNodeId]);
  let frontier = [focusNodeId];
  for (let level = 0; level < depth; level += 1) {
    const next = new Set<string>();
    for (const nodeId of frontier) {
      for (const adjacent of adjacency.get(nodeId) ?? []) {
        if (!visited.has(adjacent)) {
          visited.add(adjacent);
          next.add(adjacent);
        }
      }
    }
    frontier = [...next].sort();
  }
  return visited;
}

export function computeExplorerView(
  graph: ExplorerGraph,
  controls: ExplorerViewControls,
): ExplorerView {
  validateInputGraph(graph);
  const query = normalizedQuery(controls.query);
  const filters = normalizedFilters(controls.filters);
  if (![0, 1, 2].includes(controls.neighborhoodDepth)) {
    throw new TypeError("neighborhood depth must be 0, 1, or 2");
  }
  if (controls.focusNodeId !== null && !graph.hasNode(controls.focusNodeId)) {
    throw new TypeError("focus node is outside the ACL-safe graph");
  }
  if (controls.focusNodeId === null && controls.neighborhoodDepth !== 0) {
    throw new TypeError("neighborhood depth requires a focus node");
  }
  if (controls.focusNodeId !== null && controls.neighborhoodDepth === 0) {
    throw new TypeError("focus node requires a one- or two-hop depth");
  }

  const filteredNodes = new Set(
    graph.nodes().sort().filter((nodeId) => nodePassesFilters(graph, nodeId, filters)),
  );
  if (controls.focusNodeId !== null) filteredNodes.add(controls.focusNodeId);
  const filteredEdges = eligibleEdges(graph, filteredNodes, filters);

  let visibleNodes = new Set(filteredNodes);
  if (controls.focusNodeId !== null) {
    visibleNodes = neighborhoodNodes(
      graph,
      controls.focusNodeId,
      controls.neighborhoodDepth as 1 | 2,
      filteredNodes,
      filteredEdges,
    );
  }

  let visibleEdges = filteredEdges.filter(
    (edgeId) => visibleNodes.has(graph.source(edgeId)) && visibleNodes.has(graph.target(edgeId)),
  );
  if (!filters.showOrphans) {
    const connected = new Set<string>();
    for (const edgeId of visibleEdges) {
      connected.add(graph.source(edgeId));
      connected.add(graph.target(edgeId));
    }
    if (controls.focusNodeId !== null) connected.add(controls.focusNodeId);
    visibleNodes = new Set([...visibleNodes].filter((nodeId) => connected.has(nodeId)));
    visibleEdges = visibleEdges.filter(
      (edgeId) => visibleNodes.has(graph.source(edgeId)) && visibleNodes.has(graph.target(edgeId)),
    );
  }

  const visibleNodeIds = [...visibleNodes].sort();
  const visibleNodeSet = new Set(visibleNodeIds);
  const searchResults = query.length === 0
    ? []
    : visibleNodeIds
        .map((nodeId) => ({ nodeId, score: searchScore(graph, nodeId, query) }))
        .filter((candidate): candidate is { nodeId: string; score: number } => candidate.score !== null)
        .sort((left, right) => left.score - right.score || left.nodeId.localeCompare(right.nodeId))
        .slice(0, MAX_SEARCH_RESULTS)
        .map(({ nodeId }) => nodeSummary(graph, nodeId));

  return {
    visibleNodeIds,
    visibleEdgeIds: visibleEdges
      .filter(
        (edgeId) => visibleNodeSet.has(graph.source(edgeId)) && visibleNodeSet.has(graph.target(edgeId)),
      )
      .sort(),
    searchResults,
  };
}

export function createExplorerShell(options: ExplorerShellOptions): ExplorerShell {
  const releaseId = validateInputGraph(options.graph);
  const projection = createRendererProjection(options.graph);
  let selectedNodeId: string | null = null;
  let destroyed = false;
  let controls: ExplorerViewControls = {
    query: "",
    focusNodeId: null,
    neighborhoodDepth: 0,
    filters: { ...DEFAULT_FILTERS },
  };
  let currentView = computeExplorerView(options.graph, controls);
  let visibleNodeSet = new Set(currentView.visibleNodeIds);
  let visibleEdgeSet = new Set(currentView.visibleEdgeIds);
  let searchResultSet = new Set(currentView.searchResults.map((item) => item.id));

  const settings: Readonly<Record<string, unknown>> = {
    allowInvalidContainer: false,
    defaultEdgeColor: "#94a3b8",
    defaultNodeColor: "#64748b",
    edgeReducer: (edgeId: string, data: Attributes) =>
      visibleEdgeSet.has(edgeId) ? data : { ...data, hidden: true },
    enableEdgeEvents: true,
    hideEdgesOnMove: true,
    hideLabelsOnMove: true,
    labelDensity: 0.08,
    labelRenderedSizeThreshold: 8,
    nodeReducer: (nodeId: string, data: Attributes) => {
      if (!visibleNodeSet.has(nodeId)) return { ...data, hidden: true };
      if (nodeId === selectedNodeId) {
        return {
          ...data,
          color: "#0f766e",
          forceLabel: true,
          highlighted: true,
          size: 8,
          zIndex: 2,
        };
      }
      if (searchResultSet.has(nodeId)) {
        return { ...data, forceLabel: true, highlighted: true, size: 6, zIndex: 1 };
      }
      return data;
    },
    renderEdgeLabels: false,
    renderLabels: true,
    zIndex: true,
  };
  const renderer = options.rendererFactory(projection, options.container, settings);

  const emitSelection = (): void => {
    options.onSelection?.(
      selectedNodeId === null ? null : selection(options.graph, selectedNodeId),
    );
  };
  const setSelection = (nodeId: string | null): void => {
    if (destroyed) throw new Error("Sigma explorer shell has been destroyed");
    if (nodeId !== null && !visibleNodeSet.has(nodeId)) {
      throw new TypeError("selected node is outside the visible ACL-safe graph");
    }
    selectedNodeId = nodeId;
    renderer.refresh();
    emitSelection();
  };
  const recompute = (): void => {
    if (destroyed) throw new Error("Sigma explorer shell has been destroyed");
    currentView = computeExplorerView(options.graph, controls);
    visibleNodeSet = new Set(currentView.visibleNodeIds);
    visibleEdgeSet = new Set(currentView.visibleEdgeIds);
    searchResultSet = new Set(currentView.searchResults.map((item) => item.id));
    if (selectedNodeId !== null && !visibleNodeSet.has(selectedNodeId)) {
      selectedNodeId = null;
      emitSelection();
    }
    renderer.refresh();
  };
  const clickNode = ({ node }: { node: string }): void => setSelection(node);
  const clickStage = (): void => setSelection(null);
  renderer.on("clickNode", clickNode);
  renderer.on("clickStage", clickStage);

  const originalTabIndex = options.container.getAttribute("tabindex");
  const originalRole = options.container.getAttribute("role");
  const originalLabel = options.container.getAttribute("aria-label");
  options.container.setAttribute("tabindex", "0");
  options.container.setAttribute("role", "application");
  options.container.setAttribute("aria-label", "Read-only knowledge graph explorer");

  const keydown = (event: KeyboardEvent): void => {
    const nodeIds = currentView.visibleNodeIds;
    if (nodeIds.length === 0) return;
    const current = selectedNodeId === null ? -1 : nodeIds.indexOf(selectedNodeId);
    let next: string | null | undefined;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      next = nodeIds[(current + 1 + nodeIds.length) % nodeIds.length];
    } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      next = nodeIds[(current - 1 + nodeIds.length) % nodeIds.length];
    } else if (event.key === "Home") {
      next = nodeIds[0];
    } else if (event.key === "End") {
      next = nodeIds.at(-1);
    } else if (event.key === "Escape") {
      next = null;
    } else {
      return;
    }
    event.preventDefault();
    setSelection(next ?? null);
  };
  options.container.addEventListener("keydown", keydown);

  const restoreAttribute = (name: string, value: string | null): void => {
    if (value === null) options.container.removeAttribute(name);
    else options.container.setAttribute(name, value);
  };

  return {
    clearFocus: () => {
      controls = { ...controls, focusNodeId: null, neighborhoodDepth: 0 };
      recompute();
    },
    clearSelection: () => setSelection(null),
    destroy: () => {
      if (destroyed) return;
      renderer.off("clickNode", clickNode);
      renderer.off("clickStage", clickStage);
      options.container.removeEventListener("keydown", keydown);
      renderer.kill();
      restoreAttribute("tabindex", originalTabIndex);
      restoreAttribute("role", originalRole);
      restoreAttribute("aria-label", originalLabel);
      destroyed = true;
    },
    focusNode: (nodeId: string, depth: 1 | 2 = 1) => {
      if (!options.graph.hasNode(nodeId)) {
        throw new TypeError("focus node is outside the ACL-safe graph");
      }
      if (depth !== 1 && depth !== 2) {
        throw new TypeError("focus depth must be one or two hops");
      }
      controls = { ...controls, focusNodeId: nodeId, neighborhoodDepth: depth };
      recompute();
    },
    getSelection: () =>
      selectedNodeId === null ? null : selection(options.graph, selectedNodeId),
    getState: () => ({
      schemaVersion: EXPLORER_SCHEMA,
      releaseId,
      selectedNodeId,
      nodeCount: options.graph.order,
      edgeCount: options.graph.size,
      visibleNodeCount: currentView.visibleNodeIds.length,
      visibleEdgeCount: currentView.visibleEdgeIds.length,
      textualFallback: currentView.visibleNodeIds
        .slice(0, MAX_TEXT_FALLBACK_NODES)
        .map((nodeId) => nodeSummary(options.graph, nodeId)),
      textualFallbackTruncated: currentView.visibleNodeIds.length > MAX_TEXT_FALLBACK_NODES,
      query: controls.query,
      searchResults: currentView.searchResults.map((item) => ({ ...item })),
      focusNodeId: controls.focusNodeId,
      neighborhoodDepth: controls.neighborhoodDepth,
      filters: {
        relationTypes: [...controls.filters.relationTypes],
        tags: [...controls.filters.tags],
        types: [...controls.filters.types],
        showOrphans: controls.filters.showOrphans,
      },
      readOnly: true,
    }),
    resetCamera: async () => {
      if (destroyed) throw new Error("Sigma explorer shell has been destroyed");
      await renderer.getCamera().animatedReset({ duration: 200 });
    },
    selectNode: (nodeId: string) => setSelection(nodeId),
    setFilters: (filters: Partial<ExplorerFilters>) => {
      controls = {
        ...controls,
        filters: normalizedFilters({ ...controls.filters, ...filters }),
      };
      recompute();
    },
    setSearchQuery: (query: string) => {
      controls = { ...controls, query: normalizedQuery(query) };
      recompute();
    },
  };
}

export async function createBrowserExplorerShell(
  options: BrowserExplorerShellOptions,
): Promise<ExplorerShell> {
  const sigmaModule = await import("sigma");
  const SigmaConstructor = sigmaModule.default as unknown as new (
    rendererGraph: ExplorerGraph,
    rendererContainer: HTMLElement,
    rendererSettings: Readonly<Record<string, unknown>>,
  ) => SigmaRendererLike;
  return createExplorerShell({
    ...options,
    rendererFactory: (graph, container, settings) =>
      new SigmaConstructor(graph, container, settings),
  });
}
