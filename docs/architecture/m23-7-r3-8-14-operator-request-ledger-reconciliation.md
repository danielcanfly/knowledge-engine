# M23.7-R3.8.14 independent operator request-ledger reconciliation

Implementation PR #575 accepted head `4da6a81f5a7f70939eacfe9d195d795e0e580678` and merged as `7af93ece0078aab08b43c2709709825a22ad6d2d`.

Independent review confirms an exact ten-file implementation scope. The change replaces the unreliable issue-comment execution surface with an immutable request ledger while retaining the prior authorization, recovery and telemetry evidence.

## Reconciled request surface

Execution is triggered only by a push to `main` that changes:

```text
operator_requests/m23/**
```

The validator requires exact event `before` and `after` SHAs, first run attempt, and exactly one newly added canonical request JSON. Request modification, deletion, rename, multiple additions and non-canonical JSON are rejected.

Each request binds:

- a request ID matching its filename;
- the exact pre-merge base SHA;
- a committed authorization path;
- a fresh 256-bit nonce;
- the static command type `r3_8_post_delete_recovery`;
- telemetry issue #565;
- a canonical request digest.

A separate pull-request workflow validates the request before merge and grants no execution authority itself. The merge push becomes the audited dispatch event, and the event `after` SHA becomes the exact execution head.

## Telemetry and authority

Accepted and final status records remain fixed to locked issue #565. They expose the Actions run ID, run URL, exact head, authorization digest, final exit code and artifact name. Issue-comment execution is inactive.

The v3 authorization is read-only:

```text
ccafc925c4db5f6398d3ac1fa45d63831e6eaa047cc3d09e725ceef8833a56ff
```

The request-ledger contract is:

```text
039eee1a7a3731bb5942b5c556fe3db038a68d7c816b505de905c2683161fb29
```

The independent reconciliation digest is:

```text
5c93e393d841a80911e6ed808252d294c8a1f757a6bb7701ab285988b1a4e929
```

## Exact-head evidence

All implementation workflows succeeded on the accepted head:

- request ledger gate `29525204683`;
- successor-aware command-bus regression `29525204719`;
- trigger-agnostic telemetry regression `29525204730`;
- global CI `29525204714`;
- M17 `29525204760`;
- M18 `29525204796`.

## Disposition

After this reconciliation merges, the next lawful action is a separate request-only PR based on the reconciliation merge SHA. Its expected-base identity must be regenerated from that SHA. Expected-head merge of the request PR will trigger the read-only recovery and self-report the run and artifact without user copy and paste.

Production retrieval remains lexical. Both blockers remain active. No Worker deletion, deployment, Qdrant/R2 access, blocker clearance, promotion or closure is authorized by this reconciliation.
