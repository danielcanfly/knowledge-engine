import assert from "node:assert/strict";
import test from "node:test";

import { REQUEST_SCHEMA, handleRequest } from "./worker.mjs";

const OPERATOR_TOKEN = "t".repeat(48);
const VECTOR_DIMENSION = 1024;
const RELEASE = "m23pilot-a07eb79e381ca7e635cc9139";
const MANIFEST = "a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9";

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function requestBody() {
  const queries = [];
  for (let index = 1; index <= 8; index += 1) {
    const probeId = `r1-probe-${String(index).padStart(2, "0")}`;
    const queryText = `Which source section supports governed concept number ${index}?`;
    queries.push({
      probe_id: probeId,
      query_digest: await sha256Hex(JSON.stringify(["m23-7-r1", probeId, queryText])),
      target_section_id: `target-section-${index}`,
      query_text: queryText,
    });
  }
  return {
    schema_version: REQUEST_SCHEMA,
    nonce: "a".repeat(32),
    queries,
  };
}

function collectionPayload(indexed = 0) {
  return {
    result: {
      status: "green",
      points_count: 107,
      indexed_vectors_count: indexed,
      config: {
        params: {
          vectors: { default: { size: 1024, distance: "Cosine" } },
          sparse_vectors: null,
        },
      },
    },
  };
}

function point(index) {
  return {
    id: `point-${index}`,
    score: 0.99,
    payload: {
      audience: "public",
      source_membership: "evaluation-only-pending-proposal",
      release_id: RELEASE,
      release_manifest_sha256: MANIFEST,
      vector_name: "default",
      vector_dimension: 1024,
      embedding_model: "@cf/baai/bge-m3",
      canonical_knowledge: false,
      candidate_release_eligible: false,
      production_authority: false,
      section_id: `target-section-${index}`,
    },
  };
}

function env() {
  return {
    M23_R2_OPERATOR_TOKEN: OPERATOR_TOKEN,
    QDRANT_URL: "https://qdrant.invalid",
    QDRANT_API_KEY: "q".repeat(32),
    AI: {
      calls: 0,
      async run(model, input) {
        this.calls += 1;
        assert.equal(model, "@cf/baai/bge-m3");
        assert.equal(input.text.length, 8);
        return {
          data: input.text.map((_, index) => {
            const vector = Array(VECTOR_DIMENSION).fill(0);
            vector[index] = 1;
            return vector;
          }),
        };
      },
    },
  };
}

async function makeRequest(body, token = OPERATOR_TOKEN) {
  const encoded = JSON.stringify(body);
  return new Request("https://worker.invalid/v1/m23-7-r2/compare", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Content-Length": String(new TextEncoder().encode(encoded).byteLength),
    },
    body: encoded,
  });
}

test("successful request uses one AI binding call and one Qdrant batch query", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (init.method === "POST") {
      const posted = JSON.parse(init.body);
      assert.equal(posted.searches.length, 8);
      for (const search of posted.searches) {
        assert.equal(search.using, "default");
        assert.equal(search.limit, 5);
        assert.equal(search.with_payload, true);
        assert.equal(search.with_vector, false);
        assert.equal("filter" in search, false);
      }
      return Response.json({
        result: Array.from({ length: 8 }, (_, index) => ({ points: [point(index + 1)] })),
      });
    }
    return Response.json(collectionPayload());
  };
  try {
    const body = await requestBody();
    const workerEnv = env();
    const response = await handleRequest(await makeRequest(body), workerEnv);
    assert.equal(response.status, 200);
    const payload = await response.json();
    assert.equal(payload.status, "ok");
    assert.equal(payload.query_digests.length, 8);
    assert.equal(payload.cases.length, 8);
    assert.equal(payload.external_calls.workers_ai_binding, 1);
    assert.equal(payload.external_calls.qdrant_query_batch, 1);
    assert.equal(payload.external_calls.qdrant_write, 0);
    assert.equal(workerEnv.AI.calls, 1);
    assert.equal(calls.length, 3);
    assert.equal(calls.filter((call) => call.init.method === "POST").length, 1);
    const encoded = JSON.stringify(payload);
    for (const query of body.queries) {
      assert.equal(encoded.includes(query.query_text), false);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("authorization fails closed before external calls", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error("must not be called");
  };
  try {
    const response = await handleRequest(await makeRequest(await requestBody(), "wrong-token"), env());
    assert.equal(response.status, 401);
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("query digest drift fails closed", async () => {
  const body = await requestBody();
  body.queries[0].query_digest = "0".repeat(64);
  const response = await handleRequest(await makeRequest(body), env());
  assert.equal(response.status, 400);
  const payload = await response.json();
  assert.equal(payload.code, "query-digest-drift");
});

test("collection identity mutation fails closed", async () => {
  const originalFetch = globalThis.fetch;
  let getCount = 0;
  globalThis.fetch = async (_url, init = {}) => {
    if (init.method === "POST") {
      return Response.json({
        result: Array.from({ length: 8 }, (_, index) => ({ points: [point(index + 1)] })),
      });
    }
    getCount += 1;
    return Response.json(collectionPayload(getCount === 1 ? 0 : 1));
  };
  try {
    const response = await handleRequest(await makeRequest(await requestBody()), env());
    assert.equal(response.status, 502);
    const payload = await response.json();
    assert.equal(payload.code, "collection-mutated");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
