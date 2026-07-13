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
