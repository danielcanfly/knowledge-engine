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
