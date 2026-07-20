# M24.8 Query And Answer Acceptance

P5 freezes and executes the M24 query and answer acceptance suite against the
canonical candidate release created in P2 and connected to product surfaces in
P3.

## Release Under Test

- Release ID: `20260720T160000Z-46137c97263e`
- Manifest SHA-256:
  `ef5ee828069731e3e7106e1b12fb82e3a578c377930568410bc78421d1600877`
- Source SHA: `acf78596ace8a7366688ccef72b507204d09d9f9`

The P5 harness uses lexical retrieval plus one-hop relation-aware expansion on
the canonical candidate release. Semantic promotion, semantic answer serving,
and hybrid retrieval remain disabled.

## Frozen Query Classes

The suite covers the required P5 classes:

- direct fact;
- terminology;
- relationship;
- comparison;
- cross-language;
- provenance;
- ACL-negative;
- no-answer;
- stale-source;
- prompt injection;
- contradiction.

Each case records expected concepts, forbidden concepts where applicable, and a
safe fallback. Negative and adversarial cases are not treated as ordinary
answers: no-answer returns a not-found fallback, prompt injection is treated as
query text, stale-source cases require a freshness notice, and contradiction
cases require review-oriented fallback.

## Acceptance Metrics

The committed evidence records:

- Recall@5;
- MRR@10;
- nDCG@10;
- groundedness;
- citation coverage;
- citation mismatch rate;
- no-answer false-positive rate;
- ACL leakage;
- bounded offline p50/p95 latency observations;
- cost/query;
- deterministic replay.

P5 freezes lexical-candidate thresholds for this canonical release:

- Recall@5 must be `1.0`;
- MRR@10 must be at least `0.8`;
- nDCG@10 must be at least `0.85`;
- groundedness and citation coverage must be `1.0`;
- citation mismatch, no-answer false positive, ACL leakage, and query cost must
  be zero.

## Evidence

The digest-bound evidence is:

`pilot/m24/query-answer-acceptance/m24-p5-query-answer-acceptance.json`

The report records 11/11 passing cases, deterministic replay, and no failure
reasons.

## Boundary

P5 is offline/internal acceptance evidence. It does not deploy the internal app;
that remains P6.

P5 does not authorize:

- production semantic or hybrid retrieval;
- production answer serving;
- deployment or traffic mutation;
- Source, R2, Qdrant, credential, production pointer, or permanent-ledger
  mutation.
