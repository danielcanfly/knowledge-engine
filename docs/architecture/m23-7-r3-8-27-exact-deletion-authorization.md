# M23.7 R3.8.27 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29553221650`.

The authorization is based on the worker-present recovery seal merged in PR #683
and the independent reconciliation merged in PR #685. It binds deletion to the
exact observed Worker version and deployment identity sets returned by recovery
probe run `29555974732`.

## Bound Evidence

- Observation run: `29553221650`
- Recovery run: `29555974732`
- Recovery receipt SHA-256:
  `09d2bc430b4343bcd5ce03e89a718339336dcd40f8fcabc8022f444c36440ff1`
- Evidence seal SHA-256:
  `9a5e154c9129ec76077bf87553bfa95246a6f302db025382087e00623174ecae`
- Independent reconciliation SHA-256:
  `df251c9453bba0c83953c1698147a71b8bec7dd719d85e68033e81c3652de900`
- Authorization SHA-256:
  `174d38fa83cfa9ea7b1df1e859f0e459ab9eacd4e43f53b1b7fe3b543bd22445`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
