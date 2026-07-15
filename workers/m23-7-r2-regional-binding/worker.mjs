const MODEL = "@cf/baai/bge-m3";
const COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024";
const VECTOR_NAME = "default";
const VECTOR_DIMENSION = 1024;
const EXPECTED_POINTS = 107;
const SAMPLE_CAP = 8;
const TOP_K = 5;
const MAX_BODY_BYTES = 32768;
const RESPONSE_SCHEMA = "knowledge-engine-m23-7-r2-binding-worker-response/v1";
const REQUEST_SCHEMA = "knowledge-engine-m23-7-r2-binding-worker-request/v1";
const QDRANT_RELEASE = "m23pilot-a07eb79e381ca7e635cc9139";
const QDRANT_MANIFEST =
  "a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9";

class WorkerFailure extends Error {
  constructor(code, status = 400) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

function responseJson(value, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...extraHeaders,
    },
  });
}

async function sha256Hex(value) {
  const encoded = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", encoded);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function timingSafeEqualText(left, right) {
  const [leftDigest, rightDigest] = await Promise.all([sha256Hex(left), sha256Hex(right)]);
  if (leftDigest.length !== rightDigest.length) {
    return false;
  }
  let difference = 0;
  for (let index = 0; index < leftDigest.length; index += 1) {
    difference |= leftDigest.charCodeAt(index) ^ rightDigest.charCodeAt(index);
  }
  return difference === 0;
}

function assertCondition(condition, code, status = 400) {
  if (!condition) {
    throw new WorkerFailure(code, status);
  }
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function canonicalDigestInput(probeId, queryText) {
  return JSON.stringify(["m23-7-r1", probeId, queryText]);
}

async function validateBody(request) {
  const contentLength = request.headers.get("content-length");
  assertCondition(contentLength !== null, "content-length-required", 411);
  const declaredLength = Number(contentLength);
  assertCondition(Number.isInteger(declaredLength), "content-length-invalid");
  assertCondition(declaredLength > 0 && declaredLength <= MAX_BODY_BYTES, "body-size-invalid", 413);
  const raw = await request.text();
  assertCondition(new TextEncoder().encode(raw).byteLength <= MAX_BODY_BYTES, "body-too-large", 413);
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    throw new WorkerFailure("invalid-json");
  }
  assertCondition(isObject(body), "body-shape-drift");
  assertCondition(body.schema_version === REQUEST_SCHEMA, "request-schema-drift");
  assertCondition(typeof body.nonce === "string" && /^[a-f0-9]{32}$/.test(body.nonce), "nonce-invalid");
  assertCondition(Array.isArray(body.queries) && body.queries.length === SAMPLE_CAP, "query-count-drift");

  const seenProbeIds = new Set();
  const queries = [];
  for (const item of body.queries) {
    assertCondition(isObject(item), "query-shape-drift");
    const probeId = item.probe_id;
    const queryDigest = item.query_digest;
    const targetSectionId = item.target_section_id;
    const queryText = item.query_text;
    assertCondition(typeof probeId === "string" && /^r1-probe-[0-9]{2}$/.test(probeId), "probe-id-invalid");
    assertCondition(!seenProbeIds.has(probeId), "probe-id-duplicate");
    seenProbeIds.add(probeId);
    assertCondition(typeof queryDigest === "string" && /^[a-f0-9]{64}$/.test(queryDigest), "query-digest-invalid");
    assertCondition(typeof targetSectionId === "string" && targetSectionId.length > 0 && targetSectionId.length <= 300, "target-id-invalid");
    assertCondition(typeof queryText === "string" && queryText.length > 0 && queryText.length <= 240, "query-text-invalid");
    const calculatedDigest = await sha256Hex(canonicalDigestInput(probeId, queryText));
    assertCondition(await timingSafeEqualText(calculatedDigest, queryDigest), "query-digest-drift");
    queries.push({ probeId, queryDigest, targetSectionId, queryText });
  }
  return { nonce: body.nonce, queries };
}

function validateVector(vector) {
  assertCondition(Array.isArray(vector) && vector.length === VECTOR_DIMENSION, "vector-dimension-drift", 502);
  let sumSquares = 0;
  const numeric = vector.map((value) => {
    assertCondition(typeof value === "number" && Number.isFinite(value), "vector-value-invalid", 502);
    sumSquares += value * value;
    return value;
  });
  const norm = Math.sqrt(sumSquares);
  assertCondition(Number.isFinite(norm) && norm > 0, "vector-norm-invalid", 502);
  return numeric.map((value) => value / norm);
}

function parseEmbeddingRows(payload) {
  const result = isObject(payload) && isObject(payload.result) ? payload.result : payload;
  let data = isObject(result) ? result.data : undefined;
  if (!Array.isArray(data) && isObject(payload)) {
    data = payload.data;
  }
  assertCondition(Array.isArray(data), "embedding-response-shape-drift", 502);
  return data.map((item) => {
    if (isObject(item) && Array.isArray(item.embedding)) {
      return validateVector(item.embedding);
    }
    return validateVector(item);
  });
}

function validateCollection(payload) {
  assertCondition(isObject(payload), "collection-response-shape-drift", 502);
  const result = payload.result;
  assertCondition(isObject(result), "collection-result-missing", 502);
  const config = result.config;
  const params = isObject(config) ? config.params : undefined;
  const vectors = isObject(params) ? params.vectors : undefined;
  const vector = isObject(vectors) ? vectors[VECTOR_NAME] : undefined;
  const sparseVectors = isObject(params) ? params.sparse_vectors : undefined;
  assertCondition(result.status === "green", "collection-not-green", 502);
  assertCondition(result.points_count === EXPECTED_POINTS, "point-count-drift", 502);
  assertCondition(isObject(vector), "named-vector-missing", 502);
  assertCondition(vector.size === VECTOR_DIMENSION, "collection-dimension-drift", 502);
  assertCondition(vector.distance === "Cosine", "collection-distance-drift", 502);
  assertCondition(
    sparseVectors === undefined || sparseVectors === null || isEmptyObject(sparseVectors),
    "sparse-vector-drift",
    502,
  );
  assertCondition(Number.isInteger(result.indexed_vectors_count) && result.indexed_vectors_count >= 0, "indexed-count-invalid", 502);
  return {
    status: "green",
    points_count: EXPECTED_POINTS,
    indexed_vectors_count: result.indexed_vectors_count,
    vector_name: VECTOR_NAME,
    vector_dimension: VECTOR_DIMENSION,
    distance: "Cosine",
    sparse_vectors: null,
    read_only: true,
  };
}

function isEmptyObject(value) {
  return isObject(value) && Object.keys(value).length === 0;
}

async function qdrantFetch(env, path, init = {}) {
  assertCondition(typeof env.QDRANT_URL === "string" && env.QDRANT_URL.startsWith("https://"), "qdrant-url-invalid", 500);
  assertCondition(typeof env.QDRANT_API_KEY === "string" && env.QDRANT_API_KEY.length >= 16, "qdrant-key-invalid", 500);
  const baseUrl = env.QDRANT_URL.replace(/\/+$/, "");
  return fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      "api-key": env.QDRANT_API_KEY,
      ...(init.headers || {}),
    },
  });
}

async function collectionSnapshot(env) {
  const response = await qdrantFetch(env, `/collections/${encodeURIComponent(COLLECTION)}`);
  assertCondition(response.ok, "qdrant-collection-unavailable", 502);
  return validateCollection(await response.json());
}

function validateRankedPoint(raw) {
  assertCondition(isObject(raw) && isObject(raw.payload), "ranked-point-shape-drift", 502);
  const payload = raw.payload;
  const expected = {
    audience: "public",
    source_membership: "evaluation-only-pending-proposal",
    release_id: QDRANT_RELEASE,
    release_manifest_sha256: QDRANT_MANIFEST,
    vector_name: VECTOR_NAME,
    vector_dimension: VECTOR_DIMENSION,
    embedding_model: MODEL,
    canonical_knowledge: false,
    candidate_release_eligible: false,
    production_authority: false,
  };
  for (const [key, value] of Object.entries(expected)) {
    assertCondition(payload[key] === value, `ranked-point-${key}-drift`, 502);
  }
  assertCondition(typeof payload.section_id === "string" && payload.section_id.length > 0, "ranked-section-missing", 502);
  assertCondition(typeof raw.score === "number" && Number.isFinite(raw.score), "ranked-score-invalid", 502);
  assertCondition(raw.score >= -1 && raw.score <= 1, "ranked-score-range-drift", 502);
  return { score: raw.score, sectionId: payload.section_id };
}

function parseBatchResults(payload) {
  assertCondition(isObject(payload) && Array.isArray(payload.result), "batch-response-shape-drift", 502);
  assertCondition(payload.result.length === SAMPLE_CAP, "batch-result-count-drift", 502);
  return payload.result.map((item) => {
    assertCondition(isObject(item) && Array.isArray(item.points), "batch-points-shape-drift", 502);
    const ranked = item.points.map(validateRankedPoint);
    ranked.sort((left, right) => right.score - left.score || left.sectionId.localeCompare(right.sectionId));
    return ranked.map((item) => item.sectionId);
  });
}

async function executeComparison(env, validated, now = () => performance.now()) {
  assertCondition(env.AI && typeof env.AI.run === "function", "ai-binding-missing", 500);
  const collectionBefore = await collectionSnapshot(env);
  const queryTexts = validated.queries.map((item) => item.queryText);

  const shadowStarted = now();
  const providerStarted = now();
  const embeddingPayload = await env.AI.run(MODEL, { text: queryTexts });
  const providerFinished = now();
  const vectors = parseEmbeddingRows(embeddingPayload);
  assertCondition(vectors.length === SAMPLE_CAP, "embedding-count-drift", 502);

  const qdrantStarted = now();
  const batchResponse = await qdrantFetch(
    env,
    `/collections/${encodeURIComponent(COLLECTION)}/points/query/batch`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        searches: vectors.map((vector) => ({
          query: vector,
          using: VECTOR_NAME,
          limit: TOP_K,
          with_payload: true,
          with_vector: false,
        })),
      }),
    },
  );
  assertCondition(batchResponse.ok, "qdrant-batch-unavailable", 502);
  const rankings = parseBatchResults(await batchResponse.json());
  const qdrantFinished = now();
  const shadowFinished = now();
  const collectionAfter = await collectionSnapshot(env);
  assertCondition(JSON.stringify(collectionBefore) === JSON.stringify(collectionAfter), "collection-mutated", 502);

  const providerMs = Math.max(0, Math.ceil(providerFinished - providerStarted));
  const qdrantMs = Math.max(0, Math.ceil(qdrantFinished - qdrantStarted));
  const shadowMs = Math.max(0, Math.ceil(shadowFinished - shadowStarted));
  const cases = validated.queries.map((item, index) => ({
    probe_id: item.probeId,
    query_digest: item.queryDigest,
    target_section_id: item.targetSectionId,
    ranked_section_ids: rankings[index],
    raw_query_persisted: false,
    output_influenced: false,
  }));

  return {
    schema_version: RESPONSE_SCHEMA,
    status: "ok",
    nonce: validated.nonce,
    query_digests: validated.queries.map((item) => item.queryDigest),
    timings: {
      provider_ms: providerMs,
      qdrant_ms: qdrantMs,
      shadow_ms: shadowMs,
    },
    collection_before: collectionBefore,
    collection_after: collectionAfter,
    cases,
    acceptance: {
      error_rate: 0.0,
      acl_violation_rate: 0.0,
      output_influence_rate: 0.0,
    },
    privacy: {
      compiled_raw_queries_persisted: false,
      raw_answers_persisted: false,
      credentials_persisted: false,
      service_urls_persisted: false,
      arbitrary_exception_text_persisted: false,
    },
    authority: {
      production_retrieval: "lexical",
      candidate_mode_enabled: false,
      semantic_output_served: false,
      production_authority: false,
      protected_mutations_dispatched: false,
    },
    external_calls: {
      workers_ai_binding: 1,
      qdrant_collection_reads: 2,
      qdrant_query_batch: 1,
      qdrant_write: 0,
    },
  };
}

async function handleRequest(request, env) {
  try {
    const url = new URL(request.url);
    assertCondition(request.method === "POST", "method-not-allowed", 405);
    assertCondition(url.pathname === "/v1/m23-7-r2/compare", "route-not-found", 404);
    assertCondition(typeof env.M23_R2_OPERATOR_TOKEN === "string" && env.M23_R2_OPERATOR_TOKEN.length >= 32, "operator-secret-missing", 500);
    const authorization = request.headers.get("authorization") || "";
    const expected = `Bearer ${env.M23_R2_OPERATOR_TOKEN}`;
    assertCondition(await timingSafeEqualText(authorization, expected), "unauthorized", 401);
    const validated = await validateBody(request);
    const result = await executeComparison(env, validated);
    return responseJson(result, 200, {
      "Server-Timing": `workers-ai;dur=${result.timings.provider_ms}, qdrant;dur=${result.timings.qdrant_ms}`,
    });
  } catch (error) {
    if (error instanceof WorkerFailure) {
      return responseJson({ status: "error", code: error.code }, error.status);
    }
    return responseJson({ status: "error", code: "internal-failure" }, 500);
  }
}

export {
  REQUEST_SCHEMA,
  RESPONSE_SCHEMA,
  executeComparison,
  handleRequest,
  parseEmbeddingRows,
  timingSafeEqualText,
  validateBody,
};

export default { fetch: handleRequest };
