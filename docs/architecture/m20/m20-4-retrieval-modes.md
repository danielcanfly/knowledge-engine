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
