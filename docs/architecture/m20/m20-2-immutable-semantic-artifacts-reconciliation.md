# M20.2 Immutable Semantic Artifacts Reconciliation

Status: ready to close issue #293

## Identity chain

- M20.1 reconciled Engine base: `d6cd1dd613ad4675aab216356956c9abdf6e4053`
- M20.2 issue: #293
- implementation PR: #294
- implementation expected head: `e72d13635aa3e39ffd7ce375af5864b163f55784`
- implementation merge: `742b5e76aa5d2b1c29821e5b97b9723b939e309f`
- Source main remains `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main remains `e5ef644053d34e89c70d2ceb37521e1c59234832`

This reconciliation branch was created from the exact implementation merge SHA. Issue #293 closes only after this documentation-only PR passes its own exact-head checks and merges with expected-head protection.

## Implementation scope reconciled

PR #294 changed exactly six files:

1. `.github/workflows/m20-2-semantic-artifacts.yml`;
2. `docs/architecture/m20/m20-2-immutable-semantic-artifacts.md`;
3. `schemas/m20-semantic-metadata-v2.schema.json`;
4. `scripts/m20_semantic_artifacts.py`;
5. `src/knowledge_engine/m20_semantic_artifacts.py`;
6. `tests/test_m20_2_semantic_artifacts.py`.

The implementation added no runtime or development dependency and did not modify M20.1 contracts, Runtime, API, release publication, pointer, object-store, ledger or rollback code. The implementation PR had no conversation comments, submitted reviews or inline review threads before merge.

Three temporary marker files were accidentally created during tool selection and deleted before PR creation:

- `docs/architecture/m20/.m20-2-pr-ready`;
- `docs/architecture/m20/.noop`;
- `docs/architecture/m20/.do-not-create`.

They are absent from the final six-file diff and have no implementation, acceptance, release or production evidence role.

## Exact-head implementation evidence

All five workflows completed successfully against exact implementation head `e72d13635aa3e39ffd7ce375af5864b163f55784`:

- M20.2 immutable semantic artifacts run `29244260465` (#1);
- CI run `29244260479` (#618);
- R2 Release Integration run `29244260447` (#430);
- M17 Architecture Canon Acceptance run `29244260467` (#35);
- M18 Graph v2 acceptance run `29244260489` (#54).

The M20.2 workflow verified the exact checked-out head, repository Ruff compliance, all M20.1 regressions, the complete M20.2 artifact test suite, deterministic fixture creation, two byte-identical artifact builds, read-only file modes, metadata and binary verification, ACL-filtered deterministic flat-cosine ranking, vector truncation rejection, metadata tamper rejection, authority and dependency boundaries, absence of committed `.f32` files and Python compilation.

Repository CI independently passed the complete quality gates, reference vertical slice and container build. The R2 lifecycle workflow passed its isolated promotion, query, ACL and rollback regression; M20.2 retained no R2 object and dispatched no production action.

## Accepted artifact contract

M20.2 accepts one immutable derived artifact directory containing exactly:

- `semantic-metadata.json` using `knowledge-engine-semantic/v2`;
- `semantic-vectors.f32` containing little-endian float32 rows.

The accepted contract provides:

- deterministic section-ID row order;
- exact row mapping to concept ID, section ID, language, audience, source path and source text SHA-256;
- builder Engine, provider-contract Engine, Source and Foundation identities;
- canonical provider-contract and benchmark-suite digests;
- model, tokenizer, preprocessing, dimension, dtype, endianness and L2-normalisation identity;
- vectors SHA-256, byte length, row count and metadata self-digest;
- sibling staging, file fsync, read-only file modes and atomic directory rename;
- refusal to overwrite an existing artifact directory;
- rejection of missing, duplicate, extra, non-finite, wrong-dimension or non-normalised vectors;
- rejection of vector truncation, metadata tampering, digest drift and cross-release identity drift;
- deterministic flat-cosine correctness ranking with audience filtering before result return and section ID as the stable tie-breaker.

Markdown remains canonical truth. The semantic matrix is derived, replaceable and non-authoritative. Lexical retrieval remains the complete baseline.

## Boundary and protected-state reconciliation

M20.2 did not select or download a production embedding model. It did not add a Runtime artifact loader, memory mapping, semantic retrieval mode, vector-only query path, hybrid fusion, ANN cache, vector database, API endpoint or publication action.

M20.2 did not modify or promote Source, candidate publication, production, the production pointer, retained R2 objects, credentials, permanent ledgers or rollback state. No production mutation was dispatched.

M20.3 Runtime verification and loading remains a separate future gate. Graph Neural Retrieval remains excluded.
