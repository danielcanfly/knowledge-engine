# M23.7-R3.8 placed diagnostic Worker latency repair

## Decision

R3.7 completed a real read-only live acceptance against the reconciled 107-point candidate collection. Quality, target-rank parity, identity, ACL, error-rate and strict-zero gates passed. The only failed gate was direct end-to-end p95 latency at 1739 ms against the unchanged 1200 ms maximum.

R3.8 does not lower that threshold and does not treat a rerun as a repair. It restores the execution boundary already authorised by parent #474: a transient Cloudflare Worker placed by the Qdrant hostname, using an in-process Workers AI binding, one read-only Qdrant query-batch attempt, and a read-only parallel single-query fallback only if that batch endpoint is unavailable.

## Frozen inputs

- R3.7 reconciliation merge: `7793cd22092aca530ca48a3240a3c83ffd3d2894`
- R3.7 receipt file SHA-256: `72c8d9cc6a9262960659c75e87ac9cf6f6e73008633bc255f3c944681abcf4c2`
- R3.7 receipt self-digest: `55ccb6ccdb7f02fcc9ba7302c37021d6cd747af49ec8250c955e924979a3509a`
- R3.7 evidence seal SHA-256: `e5c35247dd10be17dfa526842e3f9dd27d875278d31c5537786e25bf0b17ecdd`
- R3.7 reconciliation SHA-256: `861a0156aba827d4c6eb62ee13e8025cba466fdbe28c60328056c2ec0b88c918`
- candidate collection: `llm_wiki_m23_r3_5_candidate_8eed54902c73`
- candidate points: 107
- probes: 8
- frozen query variants: 24
- accepted metrics: Recall@5 0.875, MRR@10 0.807291666667, nDCG@10 0.851933109598
- maximum top-10 hub frequency: 3

## Execution boundary

The generated local Wrangler config derives only `placement.hostname` from `QDRANT_URL`. The hostname and full service URL are never committed or persisted in receipts. The deployed Worker has:

- Workers AI binding `AI`;
- secrets `QDRANT_URL`, `QDRANT_API_KEY`, and `M23_R3_8_OPERATOR_TOKEN`;
- route `/v1/m23-7-r3-8/observe`;
- timing-safe bearer authentication;
- strict content-length and 65,536-byte request limit;
- disabled invocation logs.

The measured Worker-internal shadow begins immediately before the single Workers AI BGE-M3 binding call and ends after the Qdrant read path is parsed. The read path first uses the official `/points/query/batch` endpoint with the named vector `default`. If that batch endpoint is unavailable, it performs the same read-only search through 24 bounded-concurrency `/points/query?consistency=all` calls, matching the single-query endpoint already used by the accepted R3.7 live path without sending all fallback reads at once. Collection snapshots occur before and after that shadow. Operator-to-Worker round-trip latency is recorded separately and is informational only.

## Data plane

One authenticated request contains the exact 24 frozen query variants. The request carries query text only transiently and binds every text to its SHA-256. It contains no target section IDs or expected relevance data.

The Worker performs:

1. one read-only candidate collection snapshot;
2. one Workers AI binding call containing 24 texts;
3. one Qdrant read-only query batch containing the 24 query vectors, `using: "default"`, and an explicit `section_id`-only payload-field allowlist;
4. only if that batch endpoint is unavailable, 24 read-only single-query calls to `/points/query?consistency=all` with the same named vector, limit, full payload readback, and bounded fallback concurrency, matching the accepted R3.7 live path;
5. one read-only candidate collection snapshot.

The pre/post collection snapshots preserve the exact candidate collection identity. Each ranked result returns only the section ID needed by the accepted target-unaware evaluator, and the operator rejects any ranked section outside the reconciled candidate artifact. The Worker returns only variant IDs, query hashes, ranked section IDs, bounded timings, collection identities and strict-zero authority fields.

The operator reconstructs the accepted target-unaware R3.5 lexical plus dense-consensus ranker locally. It requires exact accepted metrics and target ranks before the latency gate can pass.

## Frozen gates

- Recall@5 >= 0.82
- MRR@10 >= 0.68
- nDCG@10 >= 0.72
- exact accepted metrics and target ranks
- maximum top-10 hub frequency <= 6
- exactly 8 probes and 24 unique query identities
- candidate collection schema identical before and after
- Worker-internal shadow <= 1200 ms
- query error, ACL violation and output-influence rates exactly zero
- Qdrant writes, deletes and reindex operations exactly zero
- all protected mutations exactly zero

The 1200 ms threshold is unchanged. A completed miss is valid fail-closed evidence and retains both blockers.

## Governance and deletion

A passing operator receipt does not itself clear a blocker. It requires an evidence seal and independent reconciliation. Only after a passing reconciliation may the exact transient Worker be deleted. That deletion requires its own absence receipt and independent deletion reconciliation.

Until those steps complete:

- `blocked_pending_retrieval_quality` remains active;
- `blocked_pending_latency` remains active;
- production retrieval remains lexical;
- semantic answer serving remains disabled;
- promotion eligibility remains false;
- parent #474 and M23.7 remain open.

## Authority boundary

R3.8 authorises one isolated diagnostic Worker deployment, Workers AI binding calls, read-only Qdrant collection reads, one read-only query-batch attempt, a read-only parallel single-query fallback only after batch unavailability, one authenticated observation, evidence metadata and later deletion of only that exact Worker.

It does not authorise Qdrant writes, deletes or reindexing; candidate or historical collection mutation; R2, pointer, Source or production mutation; user traffic; semantic answer serving; threshold changes; promotion; blocker clearance before passing reconciliation; parent closure; or M23.7 closure.
