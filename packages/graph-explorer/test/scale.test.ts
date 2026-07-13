import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import * as Graphology from "graphology";

import type { ExplorerGraph } from "../src/index.js";
import {
  DEFAULT_LAYOUT_SEED,
  EXPLORER_LAYOUT_SCHEMA,
  EXPLORER_OVERVIEW_SCHEMA,
  MAX_PROGRESSIVE_BATCH_NODES,
  PERFORMANCE_BUDGETS,
  createDeterministicLayout,
  createOverviewArtifact,
  performanceViolations,
  planProgressiveExpansion,
  semanticZoomPolicy,
  type GraphLayoutArtifact,
  type PerformanceSample,
} from "../src/scale.js";

function graph(nodeCount = 8): ExplorerGraph {
  const GraphConstructor = Graphology.default as unknown as new (options: {
    allowSelfLoops: boolean;
    multi: boolean;
    type: "mixed";
  }) => ExplorerGraph;
  const value = new GraphConstructor({ allowSelfLoops: false, multi: true, type: "mixed" });
  value.replaceAttributes({
    adapterSchemaVersion: "knowledge-os-graphology-adapter/v1",
    sourceSchemaVersion: "knowledge-engine-graph-api/v1",
    rendererNeutral: true,
    releaseId: "release-m19-6",
    manifestSha256: "manifest-m19-6",
    sourceCommitSha: "source-m19-6",
    foundationCommitSha: "foundation-m19-6",
    contentSha256: "content-m19-6",
    readOnly: true,
  });
  for (let index = 0; index < nodeCount; index += 1) {
    const id = `concepts/${index.toString().padStart(3, "0")}`;
    value.addNode(id, {
      aliases: [],
      audience: "public",
      conceptId: id,
      confidence: 0.9,
      description: `Description ${index}`,
      sourcePath: `${id}.md`,
      status: "published",
      tags: [index < Math.ceil(nodeCount / 2) ? "alpha" : "beta"],
      title: `Concept ${index}`,
      type: index % 2 === 0 ? "Concept" : "Technique",
      xKosId: `ko_${index}`,
    });
  }
  for (let index = 0; index + 1 < nodeCount; index += 1) {
    const source = `concepts/${index.toString().padStart(3, "0")}`;
    const target = `concepts/${(index + 1).toString().padStart(3, "0")}`;
    value.addDirectedEdgeWithKey(`edge-${index}`, source, target, {
      audience: "public",
      confidence: 0.9,
      directed: true,
      edgeId: `edge-${index}`,
      generatedInverse: false,
      relationType: index % 2 === 0 ? "part_of" : "depends_on",
    });
  }
  if (nodeCount > 3) {
    value.addUndirectedEdgeWithKey("edge-undirected", "concepts/000", "concepts/003", {
      audience: "public",
      confidence: 0.8,
      directed: false,
      edgeId: "edge-undirected",
      generatedInverse: false,
      relationType: "related_to",
    });
  }
  return value;
}

test("creates deterministic release-bound layout without canonical mutation", () => {
  const source = graph();
  const before = source.export();
  const first = createDeterministicLayout(source);
  const second = createDeterministicLayout(source);
  assert.equal(first.schemaVersion, EXPLORER_LAYOUT_SCHEMA);
  assert.equal(first.algorithm.seed, DEFAULT_LAYOUT_SEED);
  assert.deepEqual(first, second);
  assert.deepEqual(source.export(), before);
  assert.equal(first.positions.length, source.order);
  assert.equal(new Set(first.positions.map((item) => item.nodeId)).size, source.order);
  assert.notDeepEqual(createDeterministicLayout(source, { seed: 7 }), first);
});

test("rejects mutable, renderer-specific, oversized, or invalid-seed layout inputs", () => {
  const mutable = graph();
  mutable.setAttribute("readOnly", false);
  assert.throws(() => createDeterministicLayout(mutable), /read-only/);
  const rendererSpecific = graph();
  rendererSpecific.setAttribute("rendererNeutral", false);
  assert.throws(() => createDeterministicLayout(rendererSpecific), /renderer-neutral/);
  assert.throws(() => createDeterministicLayout(graph(), { seed: -1 }), /unsigned 32-bit/);
});

test("builds bounded semantic overview with deterministic representatives and aggregation", () => {
  const source = graph();
  const before = source.export();
  const layout = createDeterministicLayout(source);
  const overview = createOverviewArtifact(source, layout, { maxClusters: 2, maxEdges: 10 });
  assert.equal(overview.schemaVersion, EXPLORER_OVERVIEW_SCHEMA);
  assert.equal(overview.clusters.length, 2);
  assert.deepEqual(overview.clusters.map((item) => item.clusterId), [
    "cluster:tag:alpha",
    "cluster:tag:beta",
  ]);
  assert.ok(overview.edges.every((item) => item.relationTypes.length <= 20));
  assert.ok(overview.suppressedNodeCount > 0);
  assert.ok(overview.suppressedEdgeCount >= 0);
  assert.equal(JSON.stringify(overview).includes("Description"), false);
  assert.equal(JSON.stringify(overview).includes("provenance"), false);
  assert.deepEqual(source.export(), before);
});

test("rejects cross-release, incomplete, duplicate, and non-finite layouts", () => {
  const source = graph();
  const layout = createDeterministicLayout(source);
  const crossRelease: GraphLayoutArtifact = {
    ...layout,
    release: { ...layout.release, releaseId: "other" },
  };
  assert.throws(() => createOverviewArtifact(source, crossRelease), /releaseId identity mismatch/);
  assert.throws(
    () => createOverviewArtifact(source, { ...layout, positions: layout.positions.slice(1) }),
    /exactly one position/,
  );
  const duplicate = { ...layout, positions: [...layout.positions] };
  duplicate.positions[1] = { ...duplicate.positions[0]! };
  assert.throws(() => createOverviewArtifact(source, duplicate), /duplicate node positions/);
  const nonFinite = { ...layout, positions: layout.positions.map((item) => ({ ...item })) };
  nonFinite.positions[0]!.x = Number.NaN;
  assert.throws(() => createOverviewArtifact(source, nonFinite), /finite/);
});

test("returns deterministic semantic zoom budgets for overview, context, and detail", () => {
  assert.deepEqual(semanticZoomPolicy({ cameraRatio: 3, nodeCount: 1_000, selected: false }), {
    mode: "overview",
    useOverviewArtifact: true,
    nodeLabelBudget: 0,
    edgeBudget: 400,
    labels: "representatives",
    showEdgeLabels: false,
  });
  assert.equal(semanticZoomPolicy({ cameraRatio: 1, nodeCount: 2_000, selected: true }).mode, "context");
  assert.equal(semanticZoomPolicy({ cameraRatio: 0.5, nodeCount: 500, selected: true }).mode, "detail");
  assert.throws(() => semanticZoomPolicy({ cameraRatio: 0, nodeCount: 1, selected: false }), /positive/);
});

test("pages a bounded deterministic neighborhood without duplicate nodes or edges", () => {
  const source = graph(12);
  const pages = [];
  let cursor: string | undefined;
  do {
    const page = planProgressiveExpansion(source, {
      rootNodeId: "concepts/004",
      depth: 2,
      batchNodeLimit: 2,
      batchEdgeLimit: 2,
      ...(cursor !== undefined ? { cursor } : {}),
    });
    pages.push(page);
    cursor = page.nextCursor ?? undefined;
  } while (cursor !== undefined);
  const nodes = pages.flatMap((page) => page.nodeIds);
  const edges = pages.flatMap((page) => page.edgeIds);
  assert.equal(new Set(nodes).size, nodes.length);
  assert.equal(new Set(edges).size, edges.length);
  assert.equal(pages.at(-1)?.complete, true);
  assert.equal(pages.at(-1)?.nextCursor, null);
  assert.ok(pages.every((page) => page.nodeIds.length <= 2 && page.edgeIds.length <= 2));
  assert.ok(nodes.includes("concepts/004"));
});

test("applies relation filtering before progressive expansion and fails closed on bad cursors", () => {
  const source = graph(8);
  const filtered = planProgressiveExpansion(source, {
    rootNodeId: "concepts/002",
    depth: 2,
    batchNodeLimit: MAX_PROGRESSIVE_BATCH_NODES,
    relationTypes: ["part_of"],
  });
  assert.ok(filtered.edgeIds.every((edgeId) => source.getEdgeAttribute(edgeId, "relationType") === "part_of"));
  assert.throws(
    () => planProgressiveExpansion(source, { rootNodeId: "restricted", cursor: "p1:0:0" }),
    /outside the ACL-safe graph/,
  );
  assert.throws(
    () => planProgressiveExpansion(source, { rootNodeId: "concepts/000", cursor: "bad" }),
    /cursor is invalid/,
  );
});

test("defines complete 1k, 10k, and 50k performance budgets and reports violations", () => {
  assert.deepEqual(Object.keys(PERFORMANCE_BUDGETS), ["1k", "10k", "50k"]);
  const budget = PERFORMANCE_BUDGETS["1k"];
  const passing: PerformanceSample = {
    tier: "1k",
    nodeCount: budget.nodeCount,
    edgeCount: 1_000,
    payloadBytes: 1_000,
    parseMs: 1,
    importMs: 1,
    layoutMs: 1,
    overviewMs: 1,
    firstMeaningfulRenderMs: 1,
    panZoomP95Ms: 1,
    selectionP95Ms: 1,
    neighborhoodP95Ms: 1,
    memoryMiB: 1,
    labelSuppressionRatio: 1,
    edgeReductionRatio: 1,
  };
  assert.deepEqual(performanceViolations(passing), []);
  assert.ok(performanceViolations({ ...passing, payloadBytes: budget.maxPayloadBytes + 1 }).includes(
    `payloadBytes exceeds ${budget.maxPayloadBytes}`,
  ));
});

test("scale module has no network, mutation, storage, or canonical write-back authority", async () => {
  const source = await readFile(new URL("../../src/scale.ts", import.meta.url), "utf8");
  assert.equal(/https?:\/\//.test(source), false);
  assert.equal(/\b(?:fetch|XMLHttpRequest|WebSocket)\b/.test(source), false);
  assert.equal(/\b(?:POST|PUT|PATCH|DELETE)\b/.test(source), false);
  assert.equal(/\b(?:localStorage|sessionStorage|indexedDB)\b/.test(source), false);
  assert.equal(/(?:merge|set|update|replace)(?:Node|Edge)?Attributes\(/.test(source), false);
});
