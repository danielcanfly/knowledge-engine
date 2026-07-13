import type { ExplorerGraph } from "./index.js";

export const PHASE_B_ACCEPTANCE_SCHEMA = "knowledge-os-phase-b-acceptance/v1";
export const MAX_ACCEPTANCE_REQUEST_NODES = 50_000;
export const MAX_ACCEPTANCE_REQUEST_EDGES = 250_000;
export const MAX_ACCEPTANCE_DEPTH = 2;
export const MAX_ACCEPTANCE_PAYLOAD_BYTES = 96_000_000;

export type ReleaseViewMode = "production" | "candidate-preview" | "source-preview";

export interface AcceptanceReleaseIdentity {
  releaseId: string;
  manifestSha256?: string;
  sourceCommitSha?: string;
  foundationCommitSha?: string;
  contentSha256?: string;
}

export interface ReleaseViewDescriptor {
  schemaVersion: typeof PHASE_B_ACCEPTANCE_SCHEMA;
  mode: ReleaseViewMode;
  label: string;
  warning: string | null;
  release: AcceptanceReleaseIdentity;
  production: boolean;
  readOnly: true;
}

export interface RelationAccessibilityInput {
  relationType: string;
  sourceId: string;
  sourceLabel: string;
  targetId: string;
  targetLabel: string;
  directed: boolean;
}

export interface RelationAccessibilityDescriptor {
  relationType: string;
  direction: "directed" | "undirected";
  symbol: "→" | "↔";
  sourceId: string;
  targetId: string;
  text: string;
  colorIndependent: true;
}

export interface PhaseBRequestBounds {
  maxDepth: number;
  maxNodes: number;
  maxEdges: number;
  maxPayloadBytes: number;
}

export interface PhaseBAuthorityManifest {
  schemaVersion: typeof PHASE_B_ACCEPTANCE_SCHEMA;
  serverSideAcl: true;
  apiMethods: readonly ["GET"];
  mutationRoutes: readonly [];
  rendererNeutralInput: true;
  runtimeCdn: false;
  dynamicCodeEvaluation: false;
  inlineScriptRequired: false;
  browserNetworkClients: readonly [];
  browserPersistence: readonly [];
  writeBackTargets: readonly [];
  requestBounds: PhaseBRequestBounds;
  keyboardNavigation: true;
  textualFallback: true;
  colorOnlyRelations: false;
  readOnly: true;
}

function requiredString(value: unknown, label: string, maximum = 300): string {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > maximum) {
    throw new TypeError(`${label} must be a non-empty string of at most ${maximum} characters`);
  }
  return value;
}

function optionalGraphString(graph: ExplorerGraph, name: string): string | undefined {
  const value = graph.getAttribute(name);
  if (value === undefined || value === null) return undefined;
  return requiredString(value, `graph.${name}`);
}

function graphReleaseIdentity(graph: ExplorerGraph): AcceptanceReleaseIdentity {
  if (graph.getAttribute("readOnly") !== true) {
    throw new TypeError("Phase B acceptance accepts only a read-only graph");
  }
  if (graph.getAttribute("rendererNeutral") !== true) {
    throw new TypeError("Phase B acceptance accepts only a renderer-neutral graph");
  }
  const manifestSha256 = optionalGraphString(graph, "manifestSha256");
  const sourceCommitSha = optionalGraphString(graph, "sourceCommitSha");
  const foundationCommitSha = optionalGraphString(graph, "foundationCommitSha");
  const contentSha256 = optionalGraphString(graph, "contentSha256");
  return {
    releaseId: requiredString(graph.getAttribute("releaseId"), "graph.releaseId"),
    ...(manifestSha256 !== undefined ? { manifestSha256 } : {}),
    ...(sourceCommitSha !== undefined ? { sourceCommitSha } : {}),
    ...(foundationCommitSha !== undefined ? { foundationCommitSha } : {}),
    ...(contentSha256 !== undefined ? { contentSha256 } : {}),
  };
}

function identityKey(identity: AcceptanceReleaseIdentity): string {
  return [
    identity.releaseId,
    identity.manifestSha256 ?? "",
    identity.sourceCommitSha ?? "",
    identity.foundationCommitSha ?? "",
    identity.contentSha256 ?? "",
  ].join("|");
}

export function createReleaseViewDescriptor(
  graph: ExplorerGraph,
  mode: ReleaseViewMode,
): ReleaseViewDescriptor {
  const release = graphReleaseIdentity(graph);
  if (mode === "production") {
    return {
      schemaVersion: PHASE_B_ACCEPTANCE_SCHEMA,
      mode,
      label: `Production release ${release.releaseId}`,
      warning: null,
      release,
      production: true,
      readOnly: true,
    };
  }
  const label = mode === "candidate-preview" ? "Candidate preview" : "Source preview";
  return {
    schemaVersion: PHASE_B_ACCEPTANCE_SCHEMA,
    mode,
    label: `${label} ${release.releaseId}`,
    warning: "Non-production view. Do not treat this graph as the active Runtime release.",
    release,
    production: false,
    readOnly: true,
  };
}

export function assertSingleReleaseComposition(
  views: readonly ReleaseViewDescriptor[],
): readonly ReleaseViewDescriptor[] {
  if (views.length === 0 || views.length > 3) {
    throw new TypeError("release composition must contain between one and three explicit views");
  }
  const modes = new Set<ReleaseViewMode>();
  const identities = new Set<string>();
  for (const view of views) {
    if (view.schemaVersion !== PHASE_B_ACCEPTANCE_SCHEMA || view.readOnly !== true) {
      throw new TypeError("release view is mutable or uses an unsupported schema");
    }
    if (modes.has(view.mode)) throw new TypeError("release composition contains a duplicate view mode");
    modes.add(view.mode);
    identities.add(identityKey(view.release));
    if (view.mode === "production" && (!view.production || view.warning !== null)) {
      throw new TypeError("production view must be explicitly production and unambiguous");
    }
    if (view.mode !== "production" && (view.production || view.warning === null)) {
      throw new TypeError("preview views must be explicitly non-production and warned");
    }
  }
  if (identities.size !== 1) {
    throw new TypeError("different release identities must remain separate and cannot be composed together");
  }
  return views.map((view) => ({ ...view, release: { ...view.release } }));
}

export function relationAccessibilityDescriptor(
  input: RelationAccessibilityInput,
): RelationAccessibilityDescriptor {
  const relationType = requiredString(input.relationType, "relationType", 120);
  const sourceId = requiredString(input.sourceId, "sourceId");
  const sourceLabel = requiredString(input.sourceLabel, "sourceLabel", 200);
  const targetId = requiredString(input.targetId, "targetId");
  const targetLabel = requiredString(input.targetLabel, "targetLabel", 200);
  if (typeof input.directed !== "boolean") throw new TypeError("directed must be a boolean");
  const direction = input.directed ? "directed" : "undirected";
  const symbol = input.directed ? "→" : "↔";
  return {
    relationType,
    direction,
    symbol,
    sourceId,
    targetId,
    text: `${sourceLabel} ${symbol} ${targetLabel}; relation ${relationType}; ${direction}`,
    colorIndependent: true,
  };
}

export function defaultPhaseBAuthorityManifest(): PhaseBAuthorityManifest {
  return {
    schemaVersion: PHASE_B_ACCEPTANCE_SCHEMA,
    serverSideAcl: true,
    apiMethods: ["GET"],
    mutationRoutes: [],
    rendererNeutralInput: true,
    runtimeCdn: false,
    dynamicCodeEvaluation: false,
    inlineScriptRequired: false,
    browserNetworkClients: [],
    browserPersistence: [],
    writeBackTargets: [],
    requestBounds: {
      maxDepth: MAX_ACCEPTANCE_DEPTH,
      maxNodes: MAX_ACCEPTANCE_REQUEST_NODES,
      maxEdges: MAX_ACCEPTANCE_REQUEST_EDGES,
      maxPayloadBytes: MAX_ACCEPTANCE_PAYLOAD_BYTES,
    },
    keyboardNavigation: true,
    textualFallback: true,
    colorOnlyRelations: false,
    readOnly: true,
  };
}

function exactEmptyArray(value: readonly unknown[], label: string): void {
  if (!Array.isArray(value) || value.length !== 0) {
    throw new TypeError(`${label} must be an empty array`);
  }
}

export function validatePhaseBAuthorityManifest(
  manifest: PhaseBAuthorityManifest,
): PhaseBAuthorityManifest {
  if (manifest.schemaVersion !== PHASE_B_ACCEPTANCE_SCHEMA || manifest.readOnly !== true) {
    throw new TypeError("unsupported or mutable Phase B authority manifest");
  }
  if (manifest.serverSideAcl !== true || manifest.rendererNeutralInput !== true) {
    throw new TypeError("Phase B authority requires server-side ACL and renderer-neutral input");
  }
  if (manifest.apiMethods.length !== 1 || manifest.apiMethods[0] !== "GET") {
    throw new TypeError("Phase B Graph API authority must be GET-only");
  }
  exactEmptyArray(manifest.mutationRoutes, "mutationRoutes");
  exactEmptyArray(manifest.browserNetworkClients, "browserNetworkClients");
  exactEmptyArray(manifest.browserPersistence, "browserPersistence");
  exactEmptyArray(manifest.writeBackTargets, "writeBackTargets");
  if (manifest.runtimeCdn || manifest.dynamicCodeEvaluation || manifest.inlineScriptRequired) {
    throw new TypeError("Phase B packaging must remain CSP-compatible and self-contained");
  }
  if (!manifest.keyboardNavigation || !manifest.textualFallback || manifest.colorOnlyRelations) {
    throw new TypeError("Phase B accessibility contract is incomplete");
  }
  const bounds = manifest.requestBounds;
  if (
    !Number.isSafeInteger(bounds.maxDepth) ||
    bounds.maxDepth < 1 ||
    bounds.maxDepth > MAX_ACCEPTANCE_DEPTH ||
    !Number.isSafeInteger(bounds.maxNodes) ||
    bounds.maxNodes < 1 ||
    bounds.maxNodes > MAX_ACCEPTANCE_REQUEST_NODES ||
    !Number.isSafeInteger(bounds.maxEdges) ||
    bounds.maxEdges < 1 ||
    bounds.maxEdges > MAX_ACCEPTANCE_REQUEST_EDGES ||
    !Number.isSafeInteger(bounds.maxPayloadBytes) ||
    bounds.maxPayloadBytes < 1 ||
    bounds.maxPayloadBytes > MAX_ACCEPTANCE_PAYLOAD_BYTES
  ) {
    throw new TypeError("Phase B request bounds are invalid or unbounded");
  }
  return {
    ...manifest,
    apiMethods: ["GET"],
    mutationRoutes: [],
    browserNetworkClients: [],
    browserPersistence: [],
    writeBackTargets: [],
    requestBounds: { ...bounds },
  };
}
