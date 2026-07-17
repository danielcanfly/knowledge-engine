# M23.7 R3.8.70 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic Worker
`knowledge-engine-r3-8-29574526665`.

The authorization is based on the worker-present recovery seal merged in PR
#768 and the independent reconciliation merged in PR #769. It binds deletion to
the exact observed Worker version and deployment identity sets returned by
recovery probe run `29574761599`.

## Bound Evidence

- Observation run: `29574526665`
- Recovery run: `29574761599`
- Recovery receipt SHA-256:
  `e83590dbbc24c4bfa4ae056eae91527158036ca73ab8b2347f972f04b000783d`
- Evidence seal SHA-256:
  `338f958242d49c0a7184a7a781dd92dd13acbf3ddddd6b8ce81a53ce135dbfa5`
- Independent reconciliation SHA-256:
  `ba8ca5dbecc9108164ecf920f54b459573e8b7911428f654fa5a0a8fdea91879`
- Authorization SHA-256:
  `504b56f94cc9901bd815a1390ac9f3faf4ec8c03bc5f7ccbe9c12cfaa4ef5077`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, a committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
