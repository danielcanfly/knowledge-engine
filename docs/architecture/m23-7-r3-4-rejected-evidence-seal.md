# M23.7-R3.4 Rejected Target-Discrimination Evidence Seal

## Accepted operator result

The R3.4 operator ran at implementation head `0b463c9cc4920b6300e1b461a11f828042114e92` using the frozen M23.5 evidence, 107 payload-v2 candidate points and one bounded Workers AI BGE-M3 batch containing 24 synthetic query variants.

The result is a valid quality rejection:

- Recall@5: `0.875` versus `0.82`
- MRR@10: `0.566666666667` versus `0.68`
- nDCG@10: `0.643589039297` versus `0.72`
- Maximum top-10 hub frequency: `3` versus maximum `6`
- Final target ranks: `2, 21, 3, 1, 1, 5, 2, 1`
- Query variants: `24/24` unique
- Report SHA-256: `2464a6cc2aaf708cfad1b8bf3a8f16322a17c78e72af331176a98d8e349be225`
- Raw report file SHA-256: `9dde5d63f7b43ae8078cdd1a20d9c62bafa2e1d710ab03eba97f6796f838c292`
- Seal SHA-256: `3dc6cc5d23f6c4a7767571663a9ccdae9f2c24fdc21553b1676ac844b8ba496c`

The privacy-safe operator receipt was validated before sealing. The repository stores the compact self-digested seal and binds the original receipt by its file SHA-256 and internal report SHA-256.

## What passed

The frozen evidence identity, 107-point count, payload schema v2, 24 unique query identities, Recall@5 gate, all three improvements over R3.3, hub-frequency gate and zero protected mutations passed. Qdrant reads and writes were both zero.

## What failed

MRR@10 and nDCG@10 remained below their frozen thresholds.

The multi-query RRF ablation produced the best ranking-quality metrics:

- Recall@5: `0.75`
- MRR@10: `0.645833333333`
- nDCG@10: `0.702258336781`

The final specificity and centrality rerank raised Recall@5 to `0.875` but reduced MRR@10 and nDCG@10. The remaining primary defect is rank-quality calibration, compounded by an overaggressive rerank and one hard semantic mismatch case, `m23q-02`, at final rank `21`.

## Governance disposition

R3.4 is complete with disposition `completed_rejected`.

This evidence does not authorize candidate Qdrant reingestion, R3 live acceptance, semantic serving, threshold changes, promotion, or blocker clearance. Production retrieval remains lexical and `blocked_pending_retrieval_quality` remains active.

The next legal action is a separately governed R3.5 rank-quality calibration repair. Issue `#497` may close only after this seal is merged and independently reconciled. Parent issue `#474` remains open.
