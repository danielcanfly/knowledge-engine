# M13.1 Architecture and Identity Contracts

Status: implementation candidate  
Parent: #173  
Slice: #174  
Engine baseline: `f57868167aba4fc6a2a8c8e7626275c599a55651`

## Purpose

M13 turns the system from single-batch governed release operation into multi-batch production operations. M13.1 defines the identities and lifecycle rules that make later registries, concurrency, retention, release comparison, and closeout safe.

This slice is contract-only. It does not build candidates, mutate Source, promote production, roll back, delete retention targets, or append the permanent ledger.

## Canonical identities

M13.1 introduces deterministic identities for:

```text
mbatch_   governed multi-batch work item
mop_      operation request/result
mopslot_  production mutation slot identity
candidate-* candidate channel namespace
ledger_*  ledger namespace identifier
rqdecision_ / m12closure2_ / m11closure2_ review evidence references
```

Batch IDs are derived from immutable source, production, requester, timestamp, purpose, and review references. Operation IDs are derived from kind, batch, requester, timestamp, expected previous production, artifact names, and mutation declarations.

## Batch lifecycle

Allowed batch states:

```text
planned
reviewing_source
candidate_ready
awaiting_production_slot
promoting
closed
rejected
abandoned
```

Invalid jumps fail closed. A batch cannot move directly from `planned` to `closed`. Terminal states cannot leave terminal state.

Candidate-bearing states require a candidate channel. Rebuilt batches cannot rebuild from themselves. Supersession edges cannot duplicate batch IDs.

## Operation lifecycle

Allowed operation states:

```text
planned
running
blocked
completed
rejected
abandoned
```

Blocked operations require `blocked_reason`. Rejected operations require `rejection_reason`. Completed and abandoned operations cannot carry blocked or rejection reasons.

Operation kinds:

```text
source_review
candidate_build
release_comparison
production_promotion
rollback
retention_review
closeout
```

Only `production_promotion` and `rollback` may request a production slot.

## Expected previous production

Every operation carries the exact expected previous production identity:

```text
release_id
manifest_sha256
pointer_sha256
checked_at
```

If observed production differs from expected production, the operation is stale and must be rejected before mutation.

## Mutation boundary

Planning operations keep the M12 no-write governance boundary:

```text
canonical_source_write_permitted: false
source_pr_creation_permitted: false
candidate_write_permitted: false
release_write_permitted: false
production_write_permitted: false
rollback_permitted: false
permanent_ledger_append_permitted: false
```

Production mutation operations are allowed only when:

- kind is `production_promotion` or `rollback`;
- `planning_only` is false;
- `requires_production_slot` is true;
- operation result governance explicitly permits release write, production write, and ledger append;
- later M13 slices acquire the single production mutation slot.

M13.1 only defines this declaration. It does not acquire or enforce an external lock.

## Evidence and replay

All request and result envelopes are stable JSON serializable. Exact replay produces the same IDs. Invalid IDs, duplicated artifacts, invalid timestamps, stale production identity, invalid transitions, and governance mismatches fail closed.

## Exit criteria for M13.1

- deterministic identity helpers;
- strict regex validation;
- batch and operation state transition validation;
- expected-previous production stale rejection;
- production slot key generation;
- planning-only no-write and mutation governance boundaries;
- tests for replay, invalid transitions, stale expected previous, mutation declaration, and forbidden network/mutation surface;
- exact-head CI, R2 Canary, and R2 Release Integration green.
