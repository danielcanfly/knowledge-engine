# M20.1 Embedding Contract and Bilingual Benchmark Reconciliation

Status: reconciled after implementation PR #291

## Identity chain

- M19 / Phase B closure base: `b33d06a8f2b9896a8be29009f36cbbde4b5cb5c1`
- M20.1 final implementation head: `1b5b16ba892f92d7b741722a8c1b215290c28d74`
- M20.1 implementation merge: `8dc726592d8ea6ed4ad2d310a9036da06f775a9f`
- Source main remained: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main remained: `e5ef644053d34e89c70d2ceb37521e1c59234832`

## Delivered implementation

Implementation PR #291 changed exactly these ten files:

1. `.github/workflows/m20-1-embedding-contract-benchmark.yml`
2. `benchmarks/m20/bilingual-blog-benchmark-v1.json`
3. `benchmarks/m20/provider-contract.fixture.json`
4. `docs/architecture/m20/m20-1-embedding-contract-bilingual-benchmark.md`
5. `schemas/m20-embedding-provider-contract-v1.schema.json`
6. `scripts/m20_embedding_benchmark.py`
7. `src/knowledge_engine/_m20_embedding_benchmark.py`
8. `src/knowledge_engine/_m20_embedding_common.py`
9. `src/knowledge_engine/m20_embedding_contract.py`
10. `tests/test_m20_1_embedding_contract.py`

No dependency, lockfile, Runtime, API, release loader or production control file changed.

## Contract closure

M20.1 now provides:

- a provider-neutral embedding contract with exact provider implementation and execution mode;
- exact model and tokenizer revision or SHA-256 digest;
- vector dimension, pooling, normalisation, document/query templates and maximum input length;
- explicit truncation, NFKC, batching, deterministic order and input-order preservation;
- exact Engine, Source and Foundation identities;
- Markdown-canonical, vectors-derived, no-network, no-write-back and no-production authority;
- a fixed bilingual benchmark with eight hash-pinned English and Traditional Chinese sections;
- twelve realistic exact-name, paraphrase, cross-language, dependency, not-found and ACL-negative queries;
- deterministic lexical rankings and candidate-ranking evaluation;
- Recall@K, MRR, exact-name, paraphrase, cross-language and not-found metrics;
- fail-closed hash, identity, query-coverage, duplicate, ACL and vector validation.

No production embedding model was selected. No weights were downloaded and no vector artifact was created.

## Honest lexical baseline

The fixed benchmark at K=5 records:

- Recall@5: `0.900000`
- MRR: `0.900000`
- exact-name Recall@5: `1.000000`
- paraphrase Recall@5: `1.000000`
- cross-language Recall@5: `0.666667`
- not-found accuracy: `0.000000`

The zero not-found accuracy is retained as evidence. It was not tuned away to manufacture a green quality claim. Future candidate models must run against the same benchmark revision.

## CI evidence

The first implementation head failed only because local prevalidation had not loaded the repository Ruff configuration and missed five E501 findings. The branch was repaired under the actual `line-length = 100` rule, the expected head changed, and all results from the earlier head were discarded.

Final expected head `1b5b16ba892f92d7b741722a8c1b215290c28d74` passed:

- M20.1 embedding contract and bilingual benchmark run #5, ID `29243122976`;
- repository CI run #614, ID `29243123010`;
- R2 Release Integration run #428, ID `29243122965`;
- M17 Architecture Canon Acceptance run #33, ID `29243122987`;
- M18 Graph v2 acceptance run #50, ID `29243122997`.

The M20.1 workflow passed exact-head checkout, repository Ruff, twelve tests, two byte-identical benchmark executions, exact baseline metric assertions, authority/dependency scanning and compilation. Repository CI passed quality gates, the reference vertical slice and container build. R2 integration passed isolated promotion, query, ACL and rollback regression testing.

## Review reconciliation

Before merge, PR #291 had:

- no comments;
- no submitted reviews;
- no unresolved review threads;
- exactly the ten expected changed files.

The implementation was merged using expected head SHA `1b5b16ba892f92d7b741722a8c1b215290c28d74`.

## Protected-state exclusions

M20.1 did not modify or dispatch:

- Source or Foundation content;
- candidate or production publication;
- production pointer;
- retained R2 objects;
- credentials;
- permanent ledger;
- rollback state;
- Runtime semantic loading;
- hybrid ranking;
- ANN or vector-database infrastructure;
- M20.2 implementation;
- Graph Neural Retrieval.

Production mutation dispatched: false.
