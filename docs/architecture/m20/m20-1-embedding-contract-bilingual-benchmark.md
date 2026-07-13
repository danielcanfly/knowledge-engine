# M20.1 Embedding Provider Contract and Bilingual Blog Benchmark

Status: implementation contract for issue #290

## Exact baseline

- Engine base: `b33d06a8f2b9896a8be29009f36cbbde4b5cb5c1`
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- M19 / Phase B is closed and remains unchanged.

## Scope

M20.1 creates a provider-neutral contract and a deterministic bilingual benchmark. It does not select or download a production model and does not create semantic vector artifacts.

The provider contract records:

- provider name, implementation and execution mode;
- model ID and exact revision or SHA-256 digest;
- tokenizer ID and exact revision or SHA-256 digest;
- vector dimension;
- pooling and vector normalisation;
- document and query input templates;
- maximum input length and truncation policy;
- Unicode NFKC normalisation;
- batch size, deterministic execution and input-order preservation;
- exact Engine, Source and Foundation identities;
- a read-only authority statement.

Markdown remains canonical. Embeddings are derived materialised data. A provider contract has no Source, Runtime, release, storage, publication or production authority.

## Bilingual benchmark

`benchmarks/m20/bilingual-blog-benchmark-v1.json` contains fixed English and Traditional Chinese section excerpts from Daniel's Harness Theory and Production RAG article families.

Every document has:

- one stable section ID;
- one concept ID;
- language and audience;
- title and bounded text;
- source path;
- SHA-256 of the exact benchmark text.

The suite includes realistic queries for:

- exact names;
- paraphrases;
- Chinese query to English section;
- English query to Chinese section;
- capability and dependency questions;
- not-found behaviour;
- public ACL-negative behaviour.

Document and query order is canonicalised by stable ID. Duplicate IDs, unknown expected sections, text hash drift, malformed identities and invalid not-found expectations fail closed.

## Lexical baseline

M20.1 includes a deterministic lexical baseline for comparison. It is not presented as a quality target and is not silently tuned to hide weaknesses.

The committed suite currently produces these stable local baseline metrics at `K=5`:

- Recall@5: `0.900000`;
- MRR: `0.900000`;
- exact-name Recall@5: `1.000000`;
- paraphrase Recall@5: `1.000000`;
- cross-language Recall@5: `0.666667`;
- not-found accuracy: `0.000000`.

The weak not-found result is intentional evidence. Later candidate embedding models must be compared against the same fixed suite rather than a revised test crafted around their outputs.

## Candidate evaluation interface

`scripts/m20_embedding_benchmark.py` can:

1. validate the suite;
2. validate an optional provider contract;
3. generate the lexical baseline, or load candidate rankings;
4. enforce complete query coverage and known unique section IDs;
5. compute Recall@K, MRR, not-found accuracy and category metrics;
6. emit canonical suite, contract and result digests.

Candidate rankings are data only. M20.1 does not invoke a model, download weights, call a remote embedding API or persist vectors.

## Acceptance

The exact-head workflow:

- installs the existing locked Python development environment;
- lints the M20.1 module, CLI and tests;
- runs the complete M20.1 test suite;
- runs the benchmark twice and requires byte-identical output;
- verifies expected baseline metrics and public ACL exclusion;
- scans the M20.1 scope for network clients, model download libraries, vector artifact output and production/write-back authority;
- compiles the Python scope;
- runs existing Runtime, M18 and M19 regression tests through repository CI and applicable workflows.

## Non-goals

M20.1 does not add:

- a selected production embedding model;
- `semantic-metadata.json` or `semantic-vectors.f32`;
- Runtime vector loading or memory mapping;
- flat-cosine Runtime retrieval;
- hybrid rank fusion;
- ANN indexes or vector databases;
- new API routes;
- Source edits;
- candidate or production publication;
- production pointer, R2, credentials, permanent ledger or rollback mutation;
- Graph Neural Retrieval.
