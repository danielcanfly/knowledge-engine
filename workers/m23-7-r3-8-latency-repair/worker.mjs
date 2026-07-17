const MODEL = "@cf/baai/bge-m3";
const COLLECTION = "llm_wiki_m23_r3_5_candidate_8eed54902c73";
const HISTORICAL_COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024";
const VECTOR_NAME = "default";
const VECTOR_DIMENSION = 1024;
const EXPECTED_POINTS = 107;
const QUERY_COUNT = 24;
const DENSE_LIMIT = 50;
const MAX_BODY_BYTES = 65536;
const SINGLE_QUERY_CONCURRENCY = 6;
const CONTRACT_SHA256 =
  "108e749661f47861472499475591eed2b5baf485920399bb48b6413658e287a0";
const REQUEST_SCHEMA = "knowledge-engine-m23-7-r3-8-worker-request/v1";
const RESPONSE_SCHEMA = "knowledge-engine-m23-7-r3-8-worker-response/v1";
const ROUTE = "/v1/m23-7-r3-8/observe";

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

function assertCondition(condition, code, status = 400) {
  if (!condition) {
    throw new WorkerFailure(code, status);
  }
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isEmptyObject(value) {
  return isObject(value) && Object.keys(value).length === 0;
}

async function sha256Hex(value) {
  const encoded = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", encoded);
  return Array.from(
    new Uint8Array(digest),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}

async function timingSafeEqualText(left, right) {
  const [leftDigest, rightDigest] = await Promise.all([
    sha256Hex(left),
    sha256Hex(right),
  ]);
  if (leftDigest.length !== rightDigest.length) {
    return false;
  }
  let difference = 0;
  for (let index = 0; index < leftDigest.length; index += 1) {
    difference |= leftDigest.charCodeAt(index) ^ rightDigest.charCodeAt(index);
  }
  return difference === 0;
}

async function validateBody(request) {
  const contentLength = request.headers.get("content-length");
  assertCondition(contentLength !== null, "content-length-required", 411);
  const declaredLength = Number(contentLength);
  assertCondition(
    Number.isInteger(declaredLength) &&
      declaredLength > 0 &&
      declaredLength <= MAX_BODY_BYTES,
    "body-size-invalid",
    413,
  );
  const raw = await request.text();
  assertCondition(
    new TextEncoder().encode(raw).byteLength <= MAX_BODY_BYTES,
    "body-too-large",
    413,
  );
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    throw new WorkerFailure("invalid-json");
  }
  assertCondition(isObject(body), "body-shape-drift");
  assertCondition(body.schema_version === REQUEST_SCHEMA, "request-schema-drift");
  assertCondition(
    body.contract_sha256 === CONTRACT_SHA256,
    "contract-digest-drift",
  );
  assertCondition(
    typeof body.nonce === "string" && /^[a-f0-9]{32}$/.test(body.nonce),
    "nonce-invalid",
  );
  assertCondition(
    Array.isArray(body.variants) && body.variants.length === QUERY_COUNT,
    "query-count-drift",
  );
  const seenIds = new Set();
  const seenDigests = new Set();
  const variants = [];
  for (const item of body.variants) {
    assertCondition(isObject(item), "variant-shape-drift");
    const variantId = item.variant_id;
    const queryDigest = item.query_sha256;
    const queryText = item.query_text;
    assertCondition(
      typeof variantId === "string" &&
        /^r1-probe-[0-9]{2}-v[1-3]$/.test(variantId),
      "variant-id-invalid",
    );
    assertCondition(!seenIds.has(variantId), "variant-id-duplicate");
    seenIds.add(variantId);
    assertCondition(
      typeof queryDigest === "string" && /^[a-f0-9]{64}$/.test(queryDigest),
      "query-digest-invalid",
    );
    assertCondition(!seenDigests.has(queryDigest), "query-digest-duplicate");
    seenDigests.add(queryDigest);
    assertCondition(
      typeof queryText === "string" &&
        queryText.length > 0 &&
        queryText.length <= 1000,
      "query-text-invalid",
    );
    assertCondition(
      (await sha256Hex(queryText)) === queryDigest,
      "query-digest-drift",
    );
    variants.push({ variantId, queryDigest, queryText });
  }
  return { nonce: body.nonce, variants };
}

function validateVector(vector) {
  assertCondition(
    Array.isArray(vector) && vector.length === VECTOR_DIMENSION,
    "vector-dimension-drift",
    502,
  );
  let sumSquares = 0;
  const numeric = vector.map((value) => {
    assertCondition(
      typeof value === "number" && Number.isFinite(value),
      "vector-value-invalid",
      502,
    );
    sumSquares += value * value;
    return value;
  });
  const norm = Math.sqrt(sumSquares);
  assertCondition(
    Number.isFinite(norm) && norm > 0,
    "vector-norm-invalid",
    502,
  );
  return numeric.map((value) => value / norm);
}

function parseEmbeddingRows(payload) {
  const result = isObject(payload) && isObject(payload.result)
    ? payload.result
    : payload;
  let data = isObject(result) ? result.data : undefined;
  if (!Array.isArray(data) && isObject(payload)) {
    data = payload.data;
  }
  assertCondition(
    Array.isArray(data) && data.length === QUERY_COUNT,
    "embedding-response-shape-drift",
    502,
  );
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
    sparseVectors === undefined ||
      sparseVectors === null ||
      isEmptyObject(sparseVectors),
    "sparse-vector-drift",
    502,
  );
  assertCondition(
    Number.isInteger(result.indexed_vectors_count) &&
      result.indexed_vectors_count >= 0,
    "indexed-count-invalid",
    502,
  );
  return {
    status: "green",
    points_count: EXPECTED_POINTS,
    indexed_vectors_count: result.indexed_vectors_count,
    vector_name: VECTOR_NAME,
    vector_size: VECTOR_DIMENSION,
    vector_distance: "Cosine",
    sparse_vectors: null,
    read_only: true,
  };
}

async function qdrantFetch(env, path, init = {}) {
  assertCondition(
    typeof env.QDRANT_URL === "string" &&
      env.QDRANT_URL.startsWith("https://"),
    "qdrant-url-invalid",
    500,
  );
  assertCondition(
    typeof env.QDRANT_API_KEY === "string" &&
      env.QDRANT_API_KEY.length >= 16,
    "qdrant-key-invalid",
    500,
  );
  const baseUrl = env.QDRANT_URL.replace(/\/+$/, "");
  return fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      "api-key": env.QDRANT_API_KEY,
      ...(init.headers || {}),
    },
  });
}

async function mapBounded(items, limit, callback) {
  const results = Array(items.length);
  let next = 0;
  const workerCount = Math.min(limit, items.length);
  await Promise.all(
    Array.from({ length: workerCount }, async () => {
      while (next < items.length) {
        const index = next;
        next += 1;
        results[index] = await callback(items[index], index);
      }
    }),
  );
  return results;
}

async function collectionSnapshot(env) {
  const response = await qdrantFetch(
    env,
    `/collections/${encodeURIComponent(COLLECTION)}`,
  );
  assertCondition(response.ok, "qdrant-collection-unavailable", 502);
  return validateCollection(await response.json());
}

function validateCandidatePayload(raw) {
  assertCondition(
    isObject(raw) && isObject(raw.payload),
    "candidate-point-shape-drift",
    502,
  );
  const payload = raw.payload;
  const expected = {
    payload_schema_version: "knowledge-engine-m23-qdrant-payload/v2",
    source_membership: "r3-6-candidate-live-acceptance-only",
    candidate_collection: COLLECTION,
    candidate_artifact_sha256:
      "8eed54902c73314ac2e5d5e187a788e44941dae250d9823d45b71ec57d1e1371",
    candidate_reingestion_issue: 508,
    vector_name: VECTOR_NAME,
    vector_dimension: VECTOR_DIMENSION,
    canonical_knowledge: false,
    candidate_release_eligible: false,
    production_authority: false,
  };
  for (const [key, value] of Object.entries(expected)) {
    assertCondition(
      payload[key] === value,
      `ranked-point-${key}-drift`,
      502,
    );
  }
  assertCondition(
    typeof payload.section_id === "string" &&
      payload.section_id.length > 0 &&
      payload.section_id.length <= 300,
    "ranked-section-missing",
    502,
  );
  return payload.section_id;
}

function validateRankedPoint(raw) {
  assertCondition(
    isObject(raw) && isObject(raw.payload),
    "ranked-point-shape-drift",
    502,
  );
  const sectionId = validateCandidatePayload(raw);
  assertCondition(
    typeof raw.score === "number" &&
      Number.isFinite(raw.score) &&
      raw.score >= -1.0001 &&
      raw.score <= 1.0001,
    "ranked-score-invalid",
    502,
  );
  return { score: raw.score, sectionId };
}

function parseBatchResults(payload) {
  assertCondition(
    isObject(payload) &&
      Array.isArray(payload.result) &&
      payload.result.length === QUERY_COUNT,
    "batch-response-shape-drift",
    502,
  );
  return payload.result.map((item) => {
    const points = Array.isArray(item) ? item : item.points;
    assertCondition(
      Array.isArray(points) && points.length === DENSE_LIMIT,
      "batch-points-shape-drift",
      502,
    );
    const ranked = points.map(validateRankedPoint);
    ranked.sort(
      (left, right) =>
        right.score - left.score ||
        left.sectionId.localeCompare(right.sectionId),
    );
    const ids = ranked.map((item) => item.sectionId);
    assertCondition(
      new Set(ids).size === DENSE_LIMIT,
      "ranked-section-duplicate",
      502,
    );
    return ids;
  });
}

function parseSingleQueryResults(payloads) {
  assertCondition(
    Array.isArray(payloads) && payloads.length === QUERY_COUNT,
    "single-query-response-count-drift",
    502,
  );
  return payloads.map((payload) => {
    const points =
      isObject(payload) && isObject(payload.result)
        ? payload.result.points
        : undefined;
    assertCondition(
      Array.isArray(points) && points.length === DENSE_LIMIT,
      "single-query-points-shape-drift",
      502,
    );
    const ranked = points.map(validateRankedPoint);
    ranked.sort(
      (left, right) =>
        right.score - left.score ||
        left.sectionId.localeCompare(right.sectionId),
    );
    const ids = ranked.map((item) => item.sectionId);
    assertCondition(
      new Set(ids).size === DENSE_LIMIT,
      "ranked-section-duplicate",
      502,
    );
    return ids;
  });
}

async function executeObservation(env, validated, now = () => performance.now()) {
  assertCondition(
    env.AI && typeof env.AI.run === "function",
    "ai-binding-missing",
    500,
  );
  assertCondition(
    COLLECTION !== HISTORICAL_COLLECTION,
    "collection-alias",
    500,
  );
  const collectionBefore = await collectionSnapshot(env);
  const queryTexts = validated.variants.map((item) => item.queryText);

  const shadowStarted = now();
  const providerStarted = now();
  const embeddingPayload = await env.AI.run(MODEL, { text: queryTexts });
  const providerFinished = now();
  const vectors = parseEmbeddingRows(embeddingPayload);

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
          limit: DENSE_LIMIT,
          with_payload: true,
          with_vector: false,
        })),
      }),
    },
  );
  let qdrantVectorScroll = 0;
  let qdrantSingleQuery = 0;
  let rankings;
  if (batchResponse.ok) {
    rankings = parseBatchResults(await batchResponse.json());
  } else {
    const singleResponses = await mapBounded(
      vectors,
      SINGLE_QUERY_CONCURRENCY,
      (vector) =>
        qdrantFetch(
          env,
          `/collections/${encodeURIComponent(COLLECTION)}/points/query?consistency=all`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              query: vector,
              using: VECTOR_NAME,
              limit: DENSE_LIMIT,
              with_payload: true,
              with_vector: false,
            }),
          },
        ),
    );
    qdrantSingleQuery = QUERY_COUNT;
    assertCondition(
      singleResponses.every((response) => response.ok),
      "qdrant-single-query-unavailable",
      502,
    );
    rankings = parseSingleQueryResults(
      await Promise.all(singleResponses.map((response) => response.json())),
    );
  }
  const qdrantFinished = now();
  const shadowFinished = now();

  const collectionAfter = await collectionSnapshot(env);
  assertCondition(
    JSON.stringify(collectionBefore) === JSON.stringify(collectionAfter),
    "collection-mutated",
    502,
  );

  const providerMs = Math.max(
    0,
    Math.ceil(providerFinished - providerStarted),
  );
  const qdrantMs = Math.max(0, Math.ceil(qdrantFinished - qdrantStarted));
  const shadowMs = Math.max(0, Math.ceil(shadowFinished - shadowStarted));

  return {
    schema_version: RESPONSE_SCHEMA,
    status: "ok",
    nonce: validated.nonce,
    collection_before: collectionBefore,
    collection_after: collectionAfter,
    timings: {
      provider_ms: providerMs,
      qdrant_ms: qdrantMs,
      shadow_ms: shadowMs,
    },
    variants: validated.variants.map((item, index) => ({
      variant_id: item.variantId,
      query_sha256: item.queryDigest,
      ranked_section_ids: rankings[index],
      raw_query_persisted: false,
      raw_answer_persisted: false,
    })),
    acceptance: {
      error_rate: 0.0,
      acl_violation_rate: 0.0,
      output_influence_rate: 0.0,
    },
    privacy: {
      raw_queries_persisted: false,
      raw_answers_persisted: false,
      credentials_persisted: false,
      service_urls_persisted: false,
      service_hostnames_persisted: false,
      arbitrary_exception_text_persisted: false,
    },
    authority: {
      production_retrieval: "lexical",
      semantic_output_served: false,
      production_authority: false,
      protected_mutations_dispatched: false,
      retrieval_quality_blocker_cleared: false,
      latency_blocker_cleared: false,
    },
    external_calls: {
      workers_ai_binding: 1,
      qdrant_collection_reads: 2,
      qdrant_query_batch: 1,
      qdrant_single_query: qdrantSingleQuery,
      qdrant_vector_scroll: qdrantVectorScroll,
      qdrant_write: 0,
      qdrant_delete: 0,
      qdrant_reindex: 0,
    },
  };
}

async function handleRequest(request, env) {
  try {
    const url = new URL(request.url);
    assertCondition(request.method === "POST", "method-not-allowed", 405);
    assertCondition(url.pathname === ROUTE, "route-not-found", 404);
    assertCondition(
      typeof env.M23_R3_8_OPERATOR_TOKEN === "string" &&
        env.M23_R3_8_OPERATOR_TOKEN.length >= 32,
      "operator-secret-missing",
      500,
    );
    const authorization = request.headers.get("authorization") || "";
    const expected = `Bearer ${env.M23_R3_8_OPERATOR_TOKEN}`;
    assertCondition(
      await timingSafeEqualText(authorization, expected),
      "unauthorized",
      401,
    );
    const validated = await validateBody(request);
    const result = await executeObservation(env, validated);
    return responseJson(result, 200, {
      "Server-Timing":
        `workers-ai;dur=${result.timings.provider_ms}, ` +
        `qdrant;dur=${result.timings.qdrant_ms}, ` +
        `shadow;dur=${result.timings.shadow_ms}`,
    });
  } catch (error) {
    if (error instanceof WorkerFailure) {
      return responseJson({ status: "error", code: error.code }, error.status);
    }
    return responseJson({ status: "error", code: "internal-failure" }, 500);
  }
}

export {
  CONTRACT_SHA256,
  REQUEST_SCHEMA,
  RESPONSE_SCHEMA,
  executeObservation,
  handleRequest,
  parseBatchResults,
  parseEmbeddingRows,
  timingSafeEqualText,
  validateBody,
};

export default { fetch: handleRequest };
