# M23.6.4 Worker and Queue Incremental Ingestion Reconciliation

## Closure status

M23.6.4 is accepted as a deployment-ready, disabled-by-default repository implementation. No Cloudflare Worker deployment, Queue creation, Workers AI inference or Qdrant mutation was dispatched by this submilestone.

## Accepted implementation

- Issue: `knowledge-engine#396`
- Parent: `knowledge-engine#383`
- Implementation PR: `knowledge-engine#397`
- Entry main: `baa0fb9bf89bb216dbc34d3fb633b6eee706f029`
- Accepted exact head: `2a5ce95d105484a77df5e5d7151c2c5e7238cd7d`
- Expected-head squash merge: `343bd53057868536b47179b97b32008e60ef00e3`

## Accepted exact-head workflows

All workflows associated with the accepted head completed successfully:

- CI run `29390704328`, run number 807
- R2 Release Integration run `29390704326`, run number 542
- M17 Architecture Canon Acceptance run `29390704361`, run number 140
- M18 Graph v2 acceptance run `29390704412`, run number 243
- M23.6.4 Worker Queue Incremental Ingestion run `29390704331`, run number 9

The dedicated M23.6.4 workflow passed Python linting, eight adversarial policy tests, deterministic acceptance replay, pinned Node dependency installation, strict TypeScript checking, Wrangler deployment dry-run, deployment-authority guards and secret/forbidden-mutation scans.

## Delivered contract

The accepted implementation locks the following non-production topology:

- Worker: `llm-wiki-m23-pilot-embed-consumer`
- Queue: `llm-wiki-m23-pilot-embed`
- DLQ: `llm-wiki-m23-pilot-embed-dlq`
- Qdrant collection: `llm_wiki_m23_pilot_bge_m3_1024`
- named vector: `default`
- vector dimension: 1024
- distance: `Cosine`
- embedding provider/model: Cloudflare Workers AI `@cf/baai/bge-m3`

The bounded execution contract is:

- maximum four Queue messages per consumer batch;
- maximum 25 sections per message;
- maximum 500 sections and USD 0.50 estimated cost per run;
- maximum 2,000 sections and USD 2.00 estimated cost per day;
- maximum concurrency two;
- two retries after initial delivery, for at most three delivery attempts;
- explicit per-message acknowledgement and retry;
- DLQ isolation after the retry ceiling;
- `EXECUTION_ENABLED=false` by default;
- no public Worker route.

## Idempotency and stale-event policy

The producer-side planner and Worker consumer implement deterministic message identities and point-level optimistic concurrency:

1. A missing point with no expected previous text digest is planned as `insert`.
2. A point whose existing text digest equals the new digest is `skip-duplicate`.
3. A point whose existing digest equals `expected_previous_text_sha256` is `replace`.
4. A point-ID collision, missing expected predecessor or optimistic-precondition mismatch is `reject-stale` and dispatches no write for that message.

A redelivery after a completed upsert becomes `skip-duplicate`, making Queue retries idempotent. Deletes are absent from the message schema and forbidden.

## Failure and safety model

Malformed, oversized, wrong-collection, over-budget, authority-violating and stale messages are terminal and individually acknowledged after structured rejection logging. Only transient Workers AI, Qdrant or collection-availability failures are retried. Qdrant access requires HTTPS, exact collection and vector-contract verification, strong ordering and `wait=true` completion semantics.

No API token, Qdrant key or service URL is committed or emitted into receipts. The Worker package uses secret binding names only.

## Preserved authority boundary

The following remained false throughout implementation, CI and merge:

- Cloudflare deployment dispatched;
- Queue or DLQ creation dispatched;
- Workers AI inference dispatched;
- Qdrant read or write dispatched;
- Source mutation or Source PR #19 merge;
- R2 mutation or production pointer mutation;
- production traffic or retrieval-mode change;
- permanent-ledger mutation;
- physical deletion;
- credential rotation;
- public Graph Explorer deployment;
- Graph Neural Retrieval;
- production mutation dispatched.

Source PR #19 remains draft, open and unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`. Production retrieval remains `RETRIEVAL_MODE=lexical`. The existing 107-point pilot collection was not changed by M23.6.4.

## Next legal submilestone

M23.6.5 may build the read-only candidate semantic Runtime and shadow endpoint against the existing non-production collection. It must remain internal-only, authenticated, disabled by default and non-authoritative. Deployment or candidate traffic requires a separate explicit authority decision.
