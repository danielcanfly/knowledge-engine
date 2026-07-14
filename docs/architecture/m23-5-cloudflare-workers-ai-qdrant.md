# M23.5 Cloudflare Workers AI + Qdrant execution lane

## Decision

Use Cloudflare Workers AI model `@cf/baai/bge-m3` to generate multilingual dense
embeddings and use Qdrant Cloud as the derived vector index. Cloudflare R2 remains
the source-object and immutable-release store. Markdown remains canonical.

The Mac mini is a benchmark, migration and fallback environment only. Routine
incremental ingestion must not require an operator to run local embedding jobs.

## Boundaries

This milestone adds a provider adapter and an index-write contract. It does not:

- deploy a Worker or Queue consumer;
- create or mutate a production Qdrant collection;
- write R2 objects or change release pointers;
- approve or merge `knowledge-source#19`;
- enable vector or hybrid retrieval in production;
- grant canonical, candidate-release or production authority to vectors.

`RETRIEVAL_MODE=lexical` remains the rollback-safe default.

## Data flow

1. Intake writes the raw source and normalized Markdown derivative to R2.
2. The compiler emits stable sections and content hashes.
3. Unchanged section hashes are skipped.
4. A queue or bounded batch invokes Workers AI with `@cf/baai/bge-m3`.
5. The provider returns ordered 1,024-dimensional dense vectors.
6. The engine builds deterministic Qdrant point IDs from model ID + section ID.
7. Qdrant stores the vector and a minimal payload containing provenance,
   audience, release identity and R2 object references.
8. A receipt records hashes and non-authority flags without recording secrets.

## Provider contract

- provider: `cloudflare-workers-ai`
- model: `@cf/baai/bge-m3`
- vector dimension: `1024`
- Unicode normalization: `NFKC`
- query instruction: none
- document instruction: none
- pooling and L2 normalization: provider-native
- Cloudflare model context window: 60,000 tokens
- batching preserves input order

The embedding generation step requires network access. The derived semantic
artifact does not require a network connection after it has been materialized,
which is why the inherited M20 artifact authority field remains
`runtime_network_required: false`.

## Qdrant contract

The adapter uses Qdrant's point upsert endpoint:

`PUT /collections/{collection_name}/points?wait=true&ordering=strong`

Every point contains:

- deterministic UUID point ID;
- one 1,024-dimensional dense vector;
- stable `section_id`;
- text SHA-256;
- model and provider identities;
- audience and caller-supplied provenance payload;
- explicit false flags for canonical, candidate-release and production authority.

An upsert is impossible unless the caller explicitly supplies
`allow_write=True` or CLI flag `--allow-qdrant-write`.

## Secrets

Set secrets outside the repository:

- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `QDRANT_URL`
- `QDRANT_API_KEY`

Receipts must record neither tokens nor API keys. A future Worker deployment must
use a Workers AI binding rather than calling the Cloudflare REST API from inside
the Worker. Qdrant credentials must be configured with `wrangler secret put`.

## CLI modes

Dry run, no network and no writes:

```bash
knowledge-m23-embed \
  --input sections.json \
  --output evidence/m23-5 \
  --collection knowledge-pilot
```

Generate embeddings but do not write Qdrant:

```bash
knowledge-m23-embed \
  --input sections.json \
  --output evidence/m23-5 \
  --collection knowledge-pilot \
  --execute
```

Explicit Qdrant pilot write:

```bash
knowledge-m23-embed \
  --input sections.json \
  --output evidence/m23-5 \
  --collection knowledge-pilot \
  --execute \
  --allow-qdrant-write
```

## Deployment sequence

1. Merge this bounded provider-contract PR.
2. Create a non-production Qdrant Cloud collection with cosine distance and
   dimension 1024.
3. Provision least-privilege Cloudflare and Qdrant credentials.
4. Run the frozen 16-query benchmark through the actual Workers AI endpoint.
5. Verify vector shape, hashes, latency, quota and M20 semantic artifact output.
6. Keep production retrieval lexical until benchmark and human review gates pass.
7. Add Queue/Worker automation in M23.6 after M23.5 selection evidence is accepted.

## Contract reconciliation

The managed embedding execution contract was reconciled against live GitHub evidence.
This reconciliation closes the implementation slice, not the whole M23.5 milestone.

- authoritative Engine issue: #377, still open;
- exact implementation base: `1d574c5085c8fecbe7423aded093ac205c30465b`;
- implementation PR: #378;
- accepted implementation head: `9be1c5d21252fbf58c41c38f62667d19cc8a07ee`;
- expected-head implementation merge: `37f9c1f910d799f1ac3f3d8836e70710fe6f0690`;
- implementation diff: seven files, 881 additions, no deletions;
- accepted-head CI: CI #766 and M23.5 Cloudflare Qdrant contract #4 passed;
- every triggered R2, M16, M17, M18, M23.2, M23.3 and M23.4 safeguard passed;
- PR conversation comments: none;
- submitted review threads: none;
- Source draft PR `knowledge-source#19`: remains open, draft and unmerged;
- Source main remains `a6ba738d910d01d2ae99b1968f0831989934c549`;
- Foundation main remains `e5ef644053d34e89c70d2ceb37521e1c59234832`.

No Cloudflare credential was used, no Qdrant collection was created or written, no R2
object or pointer changed, no production traffic changed, and no retrieval default
changed. Production mutation dispatched: false.

M23.5 remains incomplete until a non-production Qdrant collection and least-privilege
credentials exist, the frozen 16-query corpus is run through the actual Workers AI
endpoint, the returned vectors pass M20 verification, and the benchmark decision is
recorded. Until then, `RETRIEVAL_MODE=lexical` remains authoritative.
