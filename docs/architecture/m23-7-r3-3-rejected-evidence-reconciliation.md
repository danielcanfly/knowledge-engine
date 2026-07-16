# M23.7-R3.3 Rejected Evidence Reconciliation

## Bound evidence seal

- Issue: `#494`
- Parent R3.3 issue: `#487`
- Parent R3 issue: `#474`
- Evidence-seal PR: `#495`
- Accepted head: `e80d4eea204db99a8f27f322e88430b5ea589e20`
- Evidence-seal merge: `fb87b009fff0a3ad86d51d95fe14d6b6e3c910a5`
- Seal SHA-256: `09ea9d1bcfb7cc01a449c5ab52a3afb335ccbba5e9a3388c6b38b1d2d93ae3ed`
- Operator report file SHA-256: `c7650e9ba8708d01b48d3d0b80d14e55598d32659e1827ad4b782f510377a732`
- Operator report SHA-256: `a71c36456ff0fb7a00d084c5f89364d9d37c42e6f252af925dc92856733c13ff`
- Reconciliation record SHA-256: `aa9fea2edc09ef53addf85fb0e686c3a7a1286f8c22d64ff013af36b5583b331`

## Exact-head evidence

All workflows triggered for the accepted evidence-seal head succeeded:

- R3.3 Rejected Evidence Seal: `29475963859`
- CI: `29475963841`
- M17 Architecture Canon Acceptance: `29475963907`
- M18 Graph v2 acceptance: `29475963882`

R2 Release Integration was not triggered by the evidence/documentation-only path set.

## Reconciled result

R3.3 completed with disposition `completed_rejected`.

- Recall@5: `0.375` versus `0.82`
- MRR@10: `0.23125` versus `0.68`
- nDCG@10: `0.293833892245` versus `0.72`
- Target ranks: `4, 79, 14, 17, 2, 1, 15, 10`
- Query identities: `8/8` unique
- Maximum top-10 hub frequency: `6`

The original query-collision defect is repaired and payload-v2 rebuild integrity is accepted. Retrieval quality remains blocked by weak target-specific semantic discrimination, residual corpus hubness and generic section-lead bias.

## Authority state

No candidate reingestion, R3 live acceptance, Qdrant I/O, R2 or pointer mutation, Source mutation, serving, threshold change, promotion or production mutation is authorized.

Production retrieval remains lexical. `blocked_pending_retrieval_quality` remains active. Parent issue `#474` stays open.

## Closure and next action

After this reconciliation merges, issues `#494` and `#487` may close as completed, with R3.3 explicitly recorded as rejected rather than passed. The next legal action is a separately governed R3.4 repair iteration.
