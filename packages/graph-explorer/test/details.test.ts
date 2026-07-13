import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import * as Graphology from "graphology";

import {
  EXPLORER_DETAILS_SCHEMA,
  MAX_PROVENANCE_REFERENCES,
  createExplorerDetailsController,
  type ExplorerDetailsBundle,
} from "../src/details.js";
import type { ExplorerGraph } from "../src/index.js";

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
    releaseId: "release-m19-5",
    manifestSha256: "manifest-m19-5",
    sourceCommitSha: "source-m19-5",
    foundationCommitSha: "foundation-m19-5",
    contentSha256: "content-m19-5",
    readOnly: true,
  });
  for (const [index, title] of ["Agent Systems", "Retrieval Systems"].entries()) {
    const id = `concepts/${index.toString().padStart(3, "0")}`;
    value.addNode(id, {
      aliases: [], audience: "public", conceptId: id, confidence: 0.9,
      description: `${title} description`, sourcePath: `${id}.md`, status: "published",
      tags: ["agents"], title, type: "Concept", xKosId: `ko_${index}`,
    });
  }
  value.addDirectedEdgeWithKey("edge-0", "concepts/000", "concepts/001", {
    audience: "public", confidence: 0.9, directed: true, edgeId: "edge-0",
    generatedInverse: false, relationType: "depends_on",
  });
  return value;
}

function details(): ExplorerDetailsBundle {
  return {
    schemaVersion: EXPLORER_DETAILS_SCHEMA,
    release: {
      releaseId: "release-m19-5",
      manifestSha256: "manifest-m19-5",
      sourceCommitSha: "source-m19-5",
      foundationCommitSha: "foundation-m19-5",
      contentSha256: "content-m19-5",
    },
    nodes: [{
      nodeId: "concepts/000",
      provenance: [{
        referenceId: "claim-agent-systems",
        label: "Reviewed source claim",
        sourcePath: "provenance/agent-systems.md",
        anchor: "claim-agent-systems",
        reviewStatus: "approved",
      }],
    }],
    edges: [{
      edgeId: "edge-0",
      provenance: [{
        referenceId: "claim-agent-depends-retrieval",
        label: "Approved relation evidence",
        sourcePath: "provenance/relations.md",
        reviewStatus: "approved",
      }],
    }],
    readOnly: true,
  };
}

test("returns exact release identity, a safe Markdown link, and approved node provenance", () => {
  const controller = createExplorerDetailsController({ graph: graph(), details: details() });
  controller.selectNode("concepts/000");
  const state = controller.getState();
  assert.equal(state.panel?.kind, "node");
  if (state.panel?.kind !== "node") throw new Error("expected node panel");
  assert.equal(state.panel.markdownHref, "concepts/000.md");
  assert.equal(state.panel.provenance[0]?.referenceId, "claim-agent-systems");
  assert.deepEqual(state.release, details().release);
  assert.equal(state.selectedEdgeId, null);
  assert.equal(state.readOnly, true);
});

test("returns edge details and renderer-only selection styling", () => {
  const controller = createExplorerDetailsController({ graph: graph(), details: details() });
  controller.selectEdge("edge-0");
  const panel = controller.getState().panel;
  assert.equal(panel?.kind, "edge");
  if (panel?.kind !== "edge") throw new Error("expected edge panel");
  assert.equal(panel.edge.relationType, "depends_on");
  assert.equal(panel.edge.source.id, "concepts/000");
  assert.equal(panel.edge.target.id, "concepts/001");
  assert.equal(panel.provenance[0]?.reviewStatus, "approved");
  assert.equal(controller.edgeReducer("edge-0", {}).highlighted, true);
  assert.equal(controller.getState().selectedNodeId, null);
});

test("clears panel state when M19.4 visibility removes the selected object", () => {
  const emitted: Array<string | null> = [];
  const controller = createExplorerDetailsController({
    graph: graph(), details: details(), onChange: (panel) => emitted.push(panel?.kind ?? null),
  });
  controller.selectEdge("edge-0");
  controller.reconcileVisible(["concepts/000"], []);
  assert.equal(controller.getState().panel, null);
  assert.deepEqual(emitted, ["edge", null]);
});

test("rejects cross-release metadata and references outside the ACL-safe graph", () => {
  const mismatch = details();
  mismatch.release.manifestSha256 = "wrong";
  assert.throws(
    () => createExplorerDetailsController({ graph: graph(), details: mismatch }),
    /manifestSha256 identity mismatch/,
  );
  const outside = details();
  outside.nodes.push({ nodeId: "concepts/restricted", provenance: [] });
  assert.throws(
    () => createExplorerDetailsController({ graph: graph(), details: outside }),
    /outside the ACL-safe graph/,
  );
});

test("rejects unsafe, unapproved, duplicate, and unbounded provenance", () => {
  const unsafe = details();
  unsafe.nodes[0]!.provenance[0]!.sourcePath = "../secret.md";
  assert.throws(() => createExplorerDetailsController({ graph: graph(), details: unsafe }), /traversal/);

  const unapproved = details();
  (unapproved.nodes[0]!.provenance[0] as { reviewStatus: string }).reviewStatus = "pending";
  assert.throws(
    () => createExplorerDetailsController({ graph: graph(), details: unapproved }),
    /must be approved/,
  );

  const duplicate = details();
  duplicate.nodes[0]!.provenance.push({ ...duplicate.nodes[0]!.provenance[0]! });
  assert.throws(
    () => createExplorerDetailsController({ graph: graph(), details: duplicate }),
    /duplicate reference IDs/,
  );

  const unbounded = details();
  unbounded.nodes[0]!.provenance = Array.from(
    { length: MAX_PROVENANCE_REFERENCES + 1 },
    (_, index) => ({
      referenceId: `reference-${index}`,
      label: `Reference ${index}`,
      sourcePath: `provenance/reference-${index}.md`,
      reviewStatus: "approved" as const,
    }),
  );
  assert.throws(
    () => createExplorerDetailsController({ graph: graph(), details: unbounded }),
    /at most 20/,
  );
});

test("keeps details optional and never mutates the canonical graph", () => {
  const source = graph();
  const before = source.export();
  const controller = createExplorerDetailsController({ graph: source });
  controller.selectNode("concepts/001");
  const panel = controller.getState().panel;
  assert.equal(panel?.kind, "node");
  if (panel?.kind !== "node") throw new Error("expected node panel");
  assert.deepEqual(panel.provenance, []);
  assert.deepEqual(source.export(), before);
});

test("adds no runtime network, mutation, arbitrary URL, raw evidence, or reviewer identity authority", async () => {
  const source = await readFile(new URL("../../src/details.ts", import.meta.url), "utf8");
  assert.equal(/https?:\/\//.test(source), false);
  assert.equal(/\b(?:fetch|XMLHttpRequest|WebSocket)\b/.test(source), false);
  assert.equal(/\b(?:POST|PUT|PATCH|DELETE)\b/.test(source), false);
  assert.equal(/rawEvidence|reviewedBy|reviewerIdentity/.test(source), false);
});
