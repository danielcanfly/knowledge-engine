# M20.3 Runtime semantic verification

## Status

Implementation contract for issue #296. M20.2 remains the immutable artifact producer; M20.3 only verifies and consumes those artifacts inside Runtime.

## Runtime activation boundary

A release may omit semantic artifacts and continue to use the complete lexical baseline. If either semantic artifact is present, both are mandatory:

- `semantic_metadata`
- `semantic_vectors`

`Runtime.refresh()` first applies the existing release-manifest byte count and SHA-256 checks. It then validates the semantic pair inside the staging cache. The active release is replaced only after every check and the read-only memory map succeed.

A semantic failure:

- closes the newly opened mapping,
- removes the staging cache,
- leaves the previous `ActiveRelease` unchanged,
- never returns partially verified semantic results.

## Verification contract

The Runtime loader validates:

- metadata schema `knowledge-engine-semantic/v2`,
- immutable, read-only, non-production authority flags,
- metadata self-digest,
- provider-contract and benchmark digests,
- provider, model, tokenizer, templates and preprocessing identity,
- float32, little-endian, L2-normalised vector encoding,
- bounded row count, dimension and byte length,
- vector SHA-256,
- finite values and unit norm for every row,
- exact Source and Foundation SHA alignment with the release manifest,
- contiguous row ordering,
- unique section IDs,
- exact semantic-to-lexical section coverage,
- concept, audience, source path and section-text digest alignment.

Optional Runtime policy may require one exact model ID and vector dimension. A mismatch blocks activation.

## Memory mapping

Verified `semantic-vectors.f32` is opened with a read-only `mmap`. The capability response is intentionally path-free and bounded:

- status,
- memory-mapped boolean,
- diagnostic-enabled boolean,
- artifact ID,
- row count,
- dimension,
- provider,
- model ID.

It does not expose cache paths, object keys, credentials, raw vectors, restricted text or hidden configuration.

## Diagnostic vector retrieval

`Runtime.query_vector_diagnostic()` is disabled by default and is not connected to an HTTP endpoint in M20.3. It accepts only a caller-supplied, finite, correctly dimensioned, L2-normalised vector.

The diagnostic path:

1. requires the explicit constructor flag,
2. requires an active verified semantic mapping,
3. filters rows by audience before result serialization,
4. computes deterministic flat cosine through the mapped float32 matrix,
5. sorts by descending score and then stable section ID,
6. returns at most 20 identity-and-score rows,
7. returns no generated answer, original passage body or citations.

Ordinary `Runtime.query()` is unchanged. Text-to-vector provider calls, retrieval-mode switching and hybrid rank fusion begin no earlier than M20.4.

## Acceptance

M20.3 tests cover:

- successful verified mmap activation,
- optional absence of the complete pair,
- rejection of a partial pair,
- disabled diagnostic behavior,
- ACL filtering before serialization,
- exact model policy mismatch,
- metadata tamper with last-known-good preservation,
- query dimension, normalisation and limit bounds,
- M20.1, M20.2 and existing Runtime regressions.

## Exclusions

M20.3 does not add a model download, network provider, NumPy, ANN cache, vector database, API endpoint, hybrid mode, normal-query ranking change, Source mutation, candidate or production publication, production pointer update, retained R2 object, credential, permanent ledger entry, rollback, cross-release merge or Graph Neural Retrieval.

## Closure reconciliation

M20.3 was implemented by issue #296 and implementation PR #297.

### Identity chain

- M20.2 reconciliation / implementation base: `b1b8bc0d271e71a25499dcee3e25db7b08010ca4`
- final implementation head: `833a3220beeb26fc24300b9daced7a130d4d38b7`
- implementation merge: `4bc1adacb864a70e9f4140d288c51c870f65b250`
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

### Exact implementation scope

Implementation PR #297 changed exactly five files:

1. `.github/workflows/m20-3-runtime-semantic.yml`
2. `docs/architecture/m20/m20-3-runtime-semantic-verification.md`
3. `src/knowledge_engine/m20_runtime_semantic.py`
4. `src/knowledge_engine/runtime.py`
5. `tests/test_m20_3_runtime_semantic.py`

The PR contained no dependency, lockfile, compiler, manifest publication, API endpoint, production pointer, credential, permanent ledger or rollback change.

### Failure and repair evidence

Two implementation heads were invalidated before the final green head:

- `3dd85b9bf24ed7ceb57a47db48dd5e6ad4308651` failed before code execution because the workflow checked out GitHub's synthetic pull-request merge commit instead of the exact branch head. The checkout ref was fixed.
- `5831e4794df71912b41cee557a47fd06032692dd` passed exact-head checkout, then repository Ruff rejected long lines in the new test file. The test file was formatted under the repository's actual `line-length = 100` configuration.

No workflow result from either invalidated head was used as acceptance evidence.

### Final-head acceptance evidence

All seven workflows associated with final head `833a3220beeb26fc24300b9daced7a130d4d38b7` completed successfully:

- M20.3 Runtime semantic verification #3
- CI #624
- M17 Architecture Canon Acceptance #39
- M18 Graph v2 acceptance #60
- M18.6 Runtime compatibility #9
- R2 Canary #232
- R2 Release Integration #434

The M20.3 workflow passed exact-head checkout, repository Ruff, M20.1 through M20.3 tests, existing Runtime regressions, diagnostic-isolation checks, authority/dependency scanning and Python compilation.

Implementation PR #297 had no conversation comments, submitted reviews or unresolved review threads at merge time.

### Non-authoritative branch record

An empty branch named `agent/m20-3-runtime-semantic` was accidentally created from the exact implementation base before issue #296. It received no commits, was not the PR head and has no implementation, CI, release or closure evidence role.

### Protected-state exclusions

M20.3 did not add a text-to-vector provider call, Runtime network dependency, normal-query retrieval-mode switch, hybrid fusion, alias/tag/relation scoring, ANN cache, vector database, public API endpoint, Source edit, candidate or production publication, production pointer mutation, retained R2 object, credential, permanent ledger entry, rollback, M20.4 implementation, cross-release merge or Graph Neural Retrieval.

Production mutation dispatched: false.
