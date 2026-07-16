# M23.7-R3.3 Rejected Offline Evidence Seal

## Accepted operator result

The reconciled R3.3 operator ran at engine head `18163acc42f4a378957740f5acf82533fc282a0b` using the frozen M23.5 evidence, 107 payload-v2 candidate points and one bounded Workers AI BGE-M3 query batch.

The result is a valid quality rejection:

- Recall@5: `0.375` versus `0.82`
- MRR@10: `0.23125` versus `0.68`
- nDCG@10: `0.293833892245` versus `0.72`
- Target ranks: `4, 79, 14, 17, 2, 1, 15, 10`
- Query text identities: `8/8` unique
- Maximum top-10 hub frequency: `6/8`
- Report SHA-256: `a71c36456ff0fb7a00d084c5f89364d9d37c42e6f252af925dc92856733c13ff`
- Raw file SHA-256: `c7650e9ba8708d01b48d3d0b80d14e55598d32659e1827ad4b782f510377a732`
- Seal SHA-256: `09ea9d1bcfb7cc01a449c5ab52a3afb335ccbba5e9a3388c6b38b1d2d93ae3ed`

## What passed

The frozen evidence identity, semantic artifact identity, 107-point count, payload schema v2, unique repaired query identities and zero protected mutations all passed. Qdrant reads and writes were both zero.

## What failed

All three frozen retrieval-quality thresholds failed. R3.2 therefore repaired the original query collision and R3.3 proved the repaired payload/compiler path can execute, but it did not establish retrieval quality.

The remaining primary defect is weak target-specific semantic discrimination. Residual corpus hubness and generic lead-section bias compound it. Six of eight probes miss rank five, while generic `chunk-000` and neighbouring lead sections repeatedly occupy the top results.

## Governance disposition

R3.3 is complete with disposition `completed_rejected`.

This evidence does not authorize candidate Qdrant reingestion, R3 live acceptance, semantic serving, threshold changes, promotion, or blocker clearance. Production retrieval remains lexical and `blocked_pending_retrieval_quality` remains active.

The next legal action is a separately governed R3.4 repair iteration. Issue `#487` may close only after this seal is merged and independently reconciled. Parent issue `#474` remains open.
