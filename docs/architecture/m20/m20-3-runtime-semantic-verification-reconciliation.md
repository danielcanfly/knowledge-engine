# M20.3 Runtime semantic verification reconciliation

## Closure status

M20.3 is implemented by issue #296 and implementation PR #297. This document reconciles the exact implementation evidence before issue closure.

## Identity chain

- M20.2 reconciliation / implementation base: `b1b8bc0d271e71a25499dcee3e25db7b08010ca4`
- final implementation head: `833a3220beeb26fc24300b9daced7a130d4d38b7`
- implementation merge: `4bc1adacb864a70e9f4140d288c51c870f65b250`
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

## Exact implementation scope

Implementation PR #297 changed exactly five files:

1. `.github/workflows/m20-3-runtime-semantic.yml`
2. `docs/architecture/m20/m20-3-runtime-semantic-verification.md`
3. `src/knowledge_engine/m20_runtime_semantic.py`
4. `src/knowledge_engine/runtime.py`
5. `tests/test_m20_3_runtime_semantic.py`

The PR contained no dependency, lockfile, compiler, manifest publication, API endpoint, production pointer, credential, permanent ledger or rollback change.

## Runtime contract delivered

- semantic metadata and vectors are optional only as a complete pair;
- manifest byte count and SHA-256 checks run before semantic parsing;
- metadata schema, self-digest, provider/model/tokenizer identity, dimensions, dtype, endianness, normalization, row count and vector digest fail closed;
- Source and Foundation identities must match the active release manifest;
- every semantic section maps exactly once to a lexical section with matching concept, audience, path and section-text digest;
- verified float32 vectors are memory-mapped read-only;
- capability status is bounded and path-free;
- diagnostic vector retrieval is disabled by default, accepts only an explicit precomputed normalized vector, applies ACL filtering before serialization and uses deterministic score/section ordering;
- ordinary Runtime `query()` remains unchanged;
- a failed refresh closes the new mapping, removes staging state and preserves the last-known-good active release.

## Failures and repair evidence

Two implementation heads were invalidated before the final green head:

- `3dd85b9bf24ed7ceb57a47db48dd5e6ad4308651` failed before code execution because the new workflow checked out GitHub's synthetic pull-request merge commit rather than the exact branch head. The workflow was repaired to set the checkout ref explicitly.
- `5831e4794df71912b41cee557a47fd06032692dd` passed exact-head checkout, then repository Ruff rejected long lines in the new test file. The test file was formatted under the repository's actual `line-length = 100` configuration.

No workflow result from either invalidated head was used as acceptance evidence.

## Final-head acceptance evidence

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

## Non-authoritative branch record

An empty branch named `agent/m20-3-runtime-semantic` was accidentally created from the exact implementation base before issue #296. It received no commits, was not the PR head and has no implementation, CI, release or closure evidence role.

## Exclusions preserved

M20.3 did not add a text-to-vector provider call, Runtime network dependency, normal-query retrieval-mode switch, hybrid fusion, alias/tag/relation scoring, ANN cache, vector database, public API endpoint, Source edit, candidate or production publication, production pointer mutation, retained R2 object, credential, permanent ledger entry, rollback, M20.4 implementation, cross-release merge or Graph Neural Retrieval.

Production mutation dispatched: false.
