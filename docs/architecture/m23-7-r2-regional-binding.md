# M23.7 Repair R2.1 Regional Workers AI Binding Path

Issue: #465. Parent R2 issue: #463. Parent repair decision: #455.

## Trigger

The accepted Mac mini live receipt
`17ffeee8b8bc49d0d26126da617416a8d89870dc59b98f6085d2b0edba631bca`
proved that the two-call direct batch path is correct and substantially faster, but still
misses the locked 1200 ms shadow budget:

- sequential session-reuse shadow p95: 2048 ms;
- direct batch provider: 412 ms;
- direct batch Qdrant: 824 ms;
- direct batch shadow: 1235 ms;
- budget miss: 35 ms;
- ranked-result equivalence: true;
- error, ACL violation and output-influence rates: zero.

The receipt is valid `rejected_latency_path` evidence. It does not authorise rounding,
budget inflation, selective sample removal or repeated same-origin attempts until one
happens to pass.

## Regional candidate

R2.1 compares the accepted direct two-call path with an isolated diagnostic Cloudflare
Worker that performs:

1. one in-process Workers AI binding call for all eight R1 queries;
2. one Qdrant `/points/query/batch` call for all eight vectors.

The Worker is explicitly placed near the configured Qdrant hostname. The placement
hostname is generated from `QDRANT_URL` at operator time into ignored
`wrangler.local.jsonc`; the hostname and complete service URL are never committed or
persisted in the evidence receipt.

The Worker uses `env.AI.run("@cf/baai/bge-m3", {text: queries})`. Calling the Cloudflare
REST API from inside the Worker is forbidden because it would reintroduce authentication
and network overhead that the binding is intended to remove.

## Shadow boundary

The canonical 1200 ms budget applies to Worker-internal provider plus Qdrant execution.
This matches the existing shadow boundary, which measured the semantic provider and
vector database path rather than a future end-user request lifecycle.

The operator-to-Worker round trip is recorded separately as informational evidence. It
cannot replace, inflate or redefine the canonical shadow budget.

## Request and privacy contract

The auth-protected endpoint accepts exactly eight bounded R1 synthetic queries with:

- probe ID;
- query digest;
- target section ID;
- transient query text.

The Worker recomputes every R1 query digest before any external call. Query text remains
in memory only and is never returned or logged. Durable evidence contains only query
digests, target IDs, ranked section IDs, collection identities and latency values.

The Worker returns fixed error codes rather than arbitrary exception text. It uses a
timing-safe comparison for the operator bearer secret and requires a bounded request
body. Responses use `Cache-Control: no-store`, and generated Wrangler config disables invocation logs.

## Qdrant boundary

The Worker performs fail-closed collection checks before and after the batch query:

- collection `llm_wiki_m23_pilot_bge_m3_1024`;
- status green;
- exactly 107 points;
- named vector `default`;
- 1024 dimensions;
- Cosine distance;
- no sparse vector configuration;
- read-only authority.

Every returned point must preserve the accepted release, manifest, audience, vector and
authority payload identities. The Worker exposes no write or delete operation.

## Deployment boundary

Only an isolated non-production diagnostic Worker is authorised. The generated Wrangler
config contains an AI binding and explicit `placement.hostname`, but no credentials.
These values are supplied only as Worker secrets:

- `QDRANT_URL`;
- `QDRANT_API_KEY`;
- `M23_R2_OPERATOR_TOKEN`.

The diagnostic Worker must be deleted after the live receipt is accepted and the
independent reconciliation merges. Its deployment does not authorise any production
Worker, Queue, live traffic or answer-serving change.

## Exit semantics

R2.1 passes only when a real receipt proves:

- eight accepted R1 probes;
- direct and placed-Worker rankings exactly equivalent;
- one Workers AI binding call and one Qdrant batch query;
- unchanged Qdrant collection identity;
- Worker-internal shadow at or below 1200 ms;
- zero error, ACL violation and output-influence rates;
- unchanged canonical budget with no inflation;
- independent reconciliation merged.

A passing receipt clears only `blocked_pending_latency`.
`blocked_pending_retrieval_quality` remains for R3.

If the placed path remains above 1200 ms, the receipt is still retained, but #465 and
#463 remain open and the budget remains unchanged.

## Authority

Production retrieval remains lexical. Candidate mode, semantic answer serving and
promotion eligibility remain disabled. Source PR #19 remains draft, open and unmerged at
`deb3ad1e631c2149183d10561fbceb0a1848a989`.

No production pointer, R2 object, Source, Qdrant write/delete, permanent ledger, public
Graph Explorer, credential rotation, production deployment, promotion or Graph Neural
Retrieval mutation is authorised.

Production mutation dispatched: false.
