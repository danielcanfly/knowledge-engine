import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import * as Graphology from "graphology";

import {
  EXPLORER_SCHEMA,
  MAX_SEARCH_QUERY_LENGTH,
  MAX_TEXT_FALLBACK_NODES,
  computeExplorerView,
  createExplorerShell,
  createRendererProjection,
  type ExplorerGraph,
  type ExplorerViewControls,
  type RendererFactory,
} from "../src/index.js";

function graph(nodeCount = 2): ExplorerGraph {
  const GraphConstructor = Graphology.default as unknown as new (options: {
    allowSelfLoops: boolean;
    multi: boolean;
    type: "mixed";
  }) => ExplorerGraph;
  const value = new GraphConstructor({ allowSelfLoops: false, multi: true, type: "mixed" });
  value.replaceAttributes({
    adapterSchemaVersion: "knowledge-os-graphology-adapter/v1",
    rendererNeutral: true,
    releaseId: "release-m19-4",
    readOnly: true,
  });
  const titles = [
    "Agent Systems",
    "Retrieval Augmented Generation",
    "Vector Embeddings",
    "Security Governance",
    "Detached Concept",
  ];
  const types = ["Concept", "Technique", "Technique", "Policy", "Concept"];
  const tags = [
    ["agents"],
    ["agents", "retrieval"],
    ["retrieval", "vectors"],
    ["governance"],
    ["agents"],
  ];
  const aliases = [[], ["RAG"], ["Embeddings"], ["Safety Policy"], []];
  for (let index = 0; index < nodeCount; index += 1) {
    const id = `concepts/${index.toString().padStart(3, "0")}`;
    value.addNode(id, {
      aliases: aliases[index] ?? [],
      audience: "public",
      conceptId: id,
      confidence: 0.9,
      description: `${titles[index] ?? `Concept ${index}`} description`,
      sourcePath: `${id}.md`,
      status: "published",
      tags: tags[index] ?? ["agents"],
      title: titles[index] ?? `Concept ${index}`,
      type: types[index] ?? "Concept",
      xKosId: `ko_${index}`,
    });
  }
  if (nodeCount >= 2) {
    value.addDirectedEdgeWithKey("edge-0", "concepts/000", "concepts/001", {
      audience: "public",
      confidence: 0.9,
      directed: true,
      edgeId: "edge-0",
      generatedInverse: false,
      relationType: "part_of",
    });
  }
  if (nodeCount >= 3) {
    value.addDirectedEdgeWithKey("edge-1", "concepts/001", "concepts/002", {
      audience: "public",
      confidence: 0.9,
      directed: true,
      edgeId: "edge-1",
      generatedInverse: false,
      relationType: "depends_on",
    });
  }
  if (nodeCount >= 4) {
    value.addDirectedEdgeWithKey("edge-2", "concepts/002", "concepts/003", {
      audience: "public",
      confidence: 0.9,
      directed: true,
      edgeId: "edge-2",
      generatedInverse: false,
      relationType: "related_to",
    });
  }
  return value;
}

type NodeListener = (payload: { node: string }) => void;
type StageListener = () => void;

class FakeRenderer {
  readonly listeners = new Map<string, NodeListener | StageListener>();
  killed = false;
  refreshed = 0;
  resets = 0;

  constructor(
    readonly graph: ExplorerGraph,
    readonly settings: Readonly<Record<string, unknown>>,
  ) {}

  getCamera() {
    return {
      animatedReset: () => {
        this.resets += 1;
      },
    };
  }

  kill(): void {
    this.killed = true;
  }

  off(event: "clickNode", listener: NodeListener): this;
  off(event: "clickStage", listener: StageListener): this;
  off(event: string): this {
    this.listeners.delete(event);
    return this;
  }

  on(event: "clickNode", listener: NodeListener): this;
  on(event: "clickStage", listener: StageListener): this;
  on(event: string, listener: NodeListener | StageListener): this {
    this.listeners.set(event, listener);
    return this;
  }

  refresh(): this {
    this.refreshed += 1;
    return this;
  }

  emit(event: "clickNode", payload: { node: string }): void;
  emit(event: "clickStage"): void;
  emit(event: string, payload?: { node: string }): void {
    const listener = this.listeners.get(event);
    if (event === "clickNode" && payload !== undefined) {
      (listener as NodeListener | undefined)?.(payload);
    } else {
      (listener as StageListener | undefined)?.();
    }
  }
}

class FakeContainer {
  readonly attributes = new Map<string, string>();
  readonly listeners = new Map<string, EventListener>();

  addEventListener(name: string, listener: EventListener): void {
    this.listeners.set(name, listener);
  }

  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }

  removeAttribute(name: string): void {
    this.attributes.delete(name);
  }

  removeEventListener(name: string): void {
    this.listeners.delete(name);
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  key(key: string): boolean {
    let prevented = false;
    this.listeners.get("keydown")?.({
      key,
      preventDefault: () => {
        prevented = true;
      },
    } as unknown as Event);
    return prevented;
  }
}

function shell(source = graph()) {
  const container = new FakeContainer();
  let renderer: FakeRenderer | undefined;
  const rendererFactory: RendererFactory = (rendererGraph, _container, settings) => {
    renderer = new FakeRenderer(rendererGraph, settings);
    return renderer;
  };
  const selections: Array<string | null> = [];
  const explorer = createExplorerShell({
    graph: source,
    container: container as unknown as HTMLElement,
    rendererFactory,
    onSelection: (selected) => selections.push(selected?.id ?? null),
  });
  assert.ok(renderer);
  return { container, explorer, renderer, selections };
}

function controls(overrides: Partial<ExplorerViewControls> = {}): ExplorerViewControls {
  return {
    query: "",
    focusNodeId: null,
    neighborhoodDepth: 0,
    filters: { relationTypes: [], tags: [], types: [], showOrphans: true },
    ...overrides,
  };
}

test("creates a deterministic renderer projection without mutating canonical attributes", () => {
  const source = graph();
  const before = source.export();
  const first = createRendererProjection(source);
  const second = createRendererProjection(source);
  assert.deepEqual(source.export(), before);
  assert.deepEqual(first.export(), second.export());
  assert.equal(source.hasNodeAttribute("concepts/000", "x"), false);
  assert.equal(first.hasNodeAttribute("concepts/000", "x"), true);
  assert.equal(first.getNodeAttribute("concepts/000", "color"), "#64748b");
  assert.equal(first.getEdgeAttribute("edge-0", "label"), "part_of");
});

test("rejects graphs that are not read-only, renderer-neutral, and release-bound", () => {
  for (const attribute of ["readOnly", "rendererNeutral", "releaseId"]) {
    const value = graph();
    value.removeAttribute(attribute);
    assert.throws(() => createRendererProjection(value), /read-only|renderer-neutral|releaseId/);
  }
});

test("supports click selection and stage deselection on the visible ACL-safe graph", () => {
  const { explorer, renderer, selections } = shell();
  renderer.emit("clickNode", { node: "concepts/001" });
  assert.equal(explorer.getState().selectedNodeId, "concepts/001");
  assert.equal(explorer.getSelection()?.sourcePath, "concepts/001.md");
  renderer.emit("clickStage");
  assert.equal(explorer.getSelection(), null);
  assert.deepEqual(selections, ["concepts/001", null]);
  assert.throws(() => explorer.selectNode("concepts/restricted"), /visible ACL-safe graph/);
});

test("provides deterministic keyboard selection and accessible container semantics", () => {
  const { container, explorer } = shell();
  assert.equal(container.getAttribute("role"), "application");
  assert.equal(container.getAttribute("tabindex"), "0");
  assert.equal(container.key("ArrowDown"), true);
  assert.equal(explorer.getState().selectedNodeId, "concepts/000");
  container.key("End");
  assert.equal(explorer.getState().selectedNodeId, "concepts/001");
  container.key("Escape");
  assert.equal(explorer.getState().selectedNodeId, null);
  assert.equal(container.key("a"), false);
});

test("uses renderer reducers for selection rather than canonical graph mutation", () => {
  const source = graph();
  const { explorer, renderer } = shell(source);
  explorer.selectNode("concepts/000");
  const reducer = renderer.settings.nodeReducer as (
    id: string,
    attributes: Record<string, unknown>,
  ) => Record<string, unknown>;
  assert.deepEqual(reducer("concepts/000", { color: "#64748b", size: 5 }), {
    color: "#0f766e",
    forceLabel: true,
    highlighted: true,
    size: 8,
    zIndex: 2,
  });
  assert.equal(source.getNodeAttribute("concepts/000", "color"), undefined);
  assert.equal(renderer.settings.renderEdgeLabels, false);
  assert.equal(renderer.settings.hideEdgesOnMove, true);
});

test("exposes exact release identity and a bounded textual fallback", () => {
  const { explorer } = shell(graph(MAX_TEXT_FALLBACK_NODES + 1));
  const state = explorer.getState();
  assert.equal(state.schemaVersion, EXPLORER_SCHEMA);
  assert.equal(state.releaseId, "release-m19-4");
  assert.equal(state.readOnly, true);
  assert.equal(state.textualFallback.length, MAX_TEXT_FALLBACK_NODES);
  assert.equal(state.textualFallbackTruncated, true);
});

test("resets the camera and performs idempotent teardown", async () => {
  const container = new FakeContainer();
  container.setAttribute("role", "region");
  let renderer: FakeRenderer | undefined;
  const explorer = createExplorerShell({
    graph: graph(),
    container: container as unknown as HTMLElement,
    rendererFactory: (rendererGraph, _container, settings) => {
      renderer = new FakeRenderer(rendererGraph, settings);
      return renderer;
    },
  });
  assert.ok(renderer);
  await explorer.resetCamera();
  assert.equal(renderer.resets, 1);
  explorer.destroy();
  explorer.destroy();
  assert.equal(renderer.killed, true);
  assert.equal(renderer.listeners.size, 0);
  assert.equal(container.getAttribute("role"), "region");
  assert.equal(container.listeners.size, 0);
  await assert.rejects(explorer.resetCamera(), /destroyed/);
});

test("searches normalized canonical fields with deterministic bounded ranking", () => {
  const source = graph(5);
  const byAlias = computeExplorerView(source, controls({ query: " rag " }));
  assert.deepEqual(byAlias.searchResults.map((item) => item.id), ["concepts/001"]);
  const byTag = computeExplorerView(source, controls({ query: "retrieval" }));
  assert.deepEqual(byTag.searchResults.map((item) => item.id), [
    "concepts/001",
    "concepts/002",
  ]);
  assert.throws(
    () => computeExplorerView(source, controls({ query: "x".repeat(MAX_SEARCH_QUERY_LENGTH + 1) })),
    /at most 160/,
  );
});

test("focuses deterministic one- and two-hop neighborhoods without following direction", () => {
  const source = graph(5);
  const oneHop = computeExplorerView(
    source,
    controls({ focusNodeId: "concepts/000", neighborhoodDepth: 1 }),
  );
  assert.deepEqual(oneHop.visibleNodeIds, ["concepts/000", "concepts/001"]);
  assert.deepEqual(oneHop.visibleEdgeIds, ["edge-0"]);
  const twoHop = computeExplorerView(
    source,
    controls({ focusNodeId: "concepts/000", neighborhoodDepth: 2 }),
  );
  assert.deepEqual(twoHop.visibleNodeIds, [
    "concepts/000",
    "concepts/001",
    "concepts/002",
  ]);
  assert.deepEqual(twoHop.visibleEdgeIds, ["edge-0", "edge-1"]);
});

test("applies relation filters before bounded neighborhood expansion", () => {
  const view = computeExplorerView(
    graph(5),
    controls({
      focusNodeId: "concepts/000",
      neighborhoodDepth: 2,
      filters: {
        relationTypes: ["part_of"],
        tags: [],
        types: [],
        showOrphans: true,
      },
    }),
  );
  assert.deepEqual(view.visibleNodeIds, ["concepts/000", "concepts/001"]);
  assert.deepEqual(view.visibleEdgeIds, ["edge-0"]);
});

test("uses OR within tag and type filters and AND across dimensions", () => {
  const view = computeExplorerView(
    graph(5),
    controls({
      filters: {
        relationTypes: [],
        tags: ["retrieval", "governance"],
        types: ["Technique"],
        showOrphans: true,
      },
    }),
  );
  assert.deepEqual(view.visibleNodeIds, ["concepts/001", "concepts/002"]);
  assert.deepEqual(view.visibleEdgeIds, ["edge-1"]);
});

test("hides orphan nodes explicitly while preserving an isolated focus node", () => {
  const source = graph(5);
  const withoutOrphans = computeExplorerView(
    source,
    controls({
      filters: { relationTypes: [], tags: [], types: [], showOrphans: false },
    }),
  );
  assert.equal(withoutOrphans.visibleNodeIds.includes("concepts/004"), false);
  const isolatedFocus = computeExplorerView(
    source,
    controls({
      focusNodeId: "concepts/004",
      neighborhoodDepth: 1,
      filters: { relationTypes: [], tags: [], types: [], showOrphans: false },
    }),
  );
  assert.deepEqual(isolatedFocus.visibleNodeIds, ["concepts/004"]);
});

test("updates renderer-only visibility, search, focus, and filters without canonical mutation", () => {
  const source = graph(5);
  const before = source.export();
  const { explorer, renderer, selections } = shell(source);
  explorer.selectNode("concepts/004");
  explorer.setFilters({ showOrphans: false });
  assert.equal(explorer.getSelection(), null);
  assert.deepEqual(selections, ["concepts/004", null]);
  explorer.setSearchQuery("rag");
  assert.deepEqual(explorer.getState().searchResults.map((item) => item.id), ["concepts/001"]);
  explorer.focusNode("concepts/000", 2);
  assert.equal(explorer.getState().visibleNodeCount, 3);
  const nodeReducer = renderer.settings.nodeReducer as (
    id: string,
    attributes: Record<string, unknown>,
  ) => Record<string, unknown>;
  const edgeReducer = renderer.settings.edgeReducer as (
    id: string,
    attributes: Record<string, unknown>,
  ) => Record<string, unknown>;
  assert.equal(nodeReducer("concepts/004", {}).hidden, true);
  assert.equal(edgeReducer("edge-2", {}).hidden, true);
  explorer.clearFocus();
  assert.equal(explorer.getState().focusNodeId, null);
  assert.deepEqual(source.export(), before);
});

test("rejects unbounded controls and nodes outside the ACL-safe graph", () => {
  const { explorer } = shell(graph(5));
  assert.throws(() => explorer.focusNode("concepts/restricted"), /outside the ACL-safe graph/);
  assert.throws(() => explorer.focusNode("concepts/000", 3 as 1), /one or two hops/);
  assert.throws(
    () => explorer.setFilters({ tags: Array.from({ length: 51 }, (_, index) => `tag-${index}`) }),
    /at most 50/,
  );
});

test("pins Sigma v3 locally and exposes no network or mutation authority", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../../package.json", import.meta.url), "utf8"),
  ) as { dependencies: Record<string, string> };
  assert.deepEqual(packageJson.dependencies, { graphology: "0.26.0", sigma: "3.0.3" });
  const source = await readFile(new URL("../../src/index.ts", import.meta.url), "utf8");
  assert.equal(/https?:\/\//.test(source), false);
  assert.equal(/\b(?:fetch|XMLHttpRequest|WebSocket)\b/.test(source), false);
  assert.equal(/\b(?:POST|PUT|PATCH|DELETE)\b/.test(source), false);
});
