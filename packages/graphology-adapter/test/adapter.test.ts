import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  GRAPH_API_SCHEMA,
  KNOWLEDGE_GRAPH_V2_SCHEMA,
  graphApiPayloadToGraphology,
  knowledgeGraphV2ToGraphology,
  type GraphApiPayload,
  type KnowledgeGraphV2,
} from "../src/index.js";

function node(id: string, audience = "public") {
  return {
    concept_id: id,
    x_kos_id: `ko_${id}`,
    title: id,
    description: `${id} description`,
    type: "Concept",
    audience,
    status: "published",
    confidence: 0.9,
    tags: ["agents"],
    aliases: [`${id} alias`],
    path: `${id}.md`,
    provenance_record: `provenance/${id}.json`,
  };
}

function edge(id: string, source: string, target: string, directed: boolean) {
  return {
    edge_id: id,
    source,
    target,
    relation_type: directed ? "part_of" : "complements",
    directed,
    audience: "public",
    confidence: 0.9,
    generated_inverse: false,
    review_id: "review-private",
    provenance_record: "provenance/private.json",
  };
}

function canonical(): KnowledgeGraphV2 {
  return {
    schema_version: KNOWLEDGE_GRAPH_V2_SCHEMA,
    release: {
      release_id: "release-m19",
      source_commit_sha: "a".repeat(40),
      foundation_commit_sha: "b".repeat(40),
      content_sha256: "c".repeat(64),
    },
    nodes: [node("concepts/b"), node("concepts/a")],
    edges: [
      edge("edge-undirected", "concepts/a", "concepts/b", false),
      edge("edge-directed", "concepts/a", "concepts/b", true),
    ],
    renderer_neutral: true,
  };
}

function apiPayload(): GraphApiPayload {
  const input = canonical();
  return {
    schema_version: GRAPH_API_SCHEMA,
    release: {
      release_id: input.release.release_id,
      manifest_sha256: "d".repeat(64),
      source_commit_sha: input.release.source_commit_sha,
      foundation_commit_sha: input.release.foundation_commit_sha,
      content_sha256: input.release.content_sha256,
    },
    read_only: true,
    nodes: input.nodes.map(({ path, ...value }) => ({ ...value, source_path: path })),
    edges: input.edges,
  };
}

test("imports directed and undirected edges into an exact mixed graph", () => {
  const graph = knowledgeGraphV2ToGraphology(canonical(), {
    expectedReleaseId: "release-m19",
  });
  assert.equal(graph.type, "mixed");
  assert.equal(graph.multi, true);
  assert.equal(graph.order, 2);
  assert.equal(graph.size, 2);
  assert.equal(graph.hasDirectedEdge("edge-directed"), true);
  assert.equal(graph.hasUndirectedEdge("edge-undirected"), true);
  assert.deepEqual(graph.nodes(), ["concepts/a", "concepts/b"]);
  assert.deepEqual(graph.edges(), ["edge-directed", "edge-undirected"]);
  assert.equal(graph.getAttribute("releaseId"), "release-m19");
  assert.equal(graph.getAttribute("readOnly"), true);
});

test("adapts an exact M19.1 ACL-safe API payload", () => {
  const graph = graphApiPayloadToGraphology(apiPayload(), {
    expectedReleaseId: "release-m19",
    expectedManifestSha256: "d".repeat(64),
  });
  assert.equal(graph.getAttribute("sourceSchemaVersion"), GRAPH_API_SCHEMA);
  assert.equal(graph.getAttribute("manifestSha256"), "d".repeat(64));
  assert.equal(graph.getNodeAttribute("concepts/a", "conceptId"), "concepts/a");
  assert.equal(graph.getEdgeAttribute("edge-directed", "edgeId"), "edge-directed");
});

test("copies only approved canonical attributes and does not mutate input", () => {
  const input = canonical();
  const before = structuredClone(input);
  const graph = knowledgeGraphV2ToGraphology(input);
  assert.deepEqual(input, before);
  assert.deepEqual(Object.keys(graph.getNodeAttributes("concepts/a")).sort(), [
    "aliases",
    "audience",
    "conceptId",
    "confidence",
    "description",
    "sourcePath",
    "status",
    "tags",
    "title",
    "type",
    "xKosId",
  ]);
  assert.equal("provenanceRecord" in graph.getNodeAttributes("concepts/a"), false);
  assert.equal("reviewId" in graph.getEdgeAttributes("edge-directed"), false);
});

test("is deterministic across input ordering", () => {
  const first = canonical();
  const second = canonical();
  second.nodes.reverse();
  second.edges.reverse();
  assert.deepEqual(
    knowledgeGraphV2ToGraphology(first).export(),
    knowledgeGraphV2ToGraphology(second).export(),
  );
});

test("rejects duplicate nodes and duplicate stable edge IDs", () => {
  const duplicateNode = canonical();
  duplicateNode.nodes.push(structuredClone(duplicateNode.nodes[0]!));
  assert.throws(() => knowledgeGraphV2ToGraphology(duplicateNode), /duplicate concept/);
  const duplicateEdge = canonical();
  duplicateEdge.edges.push(structuredClone(duplicateEdge.edges[0]!));
  assert.throws(() => knowledgeGraphV2ToGraphology(duplicateEdge), /duplicate edge/);
});

test("rejects missing endpoints and self-loops", () => {
  const missing = canonical();
  missing.edges[0]!.target = "concepts/missing";
  assert.throws(() => knowledgeGraphV2ToGraphology(missing), /endpoint is missing/);
  const selfLoop = canonical();
  selfLoop.edges[0]!.target = selfLoop.edges[0]!.source;
  assert.throws(() => knowledgeGraphV2ToGraphology(selfLoop), /self-loop/);
});

test("rejects schema, release, manifest, direction, and ACL drift", () => {
  const schema = canonical();
  schema.schema_version = "knowledge-os-graph/v3";
  assert.throws(() => knowledgeGraphV2ToGraphology(schema), /unsupported/);
  assert.throws(
    () => knowledgeGraphV2ToGraphology(canonical(), { expectedReleaseId: "other" }),
    /release identity mismatch/,
  );
  assert.throws(
    () =>
      graphApiPayloadToGraphology(apiPayload(), {
        expectedManifestSha256: "e".repeat(64),
      }),
    /manifest identity mismatch/,
  );
  const direction = canonical();
  (direction.edges[0] as Record<string, unknown>).directed = "false";
  assert.throws(() => knowledgeGraphV2ToGraphology(direction), /directed must be a boolean/);
  const acl = canonical();
  acl.nodes[0]!.audience = "unknown";
  assert.throws(() => knowledgeGraphV2ToGraphology(acl), /audience is unknown/);
});

test("rejects renderer state in canonical or API input", () => {
  for (const field of ["color", "x", "coordinates", "camera", "layout"]) {
    const input = canonical();
    (input.nodes[0] as Record<string, unknown>)[field] = "forbidden";
    assert.throws(() => knowledgeGraphV2ToGraphology(input), /renderer fields/);
  }
  const payload = apiPayload();
  (payload.edges[0] as Record<string, unknown>).sigma_color = "forbidden";
  assert.throws(() => graphApiPayloadToGraphology(payload), /renderer fields/);
});

test("pins a Graphology-only runtime dependency and contains no Sigma import", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../../package.json", import.meta.url), "utf8"),
  ) as { dependencies: Record<string, string> };
  assert.deepEqual(packageJson.dependencies, { graphology: "0.26.0" });
  const source = await readFile(new URL("../../src/index.ts", import.meta.url), "utf8");
  assert.equal(/from ["'](?:@?sigma|sigma)/i.test(source), false);
});
