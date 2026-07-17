# M23.7 R3.8.112 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic Worker `knowledge-engine-r3-8-29587264678`.

The authorization is based on the worker-present recovery seal merged in PR #810 and the independent reconciliation merged in PR #811. It binds deletion to the exact observed Worker version and deployment identity sets returned by recovery probe run `29587564980`.

## Bound Evidence

- Observation run: `29587264678`
- Recovery run: `29587564980`
- Recovery receipt SHA-256:
  `eaadc828b631564e0a51dd434572afde8824851f71a87ed5e0e2d8444bf2ad57`
- Evidence seal SHA-256:
  `5a3e9b01940acb8b453f4cd3ebfd8622897a1dab9a1f897f1e67103a2480555f`
- Independent reconciliation SHA-256:
  `0694d6bcf83051ccd7b0aa7e95c09d73426977a249188e0807d272014e2e52ef`
- Authorization SHA-256:
  `3bdfdea12920380e5dc67f968f86314214de5c9114a30b485b026ea897045a52`

## Scope

This PR creates the deletion authorization record only. It does not execute deletion and does not change production retrieval, Qdrant, R2, Source, pointer, or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with exact main head, a committed authorization path, and confirmation `DELETE_RECONCILED_R3_8_WORKER`.
