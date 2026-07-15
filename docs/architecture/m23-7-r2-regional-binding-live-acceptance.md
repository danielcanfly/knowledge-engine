# M23.7 Repair R2.1 Live Regional Binding Acceptance

Issue: #465. Parent R2 issue: #463.

## Accepted operator evidence

The governed placed-Worker observation completed successfully after the sparse-vector metadata hotfix merged at main `7354a8d6ac8f550478e27f3661e4a79f01843af6`.

The operator generated the redacted receipt locally and independently recomputed its canonical SHA-256. The stored and recalculated values matched:

- receipt SHA-256: `aa56655d19cb617177bd8e4708c02e1cd6ce02189fcfee32a5b397ef0eba67db`;
- status: `pass_regional_path_qualified`;
- Cloudflare placement: `local-NRT`;
- canonical Worker-internal shadow budget: 1200 ms;
- canonical budget changed: false;
- budget inflation used: false.

The repository stores a digest-bound acceptance record at `pilot/m23/m23-7-r2-regional-binding-live-acceptance.json`. The complete redacted operator receipt remains on the operator host and is bound here by its verified digest rather than by copied or reconstructed case content.

## Measured paths

Direct Mac mini baseline:

- provider: 1603 ms;
- Qdrant: 2672 ms;
- Worker-equivalent shadow boundary: 4275 ms.

Placed Worker candidate:

- Workers AI binding: 227 ms;
- Qdrant batch: 554 ms;
- Worker-internal shadow: 781 ms;
- operator round trip: 2471 ms, informational only.

The placed path improved the governed shadow boundary by 3494 ms and passed the unchanged 1200 ms requirement with 419 ms of margin.

## Semantic and safety acceptance

The live observation proved:

- identical R1 probe identity;
- exact ranked-result equivalence between direct and placed paths;
- equivalent read-only Qdrant collection identity;
- connection reuse preserved;
- error rate 0;
- ACL violation rate 0;
- output-influence rate 0;
- no candidate answer serving;
- no Qdrant write or delete;
- no production, Source, pointer, R2 object or permanent-ledger mutation.

The initial secret update briefly returned 401 before propagation. The bounded retry then authenticated and produced the accepted receipt. This did not alter the measurement, budget or evidence semantics.

## Exit state

R2.1 is accepted as complete. `blocked_pending_latency` is cleared by new live evidence.

The only remaining repair blocker is `blocked_pending_retrieval_quality`, which belongs to R3 bounded live re-observation. R3 is now legally ready after independent reconciliation.

This acceptance does not grant promotion eligibility. Production retrieval remains lexical, candidate mode remains disabled, and a new explicit promotion decision remains required after R3.

Source PR #19 remains draft, open and unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`.

## Diagnostic Worker lifecycle

The isolated diagnostic Worker `knowledge-engine-m23-7-r2-binding` must remain available until the independent reconciliation merges. It must then be deleted and the deletion recorded before #465 and #463 are closed.

Production mutation dispatched: false.
