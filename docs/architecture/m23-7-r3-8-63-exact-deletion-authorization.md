# M23.7 R3.8.63 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic Worker
`knowledge-engine-r3-8-29572790495`.

The authorization is based on the worker-present recovery seal merged in PR
#761 and the independent reconciliation merged in PR #762. It binds deletion to
the exact observed Worker version and deployment identity sets returned by
recovery probe run `29573139584`.

## Bound Evidence

- Observation run: `29572790495`
- Recovery run: `29573139584`
- Recovery receipt SHA-256:
  `3402c7e570de6182b2c12841c51293eac01524568bcf680a751d98b655dbdb86`
- Evidence seal SHA-256:
  `143d048ed859c529f45d71a867426cb4a71c564a8b05ac81f67ab2324dbc9c7a`
- Independent reconciliation SHA-256:
  `8f0fedba406dde3e3620c3a3781674fbfc86e19f38631c80f1cc7644bc8cdf09`
- Authorization SHA-256:
  `51a89f9957b94f97ddcb1a6253dda96e0d43728734f84806506839ee1e2ba923`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, a committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
