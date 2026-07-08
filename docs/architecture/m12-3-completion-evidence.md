# M12.3 Completion Evidence

## Scope

M12.3 adds an immutable golden query baseline gate over M12.2 suite reports. The gate is deterministic, replayable, ACL/audience-aware, and release-blocking on regression.

## Required preflight

- M11 parent #146 closed completed.
- M11.6 #156 and M11.7 #157 closed completed.
- M11 merge commit: `20ad492ee0efe31abb71a581a8b08452ad769798`.
- M11 exact reviewed head: `8a9cb1a028a7fb40c2c660ced63c70dd461ef3ca` with CI #371, R2 Canary #99, and R2 Release Integration #227 successful.
- M12.1 PR #160 merged at `68a4bf7673a6d83908cfb25895c9c89d90335100`.
- M12.2 PR #162 merged at `247ab2f1cd4b9b965811ca835f1bbee5d1bc044a`.
- M12.2 exact head `52d02f8a3213d5084a3e689844536d38dbb8a966` had CI #378, R2 Canary #103, and R2 Release Integration #234 successful.
- Canonical Source remains `2126db2ed4d372d3d61464fe31a86fc0243a1f24`.
- Production release remains `20260708T040116Z-69a9f445699a`.
- Production manifest remains `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`.
- Production pointer remains `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`.
- Permanent ledger #30 remains open and is not appended.

## Delivered controls

- `GoldenQueryBaseline` immutable contract.
- Deterministic `gqbaseline_` contract identity.
- Deterministic `gqbaselinecheck_` report identity.
- Fail-closed checks for suite, release, manifest, passed-count, failed-count, release-blocking-count, required case, unexpected failure reason, and audience broadening drift.
- Explicit governance payload denying canonical Source, candidate, release, production, rollback, and permanent ledger writes.
- Replay/idempotency test coverage.
- Regression and ACL/audience broadening test coverage.
- Documentation and R2 Canary path coverage.

## Post-merge evidence

Fill after exact-head CI/R2 and merge:

- PR:
- reviewed exact head:
- merge commit:
- CI:
- R2 Canary:
- R2 Release Integration:
