# M23.7-R3.7 Fail-Closed Live Acceptance Evidence Seal

## Scope

This record seals the original privacy-safe R3.7 live acceptance receipt attached to issue #516. The operator was pinned to implementation merge `068d2968a6d60b44328b96908cfc4ce29f919a2f` and contract SHA-256 `11faa597fe15e39f2589963b30e00e3b1580d6f7bb186ffe9ef180139d427d8d`.

The original receipt is bound by two independent identities:

- raw file SHA-256: `72c8d9cc6a9262960659c75e87ac9cf6f6e73008633bc255f3c944681abcf4c2`;
- canonical receipt self-digest: `55ccb6ccdb7f02fcc9ba7302c37021d6cd747af49ec8250c955e924979a3509a`.

The compact seal is self-digested as `e5c35247dd10be17dfa526842e3f9dd27d875278d31c5537786e25bf0b17ecdd`. It does not reproduce raw queries, document text, credentials, service URLs or hostnames.

## Verified completed result

The credential-bearing operator completed all 24 individual query variants against candidate collection `llm_wiki_m23_r3_5_candidate_8eed54902c73` and emitted a valid fail-closed result.

Verified identities and safety facts:

- 107 candidate points before and after the run;
- exact collection schema before and after;
- exact ID-set and aggregate vector fingerprint before and after;
- 24 queries and 24 unique query identities;
- 58 bounded network calls;
- zero query errors and zero ACL violations;
- no Qdrant write, delete or reindex;
- no historical-pilot, production-collection, R2, pointer, Source, production, serving or promotion mutation;
- production retrieval remains lexical.

## Quality result

Live quality exactly reproduced the accepted R3.5 offline result:

- Recall@5: `0.875`;
- MRR@10: `0.807291666667`;
- nDCG@10: `0.851933109598`;
- maximum top-10 hub frequency: `3`;
- target ranks: `1, 8, 3, 1, 1, 1, 1, 1` for the eight frozen cases.

All quality, identity, parity, strict-zero and privacy gates passed.

## Fail-closed latency disposition

The sole failed gate was the unchanged canonical live latency budget:

- provider p50/p95: `604 / 1432 ms`;
- Qdrant p50/p95: `339 / 707 ms`;
- end-to-end p50/p95: `1012 / 1739 ms`;
- canonical maximum live p95: `1200 ms`.

The result is therefore `completed_fail_closed_live_acceptance`, not a pass. Thresholds were not changed and no rerun is authorized by this seal.

## Authority and next gate

This evidence seal does not clear `blocked_pending_retrieval_quality` or `blocked_pending_latency`. It does not authorize serving, production traffic, semantic promotion, candidate promotion, R2 or pointer mutation, or M23.7 closure.

Independent reconciliation is required next. The reconciliation must preserve the fail-closed disposition and may close issues #514 and #516 only as completed evidence work, not as successful live acceptance. Parent issue #474 remains open.
