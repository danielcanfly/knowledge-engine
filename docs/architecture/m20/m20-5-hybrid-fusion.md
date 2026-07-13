# M20.5 deterministic hybrid rank fusion

## Status

Implementation contract for issue #302. M20.5 consumes the closed M20.4 retrieval-mode controller through a separate hybrid-fusion layer. Runtime, FastAPI, release publication, and production controls remain unchanged.

## Authority boundary

Lexical retrieval remains the answer, citation, and evaluation authority. M20.5 adds a bounded `fused_candidates` list for non-production hybrid evaluation. It does not replace top-level lexical `results`, citations, or evaluation evidence.

The controller delegates lexical and vector modes unchanged. Fusion runs only for M20.4 `hybrid` mode, which is already forbidden in production application or production channel configuration.

## Fusion formula

M20.5 uses fixed reciprocal rank fusion:

```text
score(section) = 1 / (60 + lexical_rank) + 1 / (60 + vector_rank)
```

A missing rank contributes zero. Constants are immutable in this milestone:

- method: `reciprocal_rank_fusion`
- `k = 60`
- lexical weight: `1`
- vector weight: `1`
- maximum input candidates per ranking: `40`
- maximum returned fused candidates: `20`

Raw lexical scores and cosine scores are never added, multiplied, normalised together, or treated as comparable units. Vector cosine is retained only as diagnostic evidence.

## Determinism and identity

Before fusion:

- lexical and semantic release ID and manifest SHA-256 must match;
- both rankings must already be ACL-filtered;
- each ranking must contain unique section IDs;
- section, concept, and audience identity must agree across rankings;
- every vector score must be finite;
- result counts must remain within bounds.

Final sorting is deterministic:

1. fused score descending;
2. lexical rank ascending, missing last;
3. vector rank ascending, missing last;
4. section ID ascending.

Each fused candidate contains bounded evidence:

- section ID;
- concept ID;
- audience;
- fused score;
- lexical rank and contribution;
- vector rank and contribution;
- vector cosine score when present;
- a copy of the lexical result only when the section appeared lexically.

## Fallback policy

Lexical fallback is allowed only when semantic candidate generation is unavailable but lexical retrieval remains valid:

- caller did not supply a query vector;
- verified semantic capability is unavailable;
- vector execution reports semantic unavailability.

Fallback returns unchanged lexical results with:

- `fusion_applied: false`;
- `fallback_applied: true`;
- a deterministic reason code;
- an empty `fused_candidates` list.

The following never fall back silently:

- model or dimension policy mismatch;
- malformed or non-normalised vector;
- release identity mismatch;
- duplicate section IDs;
- concept or audience identity drift;
- unauthorised ranked rows;
- malformed result structures;
- non-finite vector scores.

Those conditions remain fail closed.

## ACL and protected data

Fusion receives only M20.4 lexical and M20.3 vector outputs, both of which apply ACL before serialization. M20.5 revalidates every candidate audience against the caller's allowed audiences before fusion.

The fused list contains no hidden text, raw vectors, cache paths, object keys, credentials, restricted metadata, or new citations. Semantic-only candidates contain identity and rank evidence only.

## Acceptance

M20.5 acceptance covers:

- exact RRF arithmetic and stable ordering;
- overlap and semantic-only candidates;
- lexical result, citation, and evaluation authority;
- missing-vector fallback;
- semantic-unavailable fallback;
- model and dimension mismatch fail-closed behavior;
- cross-release rejection;
- ACL filtering before fusion;
- duplicate and identity-drift rejection;
- lexical and vector mode delegation;
- M20.1 through M20.4 and Runtime regressions.

## Exclusions

M20.5 does not add learned weights, raw-score fusion, alias/tag/relation boosts, reranking, answer generation changes, embedding-provider calls, Runtime network access, ANN, a vector database, a public vector endpoint, Source mutation, candidate or production publication, production pointer changes, retained R2 objects, credentials, permanent ledger entries, rollback execution, M20.6 work, cross-release merge, or Graph Neural Retrieval.

## Closure reconciliation

### Identity chain

- M20.4 reconciliation / implementation base: `97ce214e01e3447345c74eac9c9835c59a4d7cf8`
- final implementation head: `5cd2b268fec8b4128bd0d41a76173b917b610d1d`
- implementation merge: `43e341fc9b6a2741521ff77f9a112598bbbebf9a`
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

### Exact implementation scope

Implementation PR #303 changed exactly four files:

1. `.github/workflows/m20-5-hybrid-fusion.yml`
2. `docs/architecture/m20/m20-5-hybrid-fusion.md`
3. `src/knowledge_engine/m20_hybrid_fusion.py`
4. `tests/test_m20_5_hybrid_fusion.py`

No Runtime, FastAPI, dependency, lockfile, compiler, release-manifest, Source, production-pointer, credential, permanent-ledger, or rollback file changed.

### Invalidated implementation heads

- `d0f420c378932874d5976fe15ce7c3671c23eb0e` failed repository Ruff on long lines.
- `2dd2d5dd7b4e56d0be7a9f112d6c787e6f62fdf1` failed repository Ruff on one unused import and one unsorted import block.

Neither invalidated head is acceptance evidence.

### Final-head acceptance evidence

All workflows associated with final implementation head `5cd2b268fec8b4128bd0d41a76173b917b610d1d` completed successfully:

- M20.5 Hybrid fusion #5
- CI #638
- M17 Architecture Canon Acceptance #48
- M18 Graph v2 acceptance #74
- R2 Release Integration #442

The M20.5 workflow passed exact-head checkout, repository Ruff, M20.1 through M20.5 tests, Runtime regressions, deterministic rank-only fusion checks, authority/dependency scanning, and Python compilation.

Implementation PR #303 had no conversation comments, submitted reviews, or unresolved review threads at merge time.

### Delivered boundary

- fixed RRF with `k=60` and immutable equal rank contributions;
- lexical results, citations, and evaluation remain authoritative;
- semantic candidates affect only bounded non-production `fused_candidates`;
- missing vectors and semantic unavailability fall back deterministically to lexical;
- model, dimension, release, ACL, identity, duplicate, and malformed-result violations remain fail closed;
- no provider call, Runtime/API mutation, ANN, vector database, or production authority was introduced.

Production mutation dispatched: false.
