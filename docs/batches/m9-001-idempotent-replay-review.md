# M9.9 Idempotent Replay Review

## Decision

Daniel explicitly approved one idempotent replay with the authorization text:

`進M9.9 Review and Explicitly Approve Idempotent Replay`

The approval is recorded in issue #119 and in the immutable contract:

`governed_batches/evidence/m9-001-idempotent-replay-approval.json`

## Operation identity

- Batch: `m9-001-agent-planning-strategies`
- Lifecycle before replay: `production_promoted`
- Operation ID: `m9-001-agent-planning-strategies-001`
- Request path: `production_promotions/m9-001-agent-planning-strategies.json`
- Request SHA-256: `41564a42a3f207ea87bbc600935effbb9c3979c8366e16a4b1c7d1f35e172b5b`

The replay must use the same operation ID and exact request bytes. A replacement operation, modified request, or substituted target is not authorized.

## Existing successful promotion

- Promotion run: `28919098263`
- Promotion job: `85792150635`
- Promotion artifact: `8158736427`
- Artifact digest: `sha256:4ff4418ea5e792d24369846dfb39930fa6815fc5c42a3b8d62a90a9fa9806d7a`
- Original precondition: `ready_to_promote`
- Original result: `promoted`
- Original idempotent flag: `false`
- Permanent ledger comment: `4911573318`

## Current production identity

- Release: `20260708T040116Z-69a9f445699a`
- Manifest SHA-256: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Pointer SHA-256: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

The approval workflow must read this pointer without mutation and confirm byte-exact identity before the approval is eligible to merge.

## Required replay outcome

A successful replay must prove all of the following:

- production precondition is `already_target`
- promotion status is `already_promoted`
- `idempotent` is `true`
- the production pointer bytes remain unchanged
- the original operation intent is reused
- the original promotion receipt is reused
- the public query remains `answered`
- the exact Part 3 citation remains present
- `cobalt heron checkpoint` remains `not_found`
- raw fallback remains false for both public and ACL checks
- exactly one replay evidence entry is appended to permanent ledger #30

## Authorization boundary

This approval authorizes one replay dispatch and the validation work required to prove idempotency. It also authorizes a later reconciliation from `production_promoted` to `closed`, but only after the replay artifact has been downloaded and inspected successfully.

It does not authorize:

- dispatch during the approval PR
- request modification
- operation ID replacement
- target substitution
- baseline weakening
- raw fallback
- rollback
- a new non-idempotent promotion
- a second or later replay
- immediate lifecycle closure

## State after approval

The batch remains `production_promoted`. No R2 object, production pointer, permanent ledger entry, or lifecycle state is mutated by M9.9.

The next executable phase after this approval merges is a separately controlled dispatch of the same production request, followed by artifact inspection and closure reconciliation.
