# M23.7-R3.3a Reconciliation

## Trigger and root cause

The first R3.3 frozen-evidence operator run stopped before any network call with `M23.7-R3.3-109 semantic vector bytes drifted`.

The evidence identity was correct. The defect was an obsolete requirement that two independent Cloudflare BGE-M3 generations be byte-identical. PR #391 had already removed that assumption from the accepted M23.6 real-evidence ingestion path.

## Accepted implementation

- Issue: `#489`
- Parent R3.3 issue: `#487`
- Parent R3 issue: `#474`
- Implementation PR: `#492`
- Accepted head: `239b7ed7f42e039b6b84bca2f509e441467e8d8c`
- Implementation merge: `23578e610012f3e2db10814368e0b72a1675a424`
- Reconciliation record SHA-256: `528a224ea4ba9f4f902ac6690f9092e8792ade993069b55a3990738f2019a02d`

## Reconciled vector authority

`pilot-document-vectors.f32` is the sole ranking and candidate-point source. The semantic vector artifact is validated independently through its own metadata digest, model contract, vector properties, section set, row uniqueness and section-level source binding. The accepted M20 benchmark-results suite digest is used when present.

The operator now routes through the real-evidence compatibility entrypoint. Regression evidence intentionally supplies different pilot and semantic vector bytes and verifies that pilot vectors remain the ranking corpus.

## Exact-head acceptance

All workflows below succeeded at implementation head `239b7ed7f42e039b6b84bca2f509e441467e8d8c`:

- R3.3a Real Evidence Compatibility: `29474685562`
- R3.3 Offline Rebuild Evaluation: `29474685556`
- CI: `29474685567`
- M17 Architecture Canon Acceptance: `29474685570`
- M18 Graph v2 acceptance: `29474685566`
- R2 Release Integration: `29474685575`

## Authority state

The failed operator attempt made zero Workers AI calls and zero Qdrant calls. The hotfix dispatched no Qdrant read/write/delete/reindex, R2 or pointer mutation, Source mutation, deployment, semantic serving, threshold change, promotion or production mutation.

Production retrieval remains lexical. `blocked_pending_retrieval_quality` remains active. Issues `#487` and `#474` remain open.

## Next action

Rerun R3.3 from the reconciled hotfix main commit. The resulting privacy-safe report must still be imported, sealed with exact-head CI and independently reconciled before closing `#487`.
