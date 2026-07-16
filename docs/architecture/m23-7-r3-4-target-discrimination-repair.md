# M23.7-R3.4 Target-Specific Semantic Discrimination Repair

## Entry

R3.3 completed with disposition `completed_rejected` after a valid 107-point payload-v2 rebuild and one bounded Workers AI BGE-M3 query batch.

- Recall@5: `0.375` versus `0.82`
- MRR@10: `0.23125` versus `0.68`
- nDCG@10: `0.293833892245` versus `0.72`
- Target ranks: `4, 79, 14, 17, 2, 1, 15, 10`
- Query identities: `8/8` unique
- Maximum top-10 hub frequency: `6`

The original identifier-humanisation query collision is repaired. Remaining failure is weak target-specific semantic discrimination, compounded by corpus hubness and generic lead-section bias.

## Repair design

### Corpus-aware semantic signatures

For each of the same eight deterministic targets, R3.4 derives a semantic signature from the target document title, concept and text. Terms are scored using document frequency, term frequency and a title/concept bonus.

The compiler removes structural identifiers, Markdown, URLs, common boilerplate and generic words. A target must expose at least five distinctive terms or compilation fails closed.

### Multi-query compilation

Each probe produces three bounded query variants:

1. title plus distinctive concepts;
2. relation-focused wording around the three strongest terms;
3. query-class wording around the target-specific signature.

All 24 query texts must have unique SHA-256 identities. Raw section IDs may not appear in a query. Raw query text is used only in memory for the bounded embedding call and is removed from persisted candidate artifacts and reports.

### Deterministic fusion and de-hubbing

The 24 queries are embedded in one Workers AI BGE-M3 batch. Each probe's three rankings are fused with reciprocal-rank fusion using fixed `k=60` and depth `50`.

The fused score is adjusted only by target-independent corpus properties:

- textual specificity derived from document frequency;
- vector centrality derived from the ten nearest corpus neighbours;
- a small centrality-weighted penalty for generic `chunk-000` lead sections.

No target-aware score adjustment, label-dependent tuning or threshold change is permitted.

## Ablations

The privacy-safe operator report records:

- single discriminative query metrics;
- multi-query RRF metrics;
- specificity and centrality reranked metrics.

The final repaired pipeline must exceed the sealed R3.3 baseline on all three metrics, meet the original thresholds and keep maximum top-10 hub frequency at or below six.

## Authority

R3.4 is offline and no-write. It authorizes one bounded Workers AI batch for 24 synthetic query variants and local ranking over frozen vectors.

It authorizes no Qdrant I/O, candidate reingestion, R3 live acceptance, R2 or pointer mutation, Source mutation, deployment, serving, promotion, threshold change, production mutation or blocker clearance.

Production retrieval remains lexical. `blocked_pending_retrieval_quality` remains active.

## Exit

A pass authorizes only a separately governed candidate-reingestion proposal. A rejection must still be sealed and reconciled. R3 live acceptance remains a later independent gate.
