# M20.7 Phase C semantic and hybrid retrieval acceptance

## Status

Implementation contract for issue #308. M20.7 closes Phase C by validating the evidence produced by M20.1 through M20.6. It adds no new retrieval strategy and grants no production authority.

## Acceptance boundary

The validator consumes one bounded, machine-readable evidence payload and rejects incomplete or drifting evidence. Acceptance requires exact Engine, Source, and Foundation commit identities, exactly six milestone records, successful workflow evidence, the full authority guarantee set, and explicit false values for every protected mutation.

## Required milestone chain

The evidence must contain exactly:

1. M20.1 embedding provider contract and bilingual benchmark
2. M20.2 immutable semantic artifacts
3. M20.3 Runtime semantic verification and read-only mapping
4. M20.4 retrieval-mode isolation
5. M20.5 deterministic hybrid rank fusion
6. M20.6 deterministic lexical enrichment

Every milestone record must prove:

- canonical issue state is `completed`;
- implementation PR merged;
- reconciliation PR merged;
- implementation merge SHA is valid;
- reconciliation merge SHA is valid.

Missing, extra, open, unmerged, malformed, or duplicate evidence fails closed.

## Required guarantees

M20.7 requires all of the following to be explicitly true:

- lexical answer, citation, and evaluation authority remains preserved;
- vector mode remains diagnostic only;
- hybrid output remains non-production only;
- lexical enrichment remains non-production only;
- ACL filtering occurs before serialization;
- all semantic and enrichment data remains release-bound;
- ordering and tie-break behaviour remains deterministic;
- all outputs remain bounded;
- no provider or network dependency was introduced;
- no ANN or vector database was introduced;
- no public vector endpoint was introduced;
- no automatic Source parsing was introduced;
- no cross-release merge was introduced.

Unknown guarantee names are rejected so future behaviour cannot be silently smuggled into the Phase C closure report.

## Workflow evidence

At least one successful exact-head record is required for each canonical workflow family:

- M20.1 Embedding Contract and Bilingual Benchmark
- M20.2 Immutable Semantic Artifacts
- M20.3 Runtime Semantic Verification
- M20.4 Retrieval Modes
- M20.5 Hybrid Fusion
- M20.6 Lexical Enrichment
- repository CI
- M17 Architecture Canon Acceptance
- M18 Graph v2 Acceptance

Each record includes a successful conclusion and exact workflow head SHA. Duplicate or failed workflow evidence is rejected.

## Protected state

Every protected mutation must be explicitly false:

- production mutation dispatch
- production pointer update
- retained R2 state creation
- credential modification
- permanent ledger write
- rollback dispatch

The final report always returns `production_authority: false`.

## Deterministic report

Successful validation emits `knowledge-engine-phase-c-acceptance/v1` with:

- exact Engine, Source, and Foundation SHAs;
- milestone and workflow counts;
- ordered verified guarantee names;
- `production_authority: false`;
- `accepted: true`.

The same evidence produces byte-equivalent Python dictionary content and ordering.

## Acceptance tests

M20.7 tests cover:

- complete deterministic acceptance;
- missing and extra milestone rejection;
- open issue and unmerged PR rejection;
- missing, failed, and duplicate workflow rejection;
- missing, false, and unknown guarantee rejection;
- every protected mutation independently failing closed;
- production authority rejection;
- schema and identity drift rejection;
- M20.1 through M20.6 and Runtime regressions.

## Exclusions

M20.7 does not add retrieval modes, learned weighting, reranking, provider calls, Runtime or FastAPI routes, ANN, vector databases, answer generation, Source mutation, candidate or production publication, production pointers, retained R2 objects, credentials, permanent ledgers, rollback, M21 work, cross-release merge, or Graph Neural Retrieval.

Production mutation dispatched: false.

## Closure reconciliation

### Identity chain

- M20.6 reconciliation / implementation base: `3410204f1299c6768649079c8016c0d7fea014be`
- final implementation head: `7b959cf8637f7adf3c53099084cd13a5f95f6d1d`
- implementation merge: `7249bc8d812838dc20675b0eaa6ced15adc3e8c2`
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

### Exact implementation scope

Implementation PR #309 changed exactly four files:

1. `.github/workflows/m20-7-phase-c-acceptance.yml`
2. `docs/architecture/m20/m20-7-phase-c-acceptance.md`
3. `src/knowledge_engine/m20_phase_c_acceptance.py`
4. `tests/test_m20_7_phase_c_acceptance.py`

No prior M20 implementation, Runtime, FastAPI, dependency, lockfile, compiler, release manifest, Source, production pointer, credential, permanent ledger, or rollback file changed.

### Invalidated head

`4004b837b8a979de57dbb25f61de8a19b30cf5cc` was invalidated after the Phase C workflow referenced a non-existent Runtime regression test file. M20.1 through M20.7 contract tests had passed, but no result from that head is acceptance evidence.

### Final-head acceptance evidence

All workflows associated with implementation head `7b959cf8637f7adf3c53099084cd13a5f95f6d1d` completed successfully:

- M20.7 Phase C Acceptance #2
- CI #649
- M17 Architecture Canon Acceptance #55
- M18 Graph v2 acceptance #85
- R2 Release Integration #449

The M20.7 workflow passed exact-head checkout, repository Ruff, M20.1 through M20.7 tests, Runtime regressions, authority-boundary assertions, dependency scanning, and Python compilation.

Implementation PR #309 had no conversation comments, submitted reviews, or unresolved review threads at merge time.

### Phase C delivered boundary

- M20.1 through M20.6 are represented as one exact, fail-closed milestone chain;
- lexical answer, citation, and evaluation authority remains intact;
- vector mode remains diagnostic and hybrid/enrichment evidence remains non-production;
- ACL, release identity, deterministic ordering, stable fallback, and output bounds are required evidence;
- provider/network dependencies, ANN, vector databases, public vector endpoints, automatic Source parsing, and cross-release merge remain excluded;
- all protected mutation flags remain false.

Production mutation dispatched: false.
