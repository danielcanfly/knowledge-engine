# M23.7 R3.8.105 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic Worker
`knowledge-engine-r3-8-29584764087`.

The authorization is based on the worker-present recovery seal merged in PR
#803 and the independent reconciliation merged in PR #804. It binds deletion to
the exact observed Worker version and deployment identity sets returned by
recovery probe run `29585094990`.

## Bound Evidence

- Observation run: `29584764087`
- Recovery run: `29585094990`
- Recovery receipt SHA-256:
  `3ed02050d849e0deb32f7a32373cd0ee3ae12bb1fc317a76625187762209a568`
- Evidence seal SHA-256:
  `d27d145db5c5d3bac6f14ec9b5726acfbdf7b66fad07c15fff5256c281052e0d`
- Independent reconciliation SHA-256:
  `27ac1d722dfbbec558d15911ffc187afe3987fdb0b5e1f728d33226693857fa7`
- Authorization SHA-256:
  `f4e3276976db3df3c02d6c1f2cc1d7c2afd9dac563c5a404c1e96665c6b98ef7`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, a committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
