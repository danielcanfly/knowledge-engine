# M25 Admission State Machine

The machine-readable transition graph is `pilot/m25/m25-1-state-machine.json`.

The state machine spans planning through candidate adoption, but each M25 stage may exercise only
the subset it is authorised to use. Transitions are adjacent, revision-checked, digest-bound, and
fail closed.

## Critical gates

- `snapshotted` requires an immutable M10 snapshot and acquisition evidence.
- `normalized` requires a derivative reference and exact digest.
- `candidate_ready` keeps candidate-only authority.
- `resolution_ready` requires exact Source and Foundation identity.
- `review_pending` cannot advance without complete item-level Daniel decisions.
- `source_pr_prepared` and `source_pr_opened` require stale-decision and path-collision checks.
- `adopted_candidate_release` requires an authorised exact-head Source merge and candidate release
  rebuild.
- Production promotion is deliberately outside this item state machine.

Rejected, deferred, duplicate, blocked, and rolled-back items are terminal. Terminal items cannot
silently re-enter; a new plan and identity are required.
