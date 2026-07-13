import type { AbstractGraph, Attributes } from "graphology-types";

export const EXPLORER_SCHEMA = "knowledge-os-sigma-explorer/v1";
export const MAX_TEXT_FALLBACK_NODES = 500;

export type ExplorerGraph = AbstractGraph<Attributes, Attributes, Attributes>;

export interface ExplorerNodeSummary {
  id: string;
  title: string;
  type: string;
}

export interface ExplorerShellState {
  schemaVersion: typeof EXPLORER_SCHEMA;
  releaseId: string;
  selectedNodeId: string | null;
  nodeCount: number;
  edgeCount: number;
  textualFallback: ExplorerNodeSummary[];
  textualFallbackTruncated: boolean;
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
  clearSelection(): void;
  destroy(): void;
  getSelection(): ExplorerSelection | null;
  getState(): ExplorerShellState;
  resetCamera(): Promise<void>;
  selectNode(nodeId: string): void;
}

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

export function createExplorerShell(options: ExplorerShellOptions): ExplorerShell {
  const releaseId = validateInputGraph(options.graph);
  const projection = createRendererProjection(options.graph);
  const nodeIds = projection.nodes().sort();
  let selectedNodeId: string | null = null;
  let destroyed = false;

  const settings: Readonly<Record<string, unknown>> = {
    allowInvalidContainer: false,
    defaultEdgeColor: "#94a3b8",
    defaultNodeColor: "#64748b",
    enableEdgeEvents: true,
    hideEdgesOnMove: true,
    hideLabelsOnMove: true,
    labelDensity: 0.08,
    labelRenderedSizeThreshold: 8,
    nodeReducer: (nodeId: string, data: Attributes) =>
      nodeId === selectedNodeId
        ? { ...data, color: "#0f766e", forceLabel: true, highlighted: true, size: 8, zIndex: 1 }
        : data,
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
    if (nodeId !== null && !options.graph.hasNode(nodeId)) {
      throw new TypeError("selected node is outside the ACL-safe graph");
    }
    selectedNodeId = nodeId;
    renderer.refresh();
    emitSelection();
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
    getSelection: () =>
      selectedNodeId === null ? null : selection(options.graph, selectedNodeId),
    getState: () => ({
      schemaVersion: EXPLORER_SCHEMA,
      releaseId,
      selectedNodeId,
      nodeCount: options.graph.order,
      edgeCount: options.graph.size,
      textualFallback: nodeIds
        .slice(0, MAX_TEXT_FALLBACK_NODES)
        .map((nodeId) => nodeSummary(options.graph, nodeId)),
      textualFallbackTruncated: nodeIds.length > MAX_TEXT_FALLBACK_NODES,
      readOnly: true,
    }),
    resetCamera: async () => {
      if (destroyed) throw new Error("Sigma explorer shell has been destroyed");
      await renderer.getCamera().animatedReset({ duration: 200 });
    },
    selectNode: (nodeId: string) => setSelection(nodeId),
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
