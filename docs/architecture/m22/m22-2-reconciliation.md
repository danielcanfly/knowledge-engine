# M22.2 Closure Reconciliation

## Status

M22.2 implementation has been reconciled against live GitHub state.

## Governance chain

- authoritative issue: #340;
- implementation PR: #342;
- exact entry base: `5cbf5d9e2871e1ad24ffcc4d5109330c04d9fa5d`;
- accepted implementation head: `75a4d765a23e924ab79e9c7e5eca7f78138ecaf1`;
- implementation merge: `5a62e379caed5848aa6687db026f3b34d64a4800`;
- implementation branch: `feat/m22-2-activation-decision`;
- reconciliation branch: `noop`.

The reconciliation branch name was created accidentally as an empty ref while selecting a connector action. It contained no commit and was fast-forwarded to the exact implementation merge before this reconciliation commit. No duplicate reconciliation branch was created. Accidental issue #341 was immediately closed as `not_planned`; it has no branch, commit, PR, or milestone work attached.

## Accepted implementation scope

The implementation diff contains exactly:

- `.github/workflows/m22-2-activation-decision.yml`;
- `docs/architecture/m22/m22-2-activation-decision.md`;
- `src/knowledge_engine/m22_activation_decision.py`;
- `tests/test_m22_2_activation_decision.py`.

No M22.3 file or executor surface is included.

## Local prevalidation

- 33 focused tests passed;
- syntax compilation passed;
- maximum Python line length remained below the repository Ruff limit.

## Exact-head workflows

The accepted implementation head passed:

- M22.2 Activation Decision #1;
- CI #712;
- M17 Architecture Canon Acceptance #87;
- M18 Graph v2 acceptance #148;
- R2 Release Integration #481.

Earlier or unrelated workflow runs are not acceptance evidence.

## Pull-request audit

PR #342 had:

- exact head `75a4d765a23e924ab79e9c7e5eca7f78138ecaf1`;
- exactly four changed files;
- no conversation comments;
- no submitted reviews;
- no unresolved review threads;
- expected-head merge enabled and used.

## Contract outcome

M22.2 now provides a deterministic, privacy-safe activation decision over the M22.1 policy:

- `off` remains direct-only;
- `force` requests later activation only after ACL and budget validation;
- `auto` uses explicit bounded features and a deterministic threshold;
- raw query text is rejected;
- reason codes and policy, feature, and decision hashes are emitted;
- no planner is constructed or invoked;
- no model/provider call occurs;
- `activate` is evidence only and grants no execution authority.

## Protected-state reconciliation

Confirmed unchanged and unauthorized:

- canonical Source;
- production deployment or promotion;
- production pointer;
- retained R2 objects;
- credentials;
- permanent ledger;
- rollback state;
- Graph Neural Retrieval;
- M22.3 implementation.

Production mutation dispatched: false.
