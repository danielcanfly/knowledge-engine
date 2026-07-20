import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  knowledgeGraphV2ToGraphology,
  type KnowledgeGraphV2,
} from "../src/index.js";

const CANONICAL_GRAPH_URL = new URL(
  "../../../../pilot/m24/canonical-release/artifacts/graph-v2.json",
  import.meta.url,
);
const RELEASE_ID = "20260720T160000Z-46137c97263e";

async function canonicalGraph(): Promise<KnowledgeGraphV2> {
  return JSON.parse(await readFile(CANONICAL_GRAPH_URL, "utf8")) as KnowledgeGraphV2;
}

test("adapts the M24 P2 canonical Graph v2 release for Sigma readiness", async () => {
  const input = await canonicalGraph();
  const graph = knowledgeGraphV2ToGraphology(input, {
    expectedReleaseId: RELEASE_ID,
  });

  assert.equal(graph.getAttribute("releaseId"), RELEASE_ID);
  assert.equal(graph.getAttribute("readOnly"), true);
  assert.equal(graph.type, "mixed");
  assert.equal(graph.order, 20);
  assert.equal(graph.size, 28);
  assert.equal(
    graph.nodes().every((nodeId) => graph.getNodeAttribute(nodeId, "conceptId") === nodeId),
    true,
  );
  assert.equal(graph.hasNode("concepts/harness"), true);
});

test("canonical Graph v2 supports alias search and typed edge filtering", async () => {
  const input = await canonicalGraph();
  const graph = knowledgeGraphV2ToGraphology(input, {
    expectedReleaseId: RELEASE_ID,
  });

  const aliasMatches = graph.nodes().filter((nodeId) => {
    const aliases = graph.getNodeAttribute(nodeId, "aliases") as string[];
    return aliases.some((alias) => alias === "run authority");
  });
  const requiresEdges = graph
    .edges()
    .filter((edgeId) => graph.getEdgeAttribute(edgeId, "relationType") === "requires");

  assert.deepEqual(aliasMatches, ["concepts/canonical-run-authority"]);
  assert.equal(requiresEdges.length > 0, true);
  assert.equal(
    requiresEdges.every((edgeId) => graph.getEdgeAttribute(edgeId, "directed") === true),
    true,
  );
});

test("canonical Graph v2 remains renderer neutral before Sigma owns layout state", async () => {
  const input = await canonicalGraph();
  const graph = knowledgeGraphV2ToGraphology(input, {
    expectedReleaseId: RELEASE_ID,
  });
  const rendererFields = new Set([
    "color",
    "coordinates",
    "hidden",
    "labelColor",
    "sigmaColor",
    "size",
    "x",
    "y",
  ]);

  for (const nodeId of graph.nodes()) {
    const attributes = Object.keys(graph.getNodeAttributes(nodeId));
    assert.equal(attributes.some((field) => rendererFields.has(field)), false);
  }
  for (const edgeId of graph.edges()) {
    const attributes = Object.keys(graph.getEdgeAttributes(edgeId));
    assert.equal(attributes.some((field) => rendererFields.has(field)), false);
  }
});
