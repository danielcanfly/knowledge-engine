import { performance } from "node:perf_hooks";

import * as Graphology from "graphology";

import type { ExplorerGraph } from "../src/index.js";
import {
  createDeterministicLayout,
  createOverviewArtifact,
  performanceViolations,
  planProgressiveExpansion,
  semanticZoomPolicy,
  type PerformanceSample,
  type PerformanceTierName,
} from "../src/scale.js";

type Density = "sparse" | "medium" | "dense";

interface PayloadNode {
  id: string;
  tag: string;
  type: string;
}

interface PayloadEdge {
  id: string;
  source: string;
  target: string;
  relationType: string;
}

interface Fixture {
  tier: PerformanceTierName;
  density: Density;
}

const FIXTURES: Fixture[] = [
  { tier: "1k", density: "sparse" },
  { tier: "1k", density: "dense" },
  { tier: "10k", density: "sparse" },
  { tier: "10k", density: "medium" },
  { tier: "50k", density: "sparse" },
];

const NODE_COUNTS: Record<PerformanceTierName, number> = {
  "1k": 1_000,
  "10k": 10_000,
  "50k": 50_000,
};

const EDGE_MULTIPLIERS: Record<Density, number> = {
  sparse: 1,
  medium: 2,
  dense: 4,
};

function newGraph(releaseId: string): ExplorerGraph {
  const GraphConstructor = Graphology.default as unknown as new (options: {
    allowSelfLoops: boolean;
    multi: boolean;
    type: "mixed";
  }) => ExplorerGraph;
  const graph = new GraphConstructor({ allowSelfLoops: false, multi: true, type: "mixed" });
  graph.replaceAttributes({
    adapterSchemaVersion: "knowledge-os-graphology-adapter/v1",
    rendererNeutral: true,
    releaseId,
    manifestSha256: `${releaseId}-manifest`,
    sourceCommitSha: `${releaseId}-source`,
    foundationCommitSha: `${releaseId}-foundation`,
    contentSha256: `${releaseId}-content`,
    readOnly: true,
  });
  return graph;
}

function payload(tier: PerformanceTierName, density: Density): {
  nodes: PayloadNode[];
  edges: PayloadEdge[];
} {
  const nodeCount = NODE_COUNTS[tier];
  const nodes = Array.from({ length: nodeCount }, (_, index): PayloadNode => ({
    id: `concepts/${index.toString().padStart(6, "0")}`,
    tag: `community-${index % 100}`,
    type: index % 3 === 0 ? "Concept" : "Technique",
  }));
  const edgeCount = nodeCount * EDGE_MULTIPLIERS[density];
  const edges = Array.from({ length: edgeCount }, (_, index): PayloadEdge => {
    const sourceIndex = index % nodeCount;
    const step = 1 + Math.floor(index / nodeCount);
    const targetIndex = (sourceIndex + step) % nodeCount;
    return {
      id: `edge-${index.toString().padStart(7, "0")}`,
      source: nodes[sourceIndex]!.id,
      target: nodes[targetIndex]!.id,
      relationType: index % 2 === 0 ? "part_of" : "related_to",
    };
  });
  return { nodes, edges };
}

function importGraph(
  releaseId: string,
  parsed: { nodes: PayloadNode[]; edges: PayloadEdge[] },
): ExplorerGraph {
  const graph = newGraph(releaseId);
  for (const node of parsed.nodes) {
    graph.addNode(node.id, {
      aliases: [],
      audience: "public",
      conceptId: node.id,
      confidence: 0.9,
      description: "",
      sourcePath: `${node.id}.md`,
      status: "published",
      tags: [node.tag],
      title: node.id,
      type: node.type,
      xKosId: `ko_${node.id}`,
    });
  }
  for (const edge of parsed.edges) {
    graph.addDirectedEdgeWithKey(edge.id, edge.source, edge.target, {
      audience: "public",
      confidence: 0.9,
      directed: true,
      edgeId: edge.id,
      generatedInverse: false,
      relationType: edge.relationType,
    });
  }
  return graph;
}

function duration<T>(operation: () => T): { value: T; milliseconds: number } {
  const started = performance.now();
  const value = operation();
  return { value, milliseconds: performance.now() - started };
}

function percentile95(values: number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(sorted.length * 0.95) - 1)] ?? 0;
}

function latency(iterations: number, operation: () => void): number {
  const samples = Array.from({ length: iterations }, () => {
    const started = performance.now();
    operation();
    return performance.now() - started;
  });
  return percentile95(samples);
}

function runFixture(fixture: Fixture): PerformanceSample & { density: Density; violations: string[] } {
  const releaseId = `fixture-${fixture.tier}-${fixture.density}`;
  const compact = payload(fixture.tier, fixture.density);
  const serialized = JSON.stringify(compact);
  const parsed = duration(() => JSON.parse(serialized) as typeof compact);
  const imported = duration(() => importGraph(releaseId, parsed.value));
  const graph = imported.value;
  const layout = duration(() => createDeterministicLayout(graph));
  const overview = duration(() => createOverviewArtifact(graph, layout.value));
  const rootNodeId = compact.nodes[0]!.id;
  const neighborhoodP95Ms = latency(20, () => {
    planProgressiveExpansion(graph, {
      rootNodeId,
      depth: 2,
      batchNodeLimit: 100,
      batchEdgeLimit: 200,
    });
  });
  const panZoomP95Ms = latency(1_000, () => {
    semanticZoomPolicy({ cameraRatio: 2.5, nodeCount: graph.order, selected: false });
  });
  const selectionP95Ms = latency(1_000, () => {
    graph.hasNode(rootNodeId);
    graph.getNodeAttribute(rootNodeId, "title");
  });
  const sample: PerformanceSample = {
    tier: fixture.tier,
    nodeCount: graph.order,
    edgeCount: graph.size,
    payloadBytes: Buffer.byteLength(serialized),
    parseMs: parsed.milliseconds,
    importMs: imported.milliseconds,
    layoutMs: layout.milliseconds,
    overviewMs: overview.milliseconds,
    firstMeaningfulRenderMs: layout.milliseconds + overview.milliseconds,
    panZoomP95Ms,
    selectionP95Ms,
    neighborhoodP95Ms,
    memoryMiB: process.memoryUsage().heapUsed / 1024 / 1024,
    labelSuppressionRatio:
      overview.value.sourceNodeCount === 0
        ? 1
        : overview.value.suppressedNodeCount / overview.value.sourceNodeCount,
    edgeReductionRatio:
      overview.value.sourceEdgeCount === 0
        ? 1
        : overview.value.suppressedEdgeCount / overview.value.sourceEdgeCount,
  };
  return { ...sample, density: fixture.density, violations: performanceViolations(sample) };
}

let failed = false;
for (const fixture of FIXTURES) {
  const result = runFixture(fixture);
  console.log(JSON.stringify(result));
  if (result.violations.length > 0) failed = true;
}
if (failed) process.exitCode = 1;
