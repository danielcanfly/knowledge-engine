import { createRemoteJWKSet, jwtVerify } from "jose";

interface Env {
  AI: Ai;
  QDRANT_URL: string;
  QDRANT_API_KEY: string;
  CANDIDATE_RUNTIME_ENABLED: string;
  QDRANT_COLLECTION: string;
  QDRANT_VECTOR_NAME: string;
  EMBEDDING_MODEL: string;
  ANSWER_MODEL: string;
  CANDIDATE_RELEASE_ID: string;
  SOURCE_COMMIT_SHA: string;
  ADMISSION_SHA256: string;
  ACCESS_TEAM_DOMAIN: string;
  ACCESS_POLICY_AUD: string;
  MAX_QUERY_CHARS: string;
  MAX_TOP_K: string;
  QDRANT_TIMEOUT_MS: string;
}

interface QdrantHit {
  id: string | number;
  score: number;
  payload?: Record<string, unknown>;
}

interface RetrievalResult {
  release_id: string;
  query: string;
  top_k: number;
  hits: Array<{
    point_id: string;
    score: number;
    node_type: string;
    source_id: string;
    series_id: string;
    article_node_id: string;
    section_node_id: string | null;
    title: string;
    section_title: string | null;
    canonical_url: string;
    source_path: string;
    start_line: number | null;
    end_line: number | null;
    content_sha256: string;
    text_sha256: string;
  }>;
}

const jsonHeaders = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
};

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value, null, 2), {
    status,
    headers: jsonHeaders,
  });
}

function required(value: string | undefined, label: string): string {
  const candidate = value?.trim() || "";
  if (!candidate || candidate.startsWith("replace-")) {
    throw new Error(`${label} is not configured`);
  }
  return candidate;
}

function numberSetting(
  value: string | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(minimum, Math.min(maximum, Math.trunc(parsed)));
}

function accessToken(request: Request): string | null {
  const assertion = request.headers.get("Cf-Access-Jwt-Assertion")?.trim();
  if (assertion) return assertion;
  const cookie = request.headers.get("cookie") || "";
  const match = cookie.match(/(?:^|;\s*)CF_Authorization=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function normalizedTeamDomain(value: string): string {
  const url = new URL(value.includes("://") ? value : `https://${value}`);
  return `${url.protocol}//${url.host}`;
}

async function verifyAccess(request: Request, env: Env): Promise<Record<string, unknown>> {
  const token = accessToken(request);
  if (!token) throw new Error("Cloudflare Access assertion is required");
  const teamDomain = normalizedTeamDomain(required(env.ACCESS_TEAM_DOMAIN, "ACCESS_TEAM_DOMAIN"));
  const audience = required(env.ACCESS_POLICY_AUD, "ACCESS_POLICY_AUD");
  const jwks = createRemoteJWKSet(new URL(`${teamDomain}/cdn-cgi/access/certs`));
  const result = await jwtVerify(token, jwks, {
    issuer: teamDomain,
    audience,
  });
  return result.payload as Record<string, unknown>;
}

function queryFromUrl(url: URL): string {
  return (url.searchParams.get("q") || "").trim();
}

async function bodyObject(request: Request): Promise<Record<string, unknown>> {
  if (request.method === "GET") return {};
  const contentType = request.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error("POST requests require application/json");
  }
  const body = await request.json();
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new Error("request body must be an object");
  }
  return body as Record<string, unknown>;
}

function parseQuery(
  request: Request,
  url: URL,
  body: Record<string, unknown>,
  env: Env,
): { query: string; topK: number } {
  const raw = request.method === "GET" ? queryFromUrl(url) : body.query;
  if (typeof raw !== "string" || !raw.trim()) {
    throw new Error("query must be a non-empty string");
  }
  const maximum = numberSetting(env.MAX_QUERY_CHARS, 2000, 1, 10000);
  const query = raw.trim();
  if (query.length > maximum) {
    throw new Error(`query exceeds ${maximum} characters`);
  }
  const maxTopK = numberSetting(env.MAX_TOP_K, 20, 1, 100);
  const requested = request.method === "GET" ? url.searchParams.get("top_k") : body.top_k;
  const topK = numberSetting(
    typeof requested === "string" || typeof requested === "number"
      ? String(requested)
      : undefined,
    8,
    1,
    maxTopK,
  );
  return { query, topK };
}

function embeddingRows(value: unknown): number[][] {
  const object = value as Record<string, unknown>;
  const data = (object?.data || (object?.result as Record<string, unknown>)?.data) as unknown;
  if (!Array.isArray(data) || data.length !== 1) {
    throw new Error("embedding response must contain exactly one row");
  }
  const row = (data[0] as Record<string, unknown>)?.embedding || data[0];
  if (!Array.isArray(row) || row.length !== 1024) {
    throw new Error("embedding vector dimension mismatch");
  }
  return [row.map((item) => Number(item))];
}

async function embedQuery(query: string, env: Env): Promise<number[]> {
  const response = await env.AI.run(required(env.EMBEDDING_MODEL, "EMBEDDING_MODEL") as keyof AiModels, {
    text: [query],
  } as never);
  const vector = embeddingRows(response)[0];
  const norm = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
  if (!Number.isFinite(norm) || norm <= 0) throw new Error("embedding norm is invalid");
  return vector.map((value) => value / norm);
}

function payloadString(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

function payloadNumber(payload: Record<string, unknown>, key: string): number | null {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

async function retrieve(query: string, topK: number, env: Env): Promise<RetrievalResult> {
  if (env.CANDIDATE_RUNTIME_ENABLED !== "true") {
    throw new Error("candidate runtime is disabled");
  }
  const releaseId = required(env.CANDIDATE_RELEASE_ID, "CANDIDATE_RELEASE_ID");
  const collection = encodeURIComponent(required(env.QDRANT_COLLECTION, "QDRANT_COLLECTION"));
  const vectorName = required(env.QDRANT_VECTOR_NAME, "QDRANT_VECTOR_NAME");
  const vector = await embedQuery(query, env);
  const controller = new AbortController();
  const timeout = numberSetting(env.QDRANT_TIMEOUT_MS, 10000, 1000, 30000);
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(
      `${required(env.QDRANT_URL, "QDRANT_URL").replace(/\/$/, "")}/collections/${collection}/points/query`,
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "api-key": required(env.QDRANT_API_KEY, "QDRANT_API_KEY"),
        },
        body: JSON.stringify({
          query: vector,
          using: vectorName,
          limit: topK,
          with_payload: true,
          with_vector: false,
          filter: {
            must: [
              { key: "release_id", match: { value: releaseId } },
              { key: "source_commit_sha", match: { value: env.SOURCE_COMMIT_SHA } },
              { key: "admission_sha256", match: { value: env.ADMISSION_SHA256 } },
              { key: "candidate_release_eligible", match: { value: true } },
              { key: "production_authority", match: { value: false } },
            ],
          },
        }),
        signal: controller.signal,
      },
    );
    if (!response.ok) throw new Error(`Qdrant query failed with ${response.status}`);
    const value = (await response.json()) as Record<string, unknown>;
    const points = ((value.result as Record<string, unknown>)?.points || []) as QdrantHit[];
    if (!Array.isArray(points)) throw new Error("Qdrant result points are missing");
    const hits = points.map((point) => {
      const payload = point.payload || {};
      if (
        payloadString(payload, "release_id") !== releaseId ||
        payloadString(payload, "source_commit_sha") !== env.SOURCE_COMMIT_SHA ||
        payloadString(payload, "admission_sha256") !== env.ADMISSION_SHA256 ||
        payload.candidate_release_eligible !== true ||
        payload.production_authority !== false
      ) {
        throw new Error("Qdrant payload authority mismatch");
      }
      return {
        point_id: String(point.id),
        score: Number(point.score),
        node_type: payloadString(payload, "node_type"),
        source_id: payloadString(payload, "source_id"),
        series_id: payloadString(payload, "series_id"),
        article_node_id: payloadString(payload, "article_node_id"),
        section_node_id: payloadString(payload, "section_node_id") || null,
        title: payloadString(payload, "title"),
        section_title: payloadString(payload, "section_title") || null,
        canonical_url: payloadString(payload, "canonical_url"),
        source_path: payloadString(payload, "source_path"),
        start_line: payloadNumber(payload, "start_line"),
        end_line: payloadNumber(payload, "end_line"),
        content_sha256: payloadString(payload, "content_sha256"),
        text_sha256: payloadString(payload, "text_sha256"),
      };
    });
    return { release_id: releaseId, query, top_k: topK, hits };
  } finally {
    clearTimeout(timer);
  }
}

function contextText(result: RetrievalResult): string {
  return result.hits
    .slice(0, 8)
    .map((hit, index) => {
      const location = hit.start_line && hit.end_line
        ? `${hit.source_path}:${hit.start_line}-${hit.end_line}`
        : hit.source_path;
      return [
        `[${index + 1}] ${hit.title}${hit.section_title ? ` / ${hit.section_title}` : ""}`,
        `Source: ${hit.canonical_url}`,
        `Locator: ${location}`,
        `Content SHA-256: ${hit.content_sha256}`,
      ].join("\n");
    })
    .join("\n\n");
}

async function answer(query: string, retrieval: RetrievalResult, env: Env): Promise<string> {
  const prompt = [
    "Answer only from the retrieved Daniel blog evidence below.",
    "If the evidence is insufficient, state that clearly.",
    "Cite supporting items as [1], [2], and so on.",
    "Do not claim that candidate data is production authority.",
    "",
    `Question: ${query}`,
    "",
    contextText(retrieval),
  ].join("\n");
  const response = await env.AI.run(required(env.ANSWER_MODEL, "ANSWER_MODEL") as keyof AiModels, {
    messages: [
      { role: "system", content: "You are a source-grounded internal knowledge assistant." },
      { role: "user", content: prompt },
    ],
    max_tokens: 900,
    temperature: 0.1,
  } as never);
  const object = response as Record<string, unknown>;
  const text = object.response || (object.result as Record<string, unknown>)?.response;
  if (typeof text !== "string" || !text.trim()) {
    throw new Error("answer model returned no text");
  }
  return text.trim();
}

async function handle(request: Request, env: Env): Promise<Response> {
  if (!new URL(request.url).pathname.startsWith("/api/m25/")) {
    return jsonResponse({ error: "not_found" }, 404);
  }
  const identity = await verifyAccess(request, env);
  const url = new URL(request.url);
  if (url.pathname === "/api/m25/health") {
    return jsonResponse({
      status: "ok",
      release_id: env.CANDIDATE_RELEASE_ID,
      source_commit_sha: env.SOURCE_COMMIT_SHA,
      admission_sha256: env.ADMISSION_SHA256,
      candidate_runtime_enabled: env.CANDIDATE_RUNTIME_ENABLED === "true",
      authenticated_subject_present: Boolean(identity.sub),
      production_authority: false,
    });
  }
  if (!["GET", "POST"].includes(request.method)) {
    return jsonResponse({ error: "method_not_allowed" }, 405);
  }
  const body = await bodyObject(request);
  const parsed = parseQuery(request, url, body, env);
  const retrieval = await retrieve(parsed.query, parsed.topK, env);
  if (url.pathname === "/api/m25/retrieve") {
    return jsonResponse({
      schema_version: "knowledge-engine-m25-retrieval/v1",
      ...retrieval,
      production_authority: false,
    });
  }
  if (url.pathname === "/api/m25/query") {
    const groundedAnswer = await answer(parsed.query, retrieval, env);
    return jsonResponse({
      schema_version: "knowledge-engine-m25-grounded-answer/v1",
      release_id: retrieval.release_id,
      query: retrieval.query,
      answer: groundedAnswer,
      citations: retrieval.hits,
      source_commit_sha: env.SOURCE_COMMIT_SHA,
      admission_sha256: env.ADMISSION_SHA256,
      production_authority: false,
    });
  }
  return jsonResponse({ error: "not_found" }, 404);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      return await handle(request, env);
    } catch (error) {
      const message = error instanceof Error ? error.message : "unknown error";
      const status = message.includes("Access assertion") ? 401 : 400;
      return jsonResponse(
        {
          error: status === 401 ? "unauthorized" : "candidate_query_failed",
          message,
          production_authority: false,
        },
        status,
      );
    }
  },
} satisfies ExportedHandler<Env>;
