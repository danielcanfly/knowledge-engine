# M23.7 R3.8.91 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic Worker
`knowledge-engine-r3-8-29579965754`.

The authorization is based on the worker-present recovery seal merged in PR
#789 and the independent reconciliation merged in PR #790. It binds deletion to
the exact observed Worker version and deployment identity sets returned by
recovery probe run `29580277257`.

## Bound Evidence

- Observation run: `29579965754`
- Recovery run: `29580277257`
- Recovery receipt SHA-256:
  `b75d362eb702ce59cf42e62b2e662c24f05cc09773f50724dd4f299c76ec6874`
- Evidence seal SHA-256:
  `fac5b1afb1df3c998b18da4f259d80ab34328c7752165dba7c4608d0e68965ff`
- Independent reconciliation SHA-256:
  `4453d2012da5c2a6ce7730c357be1ddb0316c09bb85f91024e3936acfd978b4a`
- Authorization SHA-256:
  `43e90df396346ac6e9ab7352b188f02f624bb1c010122ba8d631478baabe6936`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, a committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
