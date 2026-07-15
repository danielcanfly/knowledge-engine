# M23.6.4 Bounded Worker and Queue Incremental Ingestion

## Status

Implementation candidate. Repository code and offline validation are authorised; Cloudflare deployment, Queue creation, Workers AI inference and Qdrant mutation are not authorised by this submilestone.

## Entry state

- Engine baseline: `baa0fb9bf89bb216dbc34d3fb633b6eee706f029`
- Qdrant pilot collection: `llm_wiki_m23_pilot_bge_m3_1024`
- Existing pilot points: 107
- M23.6.3 receipt SHA-256: `0e89d9971e6fd10505b5e36113e079629c444c371d01ac6d909d717270c7c21b`
- Source PR #19 remains draft, open and unmerged.
- Production retrieval remains `lexical`.

## Topology

The package `packages/m23-pilot-ingestion-worker` contains a Queue consumer named `llm-wiki-m23-pilot-embed-consumer`. Its only configured consumer queue is `llm-wiki-m23-pilot-embed`; repeatedly failed messages are isolated in `llm-wiki-m23-pilot-embed-dlq`.

The committed Wrangler configuration locks:

- `max_batch_size = 4`
- `max_batch_timeout = 10`
- `max_retries = 2`, producing at most three delivery attempts including the first attempt
- `max_concurrency = 2`
- `workers_dev = false`
- preview URLs disabled
- structured observability enabled
- `EXECUTION_ENABLED = false`

Cloudflare documents that Queue consumers support explicit per-message acknowledgement and retry, and that a DLQ receives messages after the configured retry ceiling. The implementation acknowledges terminal invalid or stale messages individually and retries only transient Workers AI, Qdrant or collection-availability failures.

## Incremental identity and idempotency

Each message has a deterministic `m23inc-<24 hex>` identity over canonical JSON. Each section carries:

- deterministic Qdrant point ID;
- new `text_sha256`;
- optional `expected_previous_text_sha256` optimistic precondition;
- complete derived-only payload;
- all authority flags fixed to false.

The consumer reads all current points for a message before embedding or writing:

1. Missing point plus null previous hash: `insert`.
2. Existing text hash equals new text hash: `skip-duplicate`.
3. Existing text hash equals expected previous hash: `replace`.
4. Any other identity or hash state: terminal `reject-stale` with no write for that message.

Deletes are not represented by the message schema and are forbidden.

## Failure isolation

Messages are validated and acknowledged independently. A malformed, oversized, wrong-collection, over-budget, authority-violating or stale message is terminal and is acknowledged after a structured rejection log. Transient external failures are retried with a bounded delay and are eventually isolated by the configured DLQ.

A message is not acknowledged until all of its non-skipped sections have been embedded and Qdrant reports a completed strong-ordering upsert. Re-delivery is safe because current `text_sha256` values turn already-completed work into `skip-duplicate` outcomes.

## Cost and volume gates

The producer-side deterministic planner enforces:

- at most 25 sections per message;
- at most 500 sections and USD 0.50 estimated cost per run;
- at most 2,000 sections and USD 2.00 estimated cost per day.

The consumer rechecks message, batch and run caps. No persistent daily budget ledger is created because permanent-ledger mutation is outside M23.6.4 authority. A later deployment plan must identify an explicitly authorised producer-side daily gate before messages can be enqueued.

## Security and deployment boundary

- Qdrant URL and API key are secret bindings and are never stored in source, config, logs or receipts.
- The Worker exposes no public function; its fetch handler always returns 404.
- The Qdrant collection, vector name, dimension and distance are checked before processing.
- Qdrant must use HTTPS.
- No public route, production collection, Source mutation, R2 write, pointer mutation, permanent ledger, deletion, credential rotation, public Graph Explorer or Graph Neural Retrieval is permitted.

Deployment requires a later explicit authority decision and fresh read-only preflight. M23.6.4 itself performs zero Cloudflare or Qdrant calls.
