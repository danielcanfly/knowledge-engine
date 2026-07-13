# M20.2 Immutable Semantic Artifacts

Status: implementation contract for issue #293

## Exact baseline

- Engine base: `d6cd1dd613ad4675aab216356956c9abdf6e4053`
- M20.1 issue / implementation / reconciliation: #290 / #291 / #292
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

M20.1 remains the authority for provider, model, tokenizer, preprocessing, batching, benchmark and repository identities. M20.2 consumes those accepted contracts and does not select a production model.

## Canonical derived artifacts

M20.2 produces one immutable directory containing exactly:

```text
semantic-metadata.json
semantic-vectors.f32
```

Markdown remains canonical truth. The binary matrix is derived, replaceable and non-authoritative. No ANN index or mutable vector service becomes part of the canonical release.

`semantic-vectors.f32` contains deterministic little-endian float32 rows. Every input vector is converted to float32 before validation and must remain finite and L2-normalised after conversion.

`semantic-metadata.json` uses `knowledge-engine-semantic/v2` and records:

- builder Engine SHA;
- M20.1 provider-contract Engine SHA;
- Source and Foundation SHAs;
- canonical provider-contract and benchmark-suite digests;
- provider, model, tokenizer and preprocessing identity;
- dimension, dtype, endianness and normalisation;
- vector byte length, row count and SHA-256;
- exact row-to-concept, section, language, audience, source path and source-text digest mapping;
- a metadata digest calculated over the complete metadata payload except the digest field itself.

Rows follow the validated M20.1 section-ID ordering. Missing, duplicate, extra or reordered identities are rejected.

## Immutability and atomicity

The builder refuses an existing output directory. It writes both artifacts inside a sibling staging directory, fsyncs the files, marks them read-only and atomically renames the completed directory into place.

Artifacts are content-addressed through provider-contract, benchmark-suite, identity and vector digests. Rebuilding the same inputs with the same builder identity produces byte-identical metadata and vectors.

A new model, Source revision, preprocessing rule or vector matrix must produce a new artifact directory. M20.2 performs no in-place update.

## Verification

Verification is fail closed and checks:

1. metadata schema, immutability, read-only state and non-production authority;
2. metadata self-digest;
3. exact builder, provider-contract, Source and Foundation identities;
4. provider-contract and benchmark-suite digests;
5. model, tokenizer, preprocessing, dimension, dtype and endianness;
6. vector filename, SHA-256, byte length and row count;
7. exact row-to-section mapping and source text digests;
8. float finiteness and unit norm for every binary row.

Truncation, tampering, duplicate or unknown sections, wrong dimensions, NaN, infinity, non-normalised rows and cross-release inputs are rejected before retrieval.

## Flat-cosine correctness baseline

M20.2 includes a deterministic flat-cosine reference reader for correctness tests. Because all rows and query vectors are L2-normalised, cosine similarity is the dot product. Ranking uses descending score and section ID as the stable tie-breaker. Audience filtering occurs before a result is returned.

The reference implementation intentionally uses the Python standard library and introduces no numerical or ANN runtime dependency. NumPy memory mapping and production-scale loader budgets belong to M20.3, where the Runtime verifies and loads these artifacts. The canonical float32 format remains directly compatible with that later implementation.

## CLI

`scripts/m20_semantic_artifacts.py` provides three read-only operations:

- `build`: consume a validated suite, provider contract and section-to-vector JSON mapping;
- `verify`: validate an existing artifact directory and emit a bounded verification report;
- `rank`: run diagnostic flat-cosine ranking against a verified artifact.

The CLI has no model-download, network, object-store, publication, pointer, ledger or Runtime authority.

## Acceptance

The exact-head workflow proves:

- repository Ruff compliance;
- M20.1 regression plus the complete M20.2 suite;
- two independent builds are byte-identical;
- metadata and binary verification succeeds against the exact workflow head;
- flat-cosine ranking is deterministic and ACL filtered;
- vector and metadata tampering fail;
- no committed `.f32` artifact, model dependency, vector database or write-back surface is introduced;
- Python compilation and repository CI remain green.

## Boundary

M20.2 does not add a selected production embedding model, model download, Runtime loader, memory mapping, retrieval-mode switch, vector-only query path, hybrid fusion, ANN cache, API endpoint or publication action.

It does not modify production, candidate publication, the production pointer, retained R2 objects, credentials, permanent ledgers or rollback state. M20.3 remains a separate gate. Graph Neural Retrieval remains excluded.
