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
