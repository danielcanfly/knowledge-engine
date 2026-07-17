import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import {
  CONTRACT_SHA256,
  REQUEST_SCHEMA,
  executeObservation,
  handleRequest,
  validateBody,
} from "./worker.mjs";

const VECTOR_DIMENSION = 1024;
const QUERY_COUNT = 24;
const DENSE_LIMIT = 50;

function digest(text) {
  return createHash("sha256").update(text).digest("hex");
}

function requestBody() {
  const variants = [];
  for (let probe = 1; probe <= 8; probe += 1) {
    for (let variant = 1; variant <= 3; variant += 1) {
      const queryText = `probe ${probe} variant ${variant}`;
      variants.push({
        variant_id: `r1-probe-${String(probe).padStart(2, "0")}-v${variant}`,
        query_sha256: digest(queryText),
        query_text: queryText,
      });
    }
  }
  return {
    schema_version: REQUEST_SCHEMA,
    contract_sha256: CONTRACT_SHA256,
    nonce: "0".repeat(32),
    variants,
  };
}

function collectionPayload() {
  return {
    status: "ok",
    result: {
      status: "green",
      points_count: 107,
      indexed_vectors_count: 0,
      config: {
        params: {
          vectors: {
            default: { size: VECTOR_DIMENSION, distance: "Cosine" },
          },
          sparse_vectors: null,
        },
      },
    },
  };
}

function rankedPoint(index, score) {
  return {
    id: `00000000-0000-0000-0000-${String(index).padStart(12, "0")}`,
    score,
    payload: {
      section_id: `section-${String(index).padStart(3, "0")}`,
    },
  };
}

function batchPayload() {
  return {
    status: "ok",
    result: Array.from({ length: QUERY_COUNT }, () => ({
      points: Array.from(
        { length: DENSE_LIMIT },
        (_, index) => rankedPoint(index, 1 - index / 1000),
      ),
    })),
  };
}

function vector(index) {
  const output = Array(VECTOR_DIMENSION).fill(0);
  output[index % VECTOR_DIMENSION] = 1;
  return output;
}

test("validateBody accepts exactly 24 unique digests", async () => {
  const body = requestBody();
  const raw = JSON.stringify(body);
  const request = new Request("https://worker.example/v1/m23-7-r3-8/observe", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Content-Length": String(Buffer.byteLength(raw)),
    },
    body: raw,
  });
  const validated = await validateBody(request);
  assert.equal(validated.variants.length, QUERY_COUNT);
  assert.equal(new Set(validated.variants.map((item) => item.queryDigest)).size, 24);
});

test("validateBody rejects duplicate query identity", async () => {
  const body = requestBody();
  body.variants[1].query_sha256 = body.variants[0].query_sha256;
  body.variants[1].query_text = body.variants[0].query_text;
  const raw = JSON.stringify(body);
  const request = new Request("https://worker.example/v1/m23-7-r3-8/observe", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Content-Length": String(Buffer.byteLength(raw)),
    },
    body: raw,
  });
  await assert.rejects(validateBody(request), /query-digest-duplicate/);
});

test("executeObservation performs one AI batch and one section-id-only Qdrant query batch", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({
      url: String(url),
      method: init.method || "GET",
      body: init.body ? JSON.parse(init.body) : null,
    });
    if (String(url).endsWith("/points/query/batch")) {
      return new Response(JSON.stringify(batchPayload()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify(collectionPayload()), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  let aiCalls = 0;
  const env = {
    QDRANT_URL: "https://qdrant.example",
    QDRANT_API_KEY: "q".repeat(32),
    AI: {
      run: async (_model, payload) => {
        aiCalls += 1;
        assert.equal(payload.text.length, QUERY_COUNT);
        return { data: payload.text.map((_text, index) => vector(index)) };
      },
    },
  };
  const validated = {
    nonce: "0".repeat(32),
    variants: requestBody().variants.map((item) => ({
      variantId: item.variant_id,
      queryDigest: item.query_sha256,
      queryText: item.query_text,
    })),
  };
  const ticks = [0, 0, 400, 400, 750, 750];
  let cursor = 0;
  try {
    const result = await executeObservation(
      env,
      validated,
      () => ticks[cursor++] ?? 750,
    );
    assert.equal(aiCalls, 1);
    assert.deepEqual(
      calls.map((item) => item.method),
      ["GET", "POST", "GET"],
    );
    const batch = calls[1].body;
    assert.equal(batch.searches.length, QUERY_COUNT);
    assert.deepEqual(batch, {
      searches: Array.from({ length: QUERY_COUNT }, (_, index) => ({
        query: vector(index),
        using: "default",
        params: {
          hnsw_ef: DENSE_LIMIT,
          exact: false,
        },
        limit: DENSE_LIMIT,
        with_payload: ["section_id"],
        with_vector: false,
      })),
    });
    assert.equal(result.external_calls.workers_ai_binding, 1);
    assert.equal(result.external_calls.qdrant_query_batch, 1);
    assert.equal(result.external_calls.qdrant_vector_scroll, 0);
    assert.equal(result.external_calls.qdrant_write, 0);
    assert.equal(result.variants.length, QUERY_COUNT);
    assert.equal(result.timings.shadow_ms, 750);
    assert.equal(result.authority.protected_mutations_dispatched, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("handleRequest rejects an invalid bearer token", async () => {
  const body = requestBody();
  const raw = JSON.stringify(body);
  const request = new Request("https://worker.example/v1/m23-7-r3-8/observe", {
    method: "POST",
    headers: {
      Authorization: "Bearer wrong",
      "Content-Type": "application/json",
      "Content-Length": String(Buffer.byteLength(raw)),
    },
    body: raw,
  });
  const response = await handleRequest(request, {
    M23_R3_8_OPERATOR_TOKEN: "s".repeat(32),
  });
  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), {
    status: "error",
    code: "unauthorized",
  });
});
