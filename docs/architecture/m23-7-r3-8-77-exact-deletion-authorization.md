# M23.7 R3.8.77 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic Worker
`knowledge-engine-r3-8-29576200306`.

The authorization is based on the worker-present recovery seal merged in PR
#775 and the independent reconciliation merged in PR #776. It binds deletion to
the exact observed Worker version and deployment identity sets returned by
recovery probe run `29576499744`.

## Bound Evidence

- Observation run: `29576200306`
- Recovery run: `29576499744`
- Recovery receipt SHA-256:
  `b0f400aed39cb7bf17a31e4b23a84ca5673dbf5d30d3f85d77e2221626a0da86`
- Evidence seal SHA-256:
  `9e10929ccc8911295a4010a25793bcb69db3879c237a1c88a665ad09e3b12cdb`
- Independent reconciliation SHA-256:
  `97c7868baa41299fa2c3068b61679ea234b9a9c890cfeda81daa7dafccc4a90b`
- Authorization SHA-256:
  `aab6d5ba89e9516ffb89c1d670c807f1796383251d944371291af829fd23678e`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, a committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
