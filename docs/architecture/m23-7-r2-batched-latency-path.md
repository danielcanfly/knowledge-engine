# M23.7 Repair R2 Batched Latency Path

Issue: #463. Parent decision: #455. R1 prerequisite: #460.

## Objective

R2 qualifies a lower-request-count, non-production, read-only path for the eight accepted
R1 synthetic semantic probes. The current session-reuse implementation still performs
one Cloudflare embedding request and one Qdrant query request per probe. R2 compares that
16-call baseline with a two-call batch path:

1. one Cloudflare BGE-M3 request containing all eight synthetic query texts;
2. one Qdrant `/points/query/batch` request containing all eight vectors.

The model, collection, named vector, top-k, ACL rules and canonical 1200 ms shadow p95
budget remain unchanged.

## Entry evidence

- accepted M23.7.8 repair handoff:
  `7fb6fadf91f1a09110bf1d0e653652f52a298ebc0119aee3743180314e16f0b9`;
- accepted R1 manifest:
  `ebff335d572461f4438ed06c4cc35288b0d0def8bbfc2b51e80bb262db12c576`;
- accepted R1 report:
  `7ee8ddf6bf955cf0c1a10dd5442aa60d0b4b791bc2f3f4deba386213adf815e1`;
- accepted post-session-reuse live receipt:
  `493515fce1bdeb1c7155ea69c198f658c0cf05f83314a905bf2d945152dc4b3e`;
- previous provider p95: 1328 ms;
- previous Qdrant p95: 576 ms;
- previous shadow p95: 1731 ms;
- canonical shadow p95 budget: 1200 ms.

## Path contract

### Sequential session-reuse baseline

- eight provider requests;
- eight Qdrant query requests;
- one shared provider client and one shared Qdrant client;
- 16 data-plane requests total.

### Batch session-reuse candidate

- one provider request containing eight query texts;
- one Qdrant `/points/query/batch` request containing eight vector searches;
- one shared provider client and one shared Qdrant client;
- two data-plane requests total.

Both paths execute the same R1 compiled probes from the same origin during a single
comparison. Ranked section IDs must match exactly case by case. A ranking difference is a
hard failure, not an acceptable latency trade-off.

## Component receipts

The redacted report records:

- sequential provider, Qdrant and end-to-end p95 values;
- batch provider, Qdrant and end-to-end values;
- fixed request counts;
- same-origin label;
- ranked-result equivalence;
- request-count reduction;
- shadow p95 improvement;
- unchanged canonical budget result.

The origin label is a bounded operator label, not a URL, IP address, credential or
provider identifier. A later regional or Workers AI binding comparison may use another
separately governed origin label if this direct batch path remains above budget.

## Privacy

Compiled query text exists only in process memory. Durable evidence contains query
digests, target section IDs, ranked section IDs and latency values. It never contains raw
queries, answers, credentials, service URLs or arbitrary exception text.

## Exit semantics

The deterministic fixture proves implementation shape only. It does not clear the live
latency blocker.

R2 closes only after a real operator receipt proves all of the following:

- eight accepted R1 probes executed;
- sequential and batch rankings are identical;
- the batch path used exactly two data-plane requests;
- error, ACL violation and output-influence rates are zero;
- batch shadow p95 is at or below 1200 ms;
- the budget was not changed or inflated;
- independent reconciliation merged.

A passing R2 receipt clears only `blocked_pending_latency`. The
`blocked_pending_retrieval_quality` blocker remains for R3, where the aligned R1 probes
are evaluated against real live retrieval results.

If the direct batch path remains above 1200 ms, R2 remains open and the receipt becomes
the evidence basis for a separately governed regional or Workers AI binding comparison.
The canonical budget may not be raised.

## Authority boundary

Production retrieval remains lexical. Candidate mode and promotion eligibility remain
disabled. Source PR #19 remains draft, open and unmerged at
`deb3ad1e631c2149183d10561fbceb0a1848a989`.

No user query, live traffic, answer serving, deployment, production pointer, R2 storage
mutation, Source mutation, Source PR merge, Qdrant write/delete, Worker/Queue deployment,
public Graph Explorer, permanent ledger mutation, credential rotation, promotion or
Graph Neural Retrieval is authorised.

Production mutation dispatched: false.
