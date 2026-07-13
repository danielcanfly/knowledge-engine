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
