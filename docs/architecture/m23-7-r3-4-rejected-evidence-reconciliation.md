# M23.7-R3.4 Rejected Evidence Reconciliation

## Bound evidence seal

- Evidence-seal issue: `#499`
- R3.4 implementation issue: `#497`
- Parent R3 issue: `#474`
- Evidence-seal PR: `#500`
- Accepted head: `f6ddd9b95f52ed600899c367717662c8f65e8377`
- Evidence-seal merge: `e212b97e6ab1237de81c042905b20c61afc8bcb4`
- Seal SHA-256: `3dc6cc5d23f6c4a7767571663a9ccdae9f2c24fdc21553b1676ac844b8ba496c`
- Operator report file SHA-256: `9dde5d63f7b43ae8078cdd1a20d9c62bafa2e1d710ab03eba97f6796f838c292`
- Operator report SHA-256: `2464a6cc2aaf708cfad1b8bf3a8f16322a17c78e72af331176a98d8e349be225`
- Reconciliation record SHA-256: `f4b243b9c90cb7eb361b398414db25d1e9627b0d01d945306c2eb1a9c4853689`

## Exact-head evidence

All workflows triggered for the accepted evidence-seal head succeeded:

- R3.4 Rejected Evidence Seal: `29478935405`
- CI: `29478935303`
- M17 Architecture Canon Acceptance: `29478935279`
- M18 Graph v2 acceptance: `29478935269`

R2 Release Integration was not triggered by the evidence/documentation-only path set.

## Reconciled result

R3.4 completed with disposition `completed_rejected`.

- Recall@5: `0.875` versus `0.82`
- MRR@10: `0.566666666667` versus `0.68`
- nDCG@10: `0.643589039297` versus `0.72`
- Maximum top-10 hub frequency: `3`
- Query variants: `24/24` unique
- Final target ranks: `2, 21, 3, 1, 1, 5, 2, 1`

R3.4 materially improved target discrimination, passed Recall@5 and reduced hubness. Ranking-quality gates remain blocked. Multi-query RRF produced the best MRR and nDCG, while the final specificity/centrality rerank traded rank quality for Recall. One hard semantic mismatch, `m23q-02`, remains at final rank `21`.

## Authority state

No candidate reingestion, R3 live acceptance, Qdrant I/O, R2 or pointer mutation, Source mutation, serving, threshold change, promotion or production mutation is authorized.

Production retrieval remains lexical. `blocked_pending_retrieval_quality` remains active. Parent issue `#474` stays open.

## Closure and next action

After this reconciliation merges, issues `#499` and `#497` may close as completed, with R3.4 explicitly recorded as rejected rather than passed. The next legal action is a separately governed R3.5 rank-quality calibration repair.
