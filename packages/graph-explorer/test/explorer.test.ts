import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import * as Graphology from "graphology";

import {
  EXPLORER_SCHEMA,
  MAX_TEXT_FALLBACK_NODES,
  createExplorerShell,
  createRendererProjection,
  type ExplorerGraph,
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
    releaseId: "release-m19-3",
    readOnly: true,
  });
  for (let index = 0; index < nodeCount; index += 1) {
    const id = `concepts/${index.toString().padStart(3, "0")}`;
    value.addNode(id, {
      aliases: [],
      audience: "public",
      conceptId: id,
      confidence: 0.9,
      description: `${id} description`,
      sourcePath: `${id}.md`,
      status: "published",
      tags: ["agents"],
      title: `Concept ${index}`,
      type: "Concept",
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

test("supports click selection and stage deselection on the ACL-safe graph", () => {
  const { explorer, renderer, selections } = shell();
  renderer.emit("clickNode", { node: "concepts/001" });
  assert.equal(explorer.getState().selectedNodeId, "concepts/001");
  assert.equal(explorer.getSelection()?.sourcePath, "concepts/001.md");
  renderer.emit("clickStage");
  assert.equal(explorer.getSelection(), null);
  assert.deepEqual(selections, ["concepts/001", null]);
  assert.throws(() => explorer.selectNode("concepts/restricted"), /outside the ACL-safe graph/);
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
    zIndex: 1,
  });
  assert.equal(source.getNodeAttribute("concepts/000", "color"), undefined);
  assert.equal(renderer.settings.renderEdgeLabels, false);
  assert.equal(renderer.settings.hideEdgesOnMove, true);
});

test("exposes exact release identity and a bounded textual fallback", () => {
  const { explorer } = shell(graph(MAX_TEXT_FALLBACK_NODES + 1));
  const state = explorer.getState();
  assert.equal(state.schemaVersion, EXPLORER_SCHEMA);
  assert.equal(state.releaseId, "release-m19-3");
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
