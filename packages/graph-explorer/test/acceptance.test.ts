import assert from "node:assert/strict";
import test from "node:test";

import * as Graphology from "graphology";

import {
  PHASE_B_ACCEPTANCE_SCHEMA,
  assertSingleReleaseComposition,
  createReleaseViewDescriptor,
  defaultPhaseBAuthorityManifest,
  relationAccessibilityDescriptor,
  validatePhaseBAuthorityManifest,
} from "../src/acceptance.js";
import type { ExplorerGraph } from "../src/index.js";

function graph(releaseId = "release-1"): ExplorerGraph {
  const GraphConstructor = Graphology.default as unknown as new (options: {
    allowSelfLoops: boolean;
    multi: boolean;
    type: "mixed";
  }) => ExplorerGraph;
  const value = new GraphConstructor({ allowSelfLoops: false, multi: true, type: "mixed" });
  value.replaceAttributes({
    releaseId,
    manifestSha256: `manifest-${releaseId}`,
    sourceCommitSha: "source-sha",
    foundationCommitSha: "foundation-sha",
    contentSha256: `content-${releaseId}`,
    readOnly: true,
    rendererNeutral: true,
  });
  value.addNode("a", { title: "Alpha", type: "concept" });
  value.addNode("b", { title: "Beta", type: "concept" });
  value.addDirectedEdgeWithKey("edge-1", "a", "b", { relationType: "depends_on" });
  return value;
}

test("creates explicit production and preview release descriptors", () => {
  const production = createReleaseViewDescriptor(graph(), "production");
  const source = createReleaseViewDescriptor(graph(), "source-preview");
  assert.equal(production.schemaVersion, PHASE_B_ACCEPTANCE_SCHEMA);
  assert.equal(production.production, true);
  assert.equal(production.warning, null);
  assert.equal(source.production, false);
  assert.match(source.warning ?? "", /Non-production/);
});

test("accepts multiple explicit modes only for one exact release identity", () => {
  const value = graph();
  const result = assertSingleReleaseComposition([
    createReleaseViewDescriptor(value, "production"),
    createReleaseViewDescriptor(value, "candidate-preview"),
    createReleaseViewDescriptor(value, "source-preview"),
  ]);
  assert.equal(result.length, 3);
});

test("rejects cross-release composition", () => {
  assert.throws(
    () =>
      assertSingleReleaseComposition([
        createReleaseViewDescriptor(graph("release-1"), "production"),
        createReleaseViewDescriptor(graph("release-2"), "source-preview"),
      ]),
    /different release identities/,
  );
});

test("rejects duplicate release view modes", () => {
  const value = graph();
  assert.throws(
    () =>
      assertSingleReleaseComposition([
        createReleaseViewDescriptor(value, "production"),
        createReleaseViewDescriptor(value, "production"),
      ]),
    /duplicate view mode/,
  );
});

test("requires read-only renderer-neutral graphs", () => {
  const value = graph();
  value.setAttribute("readOnly", false);
  assert.throws(() => createReleaseViewDescriptor(value, "production"), /read-only/);
});

test("relation accessibility descriptor does not rely on color", () => {
  const descriptor = relationAccessibilityDescriptor({
    relationType: "depends_on",
    sourceId: "a",
    sourceLabel: "Alpha",
    targetId: "b",
    targetLabel: "Beta",
    directed: true,
  });
  assert.equal(descriptor.symbol, "→");
  assert.equal(descriptor.direction, "directed");
  assert.equal(descriptor.colorIndependent, true);
  assert.match(descriptor.text, /Alpha → Beta/);
  assert.match(descriptor.text, /depends_on/);
});

test("default Phase B authority manifest is accepted", () => {
  const manifest = validatePhaseBAuthorityManifest(defaultPhaseBAuthorityManifest());
  assert.deepEqual(manifest.apiMethods, ["GET"]);
  assert.deepEqual(manifest.mutationRoutes, []);
  assert.equal(manifest.keyboardNavigation, true);
  assert.equal(manifest.colorOnlyRelations, false);
});

test("rejects mutation, network, persistence, write-back, or CSP authority", () => {
  const base = defaultPhaseBAuthorityManifest();
  assert.throws(
    () => validatePhaseBAuthorityManifest({ ...base, mutationRoutes: ["POST"] } as never),
    /mutationRoutes/,
  );
  assert.throws(
    () => validatePhaseBAuthorityManifest({ ...base, browserNetworkClients: ["fetch"] } as never),
    /browserNetworkClients/,
  );
  assert.throws(
    () => validatePhaseBAuthorityManifest({ ...base, browserPersistence: ["localStorage"] } as never),
    /browserPersistence/,
  );
  assert.throws(
    () => validatePhaseBAuthorityManifest({ ...base, writeBackTargets: ["R2"] } as never),
    /writeBackTargets/,
  );
  assert.throws(
    () => validatePhaseBAuthorityManifest({ ...base, dynamicCodeEvaluation: true } as never),
    /CSP-compatible/,
  );
});

test("rejects unbounded request limits", () => {
  const base = defaultPhaseBAuthorityManifest();
  assert.throws(
    () =>
      validatePhaseBAuthorityManifest({
        ...base,
        requestBounds: { ...base.requestBounds, maxDepth: 3 },
      }),
    /invalid or unbounded/,
  );
});
