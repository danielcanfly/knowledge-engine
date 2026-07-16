# M23.7-R3.5 Rank-Quality Calibration Repair

## Entry

R3.4 completed with disposition `completed_rejected`.

- Recall@5: `0.875`
- MRR@10: `0.566666666667`
- nDCG@10: `0.643589039297`
- Multi-query RRF MRR@10: `0.645833333333`
- Multi-query RRF nDCG@10: `0.702258336781`
- Maximum top-10 hub frequency: `3`
- Hard case: `m23q-02`, final rank `21`

The remaining defect is rank-quality calibration. R3.4's multiplicative specificity and centrality adjustment improves Recall but degrades early-rank quality.

## Repair

R3.5 reuses the exact R3.4 24 query variants and one bounded Workers AI BGE-M3 batch.

The final ranker combines:

1. dense reciprocal-rank fusion across the three query variants;
2. BM25 ranking over query-visible lexical terms and in-memory document semantic surfaces;
3. dense top-10 variant consensus.

The fusion weights are fixed before credential-bearing evaluation. Terminology queries receive a higher lexical weight because definition retrieval benefits from exact semantic vocabulary. No score function accepts a target section ID, expected relevance list, probe ID or case label.

The R3.4 multiplicative specificity and centrality rerank remains available only as a report ablation.

## Privacy

Raw query text and raw document text exist only in the in-memory operator candidate. The persisted candidate artifact removes both and retains only digests, identities and bindings.

The report persists query digests, target ranks for offline quality evaluation, top-10 section identities, ablation metrics, safety state and authority state. It does not persist credentials, service URLs, raw answers, raw queries or document text.

## Frozen gates

- Recall@5 >= `0.82`
- MRR@10 >= `0.68`
- nDCG@10 >= `0.72`
- MRR and nDCG must improve over the sealed R3.4 final result
- maximum top-10 hub frequency <= `6`
- 24/24 query identities unique
- target-unaware score path
- Qdrant reads and writes equal zero

## Authority

R3.5 does not authorize Qdrant reads, writes, deletes or reindexing. It does not authorize candidate reingestion, live acceptance, R2 or pointer mutation, Source mutation, deployment, serving, threshold changes, promotion, production mutation or blocker clearance.

Production retrieval remains lexical. `blocked_pending_retrieval_quality` remains active.

A passing offline result authorizes only a separately governed candidate reingestion proposal. Credential-bearing evidence, evidence sealing and independent reconciliation remain mandatory before issue closure.
