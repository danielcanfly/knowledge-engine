# M20.4 retrieval modes and candidate-safe rollout

## Status

Implementation contract for issue #299. M20.4 consumes the verified M20.3 Runtime through a separate retrieval controller. It does not modify the public API or the ordinary Runtime query implementation.

## Modes

The controller reads an explicit mode policy:

```text
RETRIEVAL_MODE=lexical
RETRIEVAL_MODE=hybrid
RETRIEVAL_MODE=vector
```

Lexical is the default and remains the complete production-safe baseline.

### Lexical

- calls the existing Runtime lexical/wiki-first query path;
- requires no semantic artifacts or query vector;
- preserves original results, citations, evaluation and not-found behavior;
- records that no fusion or production mutation occurred.

### Hybrid

Hybrid is candidate/shadow evaluation only in M20.4:

1. execute the unchanged lexical query;
2. execute the verified M20.3 vector diagnostic with the same release and ACL set;
3. keep lexical results authoritative;
4. attach vector ranking only as bounded `shadow_evaluation` evidence;
5. set `fusion_applied: false`.

No vector score changes lexical ordering. Reciprocal-rank fusion, weighted fusion and other score composition begin no earlier than M20.5.

### Vector

Vector mode is diagnostic only:

- requires an explicit precomputed normalized query vector;
- returns section/concept identity, audience and cosine score;
- returns no generated answer, original body or citations;
- carries no production authority.

## Configuration policy

Semantic modes require all of the following:

- non-production application environment;
- non-production knowledge channel;
- exact expected semantic model ID;
- exact bounded vector dimension;
- explicit semantic diagnostic enablement.

Unsafe combinations fail during settings validation. Production and the production channel accept lexical mode only.

## Query-vector boundary

M20.4 does not call an embedding provider. Candidate evaluators must supply a finite, correctly dimensioned, L2-normalised query vector. Missing, malformed, non-finite or non-normalised vectors fail closed.

The controller accepts at most 20 results and an 8,000-character textual query. Audience sets must contain non-empty strings.

## Identity and ACL

Hybrid requires lexical and vector results to carry the same release ID and manifest SHA-256. Vector results are produced by M20.3, which filters ACL before serialization and uses deterministic score/section ordering.

Cross-release shadow evidence is rejected. Restricted text, cache paths, object keys, credentials and raw vectors are not exposed.

## Isolation and rollback

The controller is a separate retriever. It does not modify:

- `Runtime.query()`;
- FastAPI request or response contracts;
- compiler or release manifests;
- canonical Markdown, lexical index or graph artifacts.

Rollback is configuration-only:

```text
RETRIEVAL_MODE=lexical
```

No Source edit, graph migration, vector deletion or production pointer rollback is required merely to disable semantic retrieval.

## Acceptance

M20.4 acceptance covers:

- lexical default and production safety;
- invalid mode/environment/channel policy;
- exact model/dimension/diagnostic requirements;
- lexical parity without semantic artifacts;
- hybrid lexical authority and deterministic shadow output;
- vector diagnostic-only output;
- semantic capability mismatch;
- query-vector dimension and norm bounds;
- cross-release rejection;
- path-free capability status;
- M20.1 through M20.3 and existing Runtime regressions.

## Exclusions

M20.4 does not implement rank fusion, alias boost, tag boost, relation scoring, reranking, text-to-vector provider calls, Runtime network access, ANN, a vector database, a new public vector endpoint, Source mutation, candidate or production publication, production pointer changes, retained R2 objects, credentials, permanent ledger entries, rollback execution, M20.5 work, cross-release merge or Graph Neural Retrieval.

## Closure reconciliation

### Identity chain

- M20.3 reconciliation / implementation base: `3ce4133d06b158948737bbecee796ea0191a3747`
- implementation head: `cb97e2def1295ee0c45cb4ff7e05d7c5bc19ff62`
- implementation merge: `7a209586ae9bce25336bfa7c034d6f137cbfbc1d`
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

### Exact implementation scope

Implementation PR #300 changed exactly four files:

1. `.github/workflows/m20-4-retrieval-modes.yml`
2. `docs/architecture/m20/m20-4-retrieval-modes.md`
3. `src/knowledge_engine/m20_retrieval_modes.py`
4. `tests/test_m20_4_retrieval_modes.py`

No Runtime, API, configuration core, dependency, lockfile, compiler, release manifest, Source, production pointer, credential, permanent ledger or rollback file changed.

### Final-head acceptance evidence

All workflows associated with implementation head `cb97e2def1295ee0c45cb4ff7e05d7c5bc19ff62` completed successfully:

- M20.4 Retrieval modes #1
- CI #630
- M17 Architecture Canon Acceptance #42
- M18 Graph v2 acceptance #66
- R2 Release Integration #436

The M20.4 workflow passed exact-head checkout, repository Ruff, M20.1 through M20.4 tests, existing Runtime regressions, mode-isolation checks, deferred-fusion checks, authority/dependency scanning and Python compilation.

Implementation PR #300 had no conversation comments, submitted reviews or unresolved review threads at merge time.

### Delivered boundary

- lexical remains the complete production-safe baseline;
- hybrid is lexical-authoritative shadow evidence only;
- vector is diagnostic identity-and-score output only;
- semantic modes require explicit non-production context, exact model/dimension policy and diagnostic enablement;
- cross-release evidence, malformed vectors and unavailable semantic capability fail closed;
- no rank fusion, provider call, Runtime/API mutation or production authority was introduced.

Production mutation dispatched: false.
