# M18.6 Runtime Compatibility Reconciliation

Status: complete

Issue: #261

Production mutation dispatched: false

## Merged identities

| Boundary | Identity |
|---|---|
| Engine main before M18.6 | `0ff5cf59390db87b0d895988dc70cddb35feff10` |
| Implementation PR | #262 |
| Implementation exact head | `b003b643f6726141295afcf6b2aa63092e8887ec` |
| Implementation merged main | `17c78b99fe37b42f1ff4f5dac0a7c638d42476c4` |
| Source main | `087f96b94d045f1f096ad7a3cab0c9ac2f3c5d04` (unchanged) |
| Foundation main | `e5ef644053d34e89c70d2ceb37521e1c59234832` (unchanged) |

PR #262 was squash-merged with expected head SHA
`b003b643f6726141295afcf6b2aa63092e8887ec`. Issue #261 remained open until
this reconciliation change.

## Delivered Runtime contract

Runtime now loads, validates, and retains `graph_v2` when the release manifest
contains it. The artifact remains optional during the compatibility window, so
an immutable older release without graph v2 still loads through the existing
lexical, generic graph, and provenance requirements.

Typed-relation expansion is controlled by the strict boolean
`RELATION_AWARE_EXPANSION_ENABLED` and defaults to `false`. The disabled path
cannot add candidates or change scores. When explicitly enabled in a future
governed environment, the hook is deterministic, single-hop, limited to twenty
typed neighbors per lexical/semantic seed, and rechecks both node and edge
audiences. Existing generic-neighbor expansion stays active.

Runtime exposes typed edge identity, relation type, direction, confidence,
review identity, and provenance references in internal retrieval evidence. The
bounded public ask response continues to omit internal retrieval evidence.

Before replacing the last-known-good active release, Runtime fails closed on
schema or release mismatch, graph v1/v2 node or audience mismatch, renderer
leakage, duplicate identity, missing endpoint, ACL broadening, malformed
direction or inverse markers, unapproved relations, and invalid confidence.

## Changed-file reconciliation

Implementation PR #262 changed exactly:

- `.github/workflows/m18-6-runtime-compatibility.yml`;
- `docs/architecture/m18/m18-6-runtime-compatibility.md`;
- `src/knowledge_engine/api.py`;
- `src/knowledge_engine/cli.py`;
- `src/knowledge_engine/config.py`;
- `src/knowledge_engine/m14_retrieval.py`;
- `src/knowledge_engine/runtime.py`;
- `tests/test_m18_6_runtime_compatibility.py`.

No Source or Foundation file changed.

## Validation evidence

Local validation at the implementation content passed:

- full `make ci`: 830 tests passed;
- targeted Runtime, config, retrieval, and public-contract suite: 31 tests
  passed;
- ruff, compileall, and diff checks passed.

All pull-request workflows associated with exact implementation head
`b003b643f6726141295afcf6b2aa63092e8887ec` completed successfully:

- CI run #574;
- M18.6 Runtime compatibility run #1;
- M18 Graph v2 acceptance run #10;
- M14 Public Product Acceptance run #5;
- M17 Architecture Canon Acceptance run #11;
- R2 Canary run #228;
- R2 Release Integration run #418.

There were no PR comments, reviews, or changed-file exceptions to resolve before
the expected-head merge.

## R2 and production boundary

No production workflow, production promotion, or production pointer update was
dispatched. The M18.6 feature flag was not enabled in production, and no
credential, permanent ledger, lifecycle, or rollback state changed.

The existing repository-wide PR workflows automatically ran their R2 canary and
release-integration gates because Runtime source files changed. The integration
used run-specific test channel `ci-lifecycle-29224438866-1`, exercised two test
releases and a rollback, and executed mandatory `finally` cleanup for the test
pointer and every release object. The successful run emitted no cleanup error.
This was CI validation, not a production or retained R2 mutation, and was not
manually dispatched by M18.6.

## Exclusions

M18.6 did not add a Graph API, Graphology or renderer fields, Sigma Explorer,
hybrid retrieval, embeddings, multi-hop traversal, candidate publication,
production activation, M18.7 closure, or Graph Neural Retrieval.

M18.6 is complete when this reconciliation change passes exact-head Engine CI,
merges with its expected head SHA, and issue #261 closes.
