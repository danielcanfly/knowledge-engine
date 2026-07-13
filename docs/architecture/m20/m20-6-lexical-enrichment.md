# M20.6 deterministic lexical signal enrichment

## Status

Implementation contract for issue #305. M20.6 adds a separate lexical-enrichment layer on top of already ACL-filtered lexical candidates. Runtime, FastAPI, M20.5 fusion, release publication, and production controls remain unchanged.

## Authority boundary

The original lexical result list, citations, answer, and evaluation evidence remain authoritative. M20.6 emits a bounded `enriched_lexical_candidates` list for deterministic non-production evaluation only.

The enrichment bundle must be explicitly supplied by the caller and must match the lexical result release ID and manifest SHA-256. M20.6 does not scan Source, infer aliases, derive tags, or traverse the graph automatically.

## Fixed signal model

M20.6 uses immutable integer weights:

- exact alias match: `120`
- each matched tag: `20`, capped at `60`
- each matched typed relation: `10`, capped at `40`
- maximum input lexical candidates: `40`
- maximum returned enriched candidates: `20`

No learned weights, vector scores, lexical raw scores, or hidden heuristics are added to these signals.

Final ordering is deterministic:

1. signal score descending;
2. original lexical rank ascending;
3. section ID ascending.

## Normalisation

Queries, aliases, tags, relation types, target concept IDs, section IDs, concept IDs, and audiences use Unicode NFKC plus case folding. Empty strings, overlong values, duplicate normalised values, and malformed structures fail closed.

## Release and identity binding

Before scoring:

- lexical result and enrichment bundle release ID must match;
- lexical result and enrichment bundle manifest SHA-256 must match;
- every lexical section must have exactly one enrichment row;
- no enrichment row may point outside the lexical candidate set;
- section, concept, and audience identity must agree;
- every lexical row must already be allowed for the caller audience;
- alias, tag, and relation counts must remain within bounds;
- relation type plus target concept ID pairs must be unique.

## Evidence

Each enriched candidate contains:

- section ID;
- concept ID;
- audience;
- original lexical rank;
- matched aliases;
- matched tags;
- matched typed relations;
- alias, tag, and relation component scores;
- final signal score;
- a deep copy of the original lexical result.

The evidence contains no raw vectors, cache paths, object keys, credentials, hidden text, new citations, or unfiltered relation payloads.

## ACL

M20.6 consumes only already ACL-filtered lexical candidates and revalidates every candidate audience before scoring. An unauthorised lexical row is an integrity failure, not a skippable enrichment miss.

## Acceptance

M20.6 acceptance covers:

- fixed signal arithmetic and stable ordering;
- exact alias matching with Unicode NFKC and case folding;
- independent tag and relation evidence;
- preserved lexical results, citations, and evaluation authority;
- cross-release rejection;
- ACL rejection before scoring;
- missing, extra, and duplicate enrichment rows;
- concept and audience identity drift;
- duplicate relation rejection;
- request and signal-count bounds;
- M20.1 through M20.5 and Runtime regressions.

## Exclusions

M20.6 does not modify Runtime, FastAPI, M20.5 RRF, semantic-only candidates, fallback policy, embedding providers, network access, ANN, vector databases, answer generation, public endpoints, Source, candidate or production publication, production pointers, retained R2 objects, credentials, permanent ledgers, rollback, M20.7 work, cross-release merge, or Graph Neural Retrieval.

## Closure reconciliation

### Identity chain

- M20.5 reconciliation / implementation base: `5dc857b61c1adb4b85b99006db40b419f9151d4e`
- final implementation head: `26a761ba28ba9ea7af3529c03c5c547cb2bcf336`
- implementation merge: `5d51e9533a08d0c3549799d555530be3dd2ff86a`
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

### Exact implementation scope

Implementation PR #306 changed exactly four files:

1. `.github/workflows/m20-6-lexical-enrichment.yml`
2. `docs/architecture/m20/m20-6-lexical-enrichment.md`
3. `src/knowledge_engine/m20_lexical_enrichment.py`
4. `tests/test_m20_6_lexical_enrichment.py`

No Runtime, FastAPI, M20.5 fusion, dependency, lockfile, compiler, release manifest, Source, production pointer, credential, permanent ledger, or rollback file changed.

### Invalidated heads

- `398346ef82f4b3050164221f36fe9d7e20bbcb73` was invalidated after repository Ruff rejected one unused import.
- `c4e6a5a679c219ac7498859bb861aefae50f83cc` was invalidated after an acceptance assertion incorrectly treated alias and tag signals as mutually exclusive.

Neither head is acceptance evidence.

### Final-head acceptance evidence

All workflows associated with implementation head `26a761ba28ba9ea7af3529c03c5c547cb2bcf336` completed successfully:

- M20.6 Lexical enrichment #3
- CI #644
- M17 Architecture Canon Acceptance #52
- M18 Graph v2 acceptance #80
- R2 Release Integration #446

The M20.6 workflow passed exact-head checkout, repository Ruff, M20.1 through M20.6 tests, Runtime regressions, fixed-weight assertions, authority/dependency scanning, and Python compilation.

Implementation PR #306 had no conversation comments, submitted reviews, or unresolved review threads at merge time.

### Delivered boundary

- lexical results, citations, answers, and evaluation remain authoritative;
- alias, tag, and typed-relation evidence is release-bound and deterministic;
- ACL, identity, uniqueness, and bounds are revalidated before scoring;
- no Runtime/API integration, automatic Source parsing, vector fusion change, provider call, or production authority was introduced.

Production mutation dispatched: false.
