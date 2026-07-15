import { createRemoteJWKSet, jwtVerify } from "jose";

const QUERY_SCHEMA = "knowledge-engine-m23-candidate-semantic-query/v1";
const RESPONSE_SCHEMA = "knowledge-engine-m23-candidate-semantic-response/v1";
const SHADOW_SCHEMA = "knowledge-engine-m23-candidate-shadow-response/v1";
const COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024";
const VECTOR_NAME = "default";
const VECTOR_DIMENSION = 1024;
const SOURCE_MEMBERSHIP = "evaluation-only-pending-proposal";
const RELEASE_ID = "m23pilot-a07eb79e381ca7e635cc9139";
const RELEASE_MANIFEST_SHA256 = "a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9";
const RETRIEVAL_PATH = "/internal/candidate/m23/retrieve";
const SHADOW_PATH = "/internal/candidate/m23/shadow/retrieve";
const DEFAULT_TOP_K = 8;
const MAX_QUERY_CHARS = 2000;
const MAX_TOP_K = 20;
const MAX_LEXICAL_IDS = 20;
const MAX_REQUEST_BYTES = 16_384;
const MAX_RESPONSE_BYTES = 262_144;

interface JsonObject {
  [key: string]: unknown;
}

type ParsedQuery = {
  schema_version: typeof QUERY_SCHEMA;
  request_id: string;
  query: string;
  top_k: number;
  lexical_point_ids?: string[];
};

type AuthContext = {
  subject: string;
  email: string | null;
};

type CandidateResult = {
  rank: number;
  point_id: string;
  score: number;
  section_id: string;
  article_id: string;
  document_id: string;
  concept_id: string;
  source_path: string;
  source_sha256: string;
  text_sha256: string;
  graph_node_id: string;
  release_id: typeof RELEASE_ID;
  release_manifest_sha256: typeof RELEASE_MANIFEST_SHA256;
  canonical_knowledge: false;
  candidate_release_eligible: false;
  production_authority: false;
};

class RequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

class UpstreamError extends Error {}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string, maxLength: number): string {
  if (typeof value !== "string") {
    throw new RequestError(`invalid-${field}`, 400);
  }
  const text = value.trim();
  if (text.length === 0 || text.length > maxLength) {
    throw new RequestError(`invalid-${field}`, 400);
  }
  return text;
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  const object = value as JsonObject;
  return `{${Object.keys(object)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(object[key])}`)
    .join(",")}}`;
}

async function sha256Hex(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function log(event: string, fields: JsonObject = {}): void {
  console.log(
    JSON.stringify({
      timestamp: new Date().toISOString(),
      milestone: "M23.6.5",
      worker: "llm-wiki-m23-candidate-runtime",
      event,
      ...fields,
    }),
  );
}

async function readJsonObject(request: Request): Promise<JsonObject> {
  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("application/json")) {
    throw new RequestError("content-type-must-be-application-json", 415);
  }
  const declaredLength = request.headers.get("content-length");
  if (declaredLength !== null) {
    const parsedLength = Number(declaredLength);
    if (!Number.isFinite(parsedLength) || parsedLength < 0 || parsedLength > MAX_REQUEST_BYTES) {
      throw new RequestError("request-body-too-large", 413);
    }
  }
  if (request.body === null) {
    throw new RequestError("request-body-required", 400);
  }
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_REQUEST_BYTES) {
      await reader.cancel();
      throw new RequestError("request-body-too-large", 413);
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new RequestError("invalid-json", 400);
  }
  if (!isObject(parsed)) {
    throw new RequestError("json-object-required", 400);
  }
  return parsed;
}

async function parseQuery(raw: JsonObject, shadow: boolean): Promise<ParsedQuery> {
  if (raw.schema_version !== QUERY_SCHEMA) {
    throw new RequestError("unsupported-query-schema", 400);
  }
  const query = requiredString(raw.query, "query", MAX_QUERY_CHARS);
  const rawTopK = raw.top_k ?? DEFAULT_TOP_K;
  if (typeof rawTopK !== "number" || !Number.isInteger(rawTopK) || rawTopK < 1 || rawTopK > MAX_TOP_K) {
    throw new RequestError("invalid-top-k", 400);
  }
  const requestId =
    raw.request_id === undefined
      ? `m23qry-${(await sha256Hex(query)).slice(0, 24)}`
      : requiredString(raw.request_id, "request-id", 128);
  const parsed: ParsedQuery = {
    schema_version: QUERY_SCHEMA,
    request_id: requestId,
    query,
    top_k: rawTopK,
  };
  if (shadow) {
    if (!Array.isArray(raw.lexical_point_ids) || raw.lexical_point_ids.length > MAX_LEXICAL_IDS) {
      throw new RequestError("invalid-lexical-point-ids", 400);
    }
    const ids = raw.lexical_point_ids.map((item) => requiredString(item, "lexical-point-id", 128));
    if (new Set(ids).size !== ids.length) {
      throw new RequestError("duplicate-lexical-point-id", 400);
    }
    parsed.lexical_point_ids = ids;
  } else if (raw.lexical_point_ids !== undefined) {
    throw new RequestError("lexical-point-ids-shadow-only", 400);
  }
  return parsed;
}

function validateTeamDomain(value: string): string {
  const url = new URL(value);
  if (
    url.protocol !== "https:" ||
    url.pathname !== "/" ||
    !url.hostname.endsWith(".cloudflareaccess.com") ||
    url.hostname === "replace-me.cloudflareaccess.com"
  ) {
    throw new RequestError("access-team-domain-not-configured", 503);
  }
  return url.origin;
}

async function verifyAccess(request: Request, env: CloudflareEnv): Promise<AuthContext> {
  const token = request.headers.get("Cf-Access-Jwt-Assertion");
  if (token === null) {
    throw new RequestError("access-token-required", 403);
  }
  const teamDomain = validateTeamDomain(env.ACCESS_TEAM_DOMAIN);
  const audience = requiredString(env.ACCESS_POLICY_AUD, "access-policy-aud", 256);
  if (audience === "replace-me-before-explicit-deployment") {
    throw new RequestError("access-audience-not-configured", 503);
  }
  try {
    const jwks = createRemoteJWKSet(new URL(`${teamDomain}/cdn-cgi/access/certs`));
    const { payload } = await jwtVerify(token, jwks, {
      issuer: teamDomain,
      audience,
    });
    return {
      subject: typeof payload.sub === "string" ? payload.sub : "authenticated",
      email: typeof payload.email === "string" ? payload.email : null,
    };
  } catch {
    throw new RequestError("invalid-access-token", 403);
  }
}

function parseEmbedding(value: unknown): number[] {
  if (!isObject(value) || !Array.isArray(value.data) || value.data.length !== 1) {
    throw new UpstreamError("workers-ai-invalid-embedding-response");
  }
  const row = value.data[0];
  if (!Array.isArray(row) || row.length !== VECTOR_DIMENSION) {
    throw new UpstreamError("workers-ai-vector-dimension-mismatch");
  }
  const numbers = row.map((entry) => {
    if (typeof entry !== "number" || !Number.isFinite(entry)) {
      throw new UpstreamError("workers-ai-nonfinite-vector");
    }
    return entry;
  });
  const norm = Math.sqrt(numbers.reduce((sum, entry) => sum + entry * entry, 0));
  if (!Number.isFinite(norm) || norm <= 0) {
    throw new UpstreamError("workers-ai-zero-vector");
  }
  return numbers.map((entry) => entry / norm);
}

async function embedQuery(env: CloudflareEnv, query: string): Promise<number[]> {
  const result: unknown = await env.AI.run(env.EMBEDDING_MODEL, { text: [query] });
  return parseEmbedding(result);
}

function qdrantBaseUrl(env: CloudflareEnv): URL {
  const url = new URL(env.QDRANT_URL);
  if (url.protocol !== "https:") {
    throw new RequestError("qdrant-url-must-use-https", 503);
  }
  return url;
}

async function queryQdrant(env: CloudflareEnv, vector: number[], topK: number): Promise<JsonObject[]> {
  if (env.QDRANT_COLLECTION !== COLLECTION || env.QDRANT_VECTOR_NAME !== VECTOR_NAME) {
    throw new RequestError("qdrant-binding-contract-mismatch", 503);
  }
  const url = new URL(`/collections/${COLLECTION}/points/query`, qdrantBaseUrl(env));
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "api-key": env.QDRANT_API_KEY,
      "content-type": "application/json",
    },
    signal: AbortSignal.timeout(Number(env.QDRANT_TIMEOUT_MS)),
    body: JSON.stringify({
      query: vector,
      using: VECTOR_NAME,
      filter: {
        must: [
          { key: "source_membership", match: { value: SOURCE_MEMBERSHIP } },
          { key: "release_id", match: { value: RELEASE_ID } },
          { key: "release_manifest_sha256", match: { value: RELEASE_MANIFEST_SHA256 } },
          { key: "canonical_knowledge", match: { value: false } },
          { key: "candidate_release_eligible", match: { value: false } },
          { key: "production_authority", match: { value: false } },
        ],
      },
      limit: topK,
      with_payload: true,
      with_vector: false,
    }),
  });
  if (!response.ok) {
    throw new UpstreamError(`qdrant-query-${response.status}`);
  }
  const body: unknown = await response.json();
  if (!isObject(body) || !isObject(body.result) || !Array.isArray(body.result.points)) {
    throw new UpstreamError("qdrant-query-invalid-response");
  }
  return body.result.points.map((item) => {
    if (!isObject(item)) {
      throw new UpstreamError("qdrant-query-invalid-point");
    }
    return item;
  });
}

function payloadString(payload: JsonObject, field: string, maxLength: number): string {
  return requiredString(payload[field], field, maxLength);
}

function payloadSha(payload: JsonObject, field: string): string {
  const value = payloadString(payload, field, 64);
  if (!/^[0-9a-f]{64}$/.test(value)) {
    throw new UpstreamError(`invalid-${field}`);
  }
  return value;
}

function parseCandidatePoint(raw: JsonObject): Omit<CandidateResult, "rank"> {
  const pointId = requiredString(raw.id, "point-id", 128);
  if (typeof raw.score !== "number" || !Number.isFinite(raw.score) || raw.score < -1 || raw.score > 1) {
    throw new UpstreamError("qdrant-score-outside-cosine-bounds");
  }
  if (!isObject(raw.payload)) {
    throw new UpstreamError("qdrant-point-payload-required");
  }
  const payload = raw.payload;
  if (
    payload.source_membership !== SOURCE_MEMBERSHIP ||
    payload.release_id !== RELEASE_ID ||
    payload.release_manifest_sha256 !== RELEASE_MANIFEST_SHA256 ||
    payload.vector_name !== VECTOR_NAME ||
    payload.vector_dimension !== VECTOR_DIMENSION ||
    payload.embedding_model !== "@cf/baai/bge-m3"
  ) {
    throw new UpstreamError("candidate-payload-identity-mismatch");
  }
  if (
    payload.canonical_knowledge !== false ||
    payload.candidate_release_eligible !== false ||
    payload.production_authority !== false
  ) {
    throw new UpstreamError("candidate-payload-authority-violation");
  }
  return {
    point_id: pointId,
    score: raw.score,
    section_id: payloadString(payload, "section_id", 500),
    article_id: payloadString(payload, "article_id", 500),
    document_id: payloadString(payload, "document_id", 500),
    concept_id: payloadString(payload, "concept_id", 500),
    source_path: payloadString(payload, "source_path", 2000),
    source_sha256: payloadSha(payload, "source_sha256"),
    text_sha256: payloadSha(payload, "text_sha256"),
    graph_node_id: payloadString(payload, "graph_node_id", 500),
    release_id: RELEASE_ID,
    release_manifest_sha256: RELEASE_MANIFEST_SHA256,
    canonical_knowledge: false,
    candidate_release_eligible: false,
    production_authority: false,
  };
}

async function buildSemanticResponse(query: ParsedQuery, points: JsonObject[]): Promise<JsonObject> {
  if (points.length > query.top_k || points.length > MAX_TOP_K) {
    throw new UpstreamError("qdrant-result-count-exceeds-bound");
  }
  const parsed = points.map(parseCandidatePoint);
  if (new Set(parsed.map((item) => item.point_id)).size !== parsed.length) {
    throw new UpstreamError("qdrant-duplicate-point-id");
  }
  parsed.sort((left, right) => right.score - left.score || left.point_id.localeCompare(right.point_id));
  const results: CandidateResult[] = parsed.map((item, index) => ({ rank: index + 1, ...item }));
  const body: JsonObject = {
    schema_version: RESPONSE_SCHEMA,
    milestone: "M23.6.5",
    request_id: query.request_id,
    query_sha256: await sha256Hex(query.query),
    collection: COLLECTION,
    vector_name: VECTOR_NAME,
    embedding_model: "@cf/baai/bge-m3",
    result_count: results.length,
    results,
    authority: {
      read_only: true,
      candidate_only: true,
      lexical_production_authority_unchanged: true,
      semantic_output_production_authority: false,
      answer_generation_dispatched: false,
      cloudflare_inference_dispatched: true,
      qdrant_read_dispatched: true,
      qdrant_write_dispatched: false,
      source_mutation_dispatched: false,
      r2_mutation_dispatched: false,
      pointer_mutation_dispatched: false,
      production_mutation_dispatched: false,
    },
  };
  body.response_sha256 = await sha256Hex(stableStringify(body));
  return body;
}

async function buildShadowResponse(query: ParsedQuery, semantic: JsonObject): Promise<JsonObject> {
  const lexicalIds = query.lexical_point_ids ?? [];
  const rawResults = semantic.results;
  if (!Array.isArray(rawResults)) {
    throw new UpstreamError("semantic-results-missing");
  }
  const semanticIds = rawResults.map((item) => {
    if (!isObject(item) || typeof item.point_id !== "string") {
      throw new UpstreamError("semantic-result-point-id-missing");
    }
    return item.point_id;
  });
  const lexicalRank = new Map(lexicalIds.map((pointId, index) => [pointId, index + 1]));
  const semanticRank = new Map(semanticIds.map((pointId, index) => [pointId, index + 1]));
  const overlap = lexicalIds.filter((pointId) => semanticRank.has(pointId));
  const rankDiagnostics = overlap.map((pointId) => ({
    point_id: pointId,
    lexical_rank: lexicalRank.get(pointId),
    semantic_rank: semanticRank.get(pointId),
    rank_delta: (semanticRank.get(pointId) ?? 0) - (lexicalRank.get(pointId) ?? 0),
  }));
  const denominator = Math.max(1, Math.min(lexicalIds.length, semanticIds.length));
  const body: JsonObject = {
    schema_version: SHADOW_SCHEMA,
    milestone: "M23.6.5",
    request_id: query.request_id,
    query_sha256: semantic.query_sha256,
    lexical_point_ids: lexicalIds,
    semantic_point_ids: semanticIds,
    overlap_count: overlap.length,
    overlap_at_k: overlap.length / denominator,
    rank_diagnostics: rankDiagnostics,
    lexical_only_point_ids: lexicalIds.filter((pointId) => !semanticRank.has(pointId)),
    semantic_only_point_ids: semanticIds.filter((pointId) => !lexicalRank.has(pointId)),
    semantic_response_sha256: semantic.response_sha256,
    authority: {
      lexical_output_authoritative: true,
      semantic_output_served_to_production: false,
      shadow_only: true,
      answer_generation_dispatched: false,
      cloudflare_inference_dispatched: true,
      qdrant_read_dispatched: true,
      qdrant_write_dispatched: false,
      production_mutation_dispatched: false,
    },
  };
  body.shadow_sha256 = await sha256Hex(stableStringify(body));
  return body;
}

function jsonResponse(body: JsonObject, status = 200): Response {
  const text = `${stableStringify(body)}\n`;
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    return new Response('{"error":"response-size-bound-exceeded"}\n', {
      status: 502,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
      },
    });
  }
  return new Response(text, {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

const worker: ExportedHandler<CloudflareEnv> = {
  async fetch(request, env): Promise<Response> {
    const url = new URL(request.url);
    const isRetrieval = url.pathname === RETRIEVAL_PATH;
    const isShadow = url.pathname === SHADOW_PATH;
    if (!isRetrieval && !isShadow) {
      return new Response("Not Found", { status: 404 });
    }
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405, headers: { allow: "POST" } });
    }
    try {
      if (env.CANDIDATE_RUNTIME_ENABLED !== "true") {
        return new Response("Not Found", { status: 404 });
      }
      if (isShadow && env.SHADOW_SEMANTIC_ENABLED !== "true") {
        return new Response("Not Found", { status: 404 });
      }
      const auth = await verifyAccess(request, env);
      const raw = await readJsonObject(request);
      const query = await parseQuery(raw, isShadow);
      const querySha = await sha256Hex(query.query);
      log("candidate-query-start", {
        request_id: query.request_id,
        query_sha256: querySha,
        top_k: query.top_k,
        shadow: isShadow,
        actor_subject: auth.subject,
        actor_email_present: auth.email !== null,
      });
      const vector = await embedQuery(env, query.query);
      const points = await queryQdrant(env, vector, query.top_k);
      const semantic = await buildSemanticResponse(query, points);
      const body = isShadow ? await buildShadowResponse(query, semantic) : semantic;
      log("candidate-query-complete", {
        request_id: query.request_id,
        query_sha256: querySha,
        result_count: semantic.result_count,
        shadow: isShadow,
      });
      return jsonResponse(body);
    } catch (error) {
      if (error instanceof RequestError) {
        log("candidate-query-rejected", { reason: error.message, status: error.status });
        return jsonResponse({ error: error.message }, error.status);
      }
      const reason = error instanceof Error ? error.message : "unknown-upstream-error";
      log("candidate-query-failed", { reason });
      return jsonResponse({ error: "candidate-runtime-unavailable" }, 503);
    }
  },
};

export default worker;
