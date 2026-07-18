import assert from "node:assert/strict";
import test from "node:test";

import { executeParallelObservation } from "./worker.mjs";

const QUERY_COUNT = 24;
const VECTOR_DIMENSION = 1024;
const DENSE_LIMIT = 50;

function vector(index) {
  const output = Array(VECTOR_DIMENSION).fill(0);
  output[index % VECTOR_DIMENSION] = 1;
  return output;
}

function collectionPayload() {
  return {
    result: {
      status: "green",
      points_count: 107,
      indexed_vectors_count: 0,
      config: {
        params: {
          vectors: { default: { size: VECTOR_DIMENSION, distance: "Cosine" } },
          sparse_vectors: null,
        },
      },
    },
  };
}

function batchPayload(count, offset) {
  return {
    result: Array.from({ length: count }, (_unused, queryIndex) =>
      Array.from({ length: DENSE_LIMIT }, (_item, rank) => ({
        score: 1 - rank / 1000,
        payload: {
          section_id: `q${String(offset + queryIndex).padStart(2, "0")}-section-${String(rank).padStart(3, "0")}`,
        },
      })),
    ),
  };
}

test("parallel observation issues four six-query batches and preserves order", async () => {
  const originalFetch = globalThis.fetch;
  const batchSizes = [];
  let queryOffset = 0;
  globalThis.fetch = async (url, init = {}) => {
    if (String(url).endsWith("/points/query/batch")) {
      const body = JSON.parse(init.body);
      const size = body.searches.length;
      const offset = queryOffset;
      queryOffset += size;
      batchSizes.push(size);
      return new Response(JSON.stringify(batchPayload(size, offset)), { status: 200 });
    }
    return new Response(JSON.stringify(collectionPayload()), { status: 200 });
  };

  const validated = {
    nonce: "0".repeat(32),
    variants: Array.from({ length: QUERY_COUNT }, (_unused, index) => ({
      variantId: `r1-probe-${String(Math.floor(index / 3) + 1).padStart(2, "0")}-v${(index % 3) + 1}`,
      queryDigest: String(index).padStart(64, "0"),
      queryText: `query-${index}`,
    })),
  };
  const env = {
    QDRANT_URL: "https://qdrant.example",
    QDRANT_API_KEY: "q".repeat(32),
    AI: {
      run: async (_model, payload) => ({
        data: payload.text.map((_text, index) => vector(index)),
      }),
    },
  };

  try {
    const result = await executeParallelObservation(env, validated);
    assert.deepEqual(batchSizes, [6, 6, 6, 6]);
    assert.equal(result.variants.length, QUERY_COUNT);
    assert.equal(result.variants[0].ranked_section_ids[0], "q00-section-000");
    assert.equal(result.variants[23].ranked_section_ids[0], "q23-section-000");
    assert.equal(result.external_calls.qdrant_query_batch, 1);
    assert.equal(result.external_calls.qdrant_single_query, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
