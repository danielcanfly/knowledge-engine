import assert from "node:assert/strict";
import test from "node:test";

import * as Graphology from "graphology";

import type { ExplorerGraph } from "../src/index.js";
import {
  CANDIDATE_EXPLORER_SCHEMA,
  createCandidateExplorerModel,
  createSemanticNeighborhoodOverlay,
  type CandidateExplorerOverlay,
  type CandidateSemanticMapping,
} from "../src/candidate.js";

const RELEASE_ID = "m23cand-c7fbec7e945e79d05d3263b0";
const MANIFEST_SHA = "3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560";
const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);

function graph(): ExplorerGraph {
  const GraphConstructor = Graphology.default as unknown as new (options: {
    allowSelfLoops: boolean;
    multi: boolean;
    type: "mixed";
  }) => ExplorerGraph;
  const value = new GraphConstructor({ allowSelfLoops: false, multi: true, type: "mixed" });
  value.replaceAttributes({
    adapterSchemaVersion: "knowledge-os-graphology-adapter/v1",
    rendererNeutral: true,
    releaseId: RELEASE_ID,
    manifestSha256: MANIFEST_SHA,
    readOnly: true,
  });
  for (const [id, title] of [["candidate-a", "Candidate A"], ["candidate-b", "Candidate B"]]) {
    value.addNode(id, {
      aliases: [],
      audience: "internal",
      conceptId: id,
      confidence: 0,
      description: `${title} description`,
      sourcePath: "proposals/m23-4/proposed-concepts.md",
      status: "pending-human-review",
      tags: ["agents"],
      title,
      type: "concept-candidate",
      xKosId: id,
    });
  }
  value.addDirectedEdgeWithKey("edge-a", "candidate-a", "candidate-b", {
    audience: "internal",
    confidence: 0,
    directed: true,
    edgeId: "edge-a",
    generatedInverse: false,
    relationType: "supports",
  });
  return value;
}

function overlay(): CandidateExplorerOverlay {
  return {
    schema_version: CANDIDATE_EXPLORER_SCHEMA,
    candidate_release_id: RELEASE_ID,
    candidate_release_manifest_sha256: MANIFEST_SHA,
    graph_api_payload_sha256: SHA_A,
    semantic_anchor_map_sha256: SHA_B,
    view_mode: "candidate-preview",
    label: "M23 candidate preview",
    warning: "Evaluation-only pending proposals.",
    feature_flag: "GRAPH_EXPLORER_ENABLED",
    feature_flag_default: false,
    internal_only: true,
    read_only: true,
    node_count: 2,
    typed_edge_count: 1,
    semantic_section_count: 107,
    semantic_anchor_counts: {
      "pilot/harness-theory-part-01": 29,
      "pilot/harness-theory-part-02": 40,
      "pilot/harness-theory-part-03": 38,
    },
    semantic_edge_count: 0,
    typed_graph_and_semantic_overlay_conflated: false,
    node_level_semantic_counts_claimed: false,
    production_authority: false,
  };
}

function mappings(): CandidateSemanticMapping[] {
  return [
    {
      candidate_id: "candidate-a",
      semantic_anchor_graph_node_id: "pilot/harness-theory-part-01",
      anchor_point_count: 29,
      mapping_basis: "evidence-derivative-part",
      per_concept_section_attribution_available: false,
    },
    {
      candidate_id: "candidate-b",
      semantic_anchor_graph_node_id: "pilot/harness-theory-part-02",
      anchor_point_count: 40,
      mapping_basis: "evidence-derivative-part",
      per_concept_section_attribution_available: false,
    },
  ];
}

test("creates an internal candidate model without claiming node-level semantic attribution", () => {
  const source = graph();
  const before = source.export();
  const model = createCandidateExplorerModel(source, overlay(), mappings());
  assert.equal(model.releaseId, RELEASE_ID);
  assert.equal(model.featureFlagDefault, false);
  assert.equal(model.semanticSectionCount, 107);
  assert.equal(model.semanticEdgeCount, 0);
  assert.equal(model.typedGraphAndSemanticOverlayConflated, false);
  assert.equal(model.nodes[0]?.semanticEvidenceScope, "anchor-shared-not-node-attributed");
  assert.deepEqual(source.export(), before);
});

test("rejects release, count, authority, and semantic-conflation drift", () => {
  const cases: CandidateExplorerOverlay[] = [];
  cases.push({ ...overlay(), candidate_release_id: "wrong-release" });
  cases.push({ ...overlay(), node_count: 3 });
  cases.push({ ...overlay(), feature_flag_default: true as false });
  cases.push({ ...overlay(), semantic_edge_count: 1 as 0 });
  cases.push({ ...overlay(), typed_graph_and_semantic_overlay_conflated: true as false });
  for (const value of cases) {
    assert.throws(
      () => createCandidateExplorerModel(graph(), value, mappings()),
      /identity|counts|feature flag|conflated/,
    );
  }
});

test("rejects invented per-concept section attribution", () => {
  const value = mappings();
  value[0] = {
    ...value[0]!,
    per_concept_section_attribution_available: true as false,
  };
  assert.throws(
    () => createCandidateExplorerModel(graph(), overlay(), value),
    /must not be claimed/,
  );
});

test("creates deterministic renderer-only semantic neighbors without mutating typed graph", () => {
  const source = graph();
  const before = source.export();
  const first = createSemanticNeighborhoodOverlay(source, "candidate-a", [
    {
      candidateId: "candidate-b",
      semanticAnchorGraphNodeId: "pilot/harness-theory-part-02",
      score: 0.75,
    },
  ]);
  const second = createSemanticNeighborhoodOverlay(source, "candidate-a", [
    {
      candidateId: "candidate-b",
      semanticAnchorGraphNodeId: "pilot/harness-theory-part-02",
      score: 0.75,
    },
  ]);
  assert.deepEqual(first, second);
  assert.equal(first.edges[0]?.typedRelationship, false);
  assert.equal(first.edges[0]?.rendererOnly, true);
  assert.equal(first.semanticEdgesMaterialized, false);
  assert.deepEqual(source.export(), before);
});

test("rejects duplicate, self, unknown, unbounded, and invalid-score semantic neighbors", () => {
  const source = graph();
  assert.throws(
    () => createSemanticNeighborhoodOverlay(source, "candidate-a", [
      { candidateId: "candidate-a", semanticAnchorGraphNodeId: "part-1", score: 0.4 },
    ]),
    /invalid or duplicated/,
  );
  assert.throws(
    () => createSemanticNeighborhoodOverlay(source, "candidate-a", [
      { candidateId: "unknown", semanticAnchorGraphNodeId: "part-1", score: 0.4 },
    ]),
    /invalid or duplicated/,
  );
  assert.throws(
    () => createSemanticNeighborhoodOverlay(source, "candidate-a", [
      { candidateId: "candidate-b", semanticAnchorGraphNodeId: "part-2", score: 2 },
    ]),
    /cosine bounds/,
  );
  assert.throws(
    () => createSemanticNeighborhoodOverlay(
      source,
      "candidate-a",
      Array.from({ length: 21 }, (_, index) => ({
        candidateId: index === 0 ? "candidate-b" : `candidate-${index}`,
        semanticAnchorGraphNodeId: "part-2",
        score: 0.1,
      })),
    ),
    /at most 20/,
  );
});
