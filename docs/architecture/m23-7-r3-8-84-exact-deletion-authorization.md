# M23.7 R3.8.84 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic Worker
`knowledge-engine-r3-8-29578234650`.

The authorization is based on the worker-present recovery seal merged in PR
#782 and the independent reconciliation merged in PR #783. It binds deletion to
the exact observed Worker version and deployment identity sets returned by
recovery probe run `29578467800`.

## Bound Evidence

- Observation run: `29578234650`
- Recovery run: `29578467800`
- Recovery receipt SHA-256:
  `ba104a12791c2123643b0a0ae604465438daa0aee1024963bfc1034f02e93c80`
- Evidence seal SHA-256:
  `481e94cd91a7eb0e8a0fcb11fe95c2095b41c22de9412af3d7eb637804f61f8d`
- Independent reconciliation SHA-256:
  `7f74a726c1af0ba5054ec23129b122cdb92df38e392d6ed5ac87c72d71546d54`
- Authorization SHA-256:
  `3b06ef148bb5663269bf1005b278404f60ab98f1f8919af09c2ce8f025264cfd`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, a committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
