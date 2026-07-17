# M23.7 R3.8.17 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29546336917`.

The authorization is based on the worker-present recovery seal merged in PR #635
and the independent reconciliation merged in PR #637. It binds the deletion to
the exact observed worker version and deployment identity sets.

## Bound Evidence

- Observation run: `29546336917`
- Recovery run: `29546964620`
- Recovery receipt SHA-256:
  `2262aaf3dacf7d964b7dc07f408aa391b5ab28f977bb7d5a17911221a4b28c55`
- Evidence seal SHA-256:
  `c7c98843d4016aa32c34b5793d7524b8f651c426d20dde104ea7d8795d6d7ca5`
- Independent reconciliation SHA-256:
  `6b806afa48f5faafd4c04f5cec261a8476414d76a407703911e891374abef725`
- Authorization SHA-256:
  `db28df9b60264bb55b4e26ceb4bdb5eabdb8a60e35ce80c82200c328406ae2df`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
