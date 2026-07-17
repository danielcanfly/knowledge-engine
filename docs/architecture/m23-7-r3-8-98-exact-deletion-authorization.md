# M23.7 R3.8.98 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic Worker
`knowledge-engine-r3-8-29582316388`.

The authorization is based on the worker-present recovery seal merged in PR
#796 and the independent reconciliation merged in PR #797. It binds deletion to
the exact observed Worker version and deployment identity sets returned by
recovery probe run `29582686914`.

## Bound Evidence

- Observation run: `29582316388`
- Recovery run: `29582686914`
- Recovery receipt SHA-256:
  `b9497142ad9daf744488e433364d3e2e97b2f1604304e43f2b3263bdbe75b9ff`
- Evidence seal SHA-256:
  `039e0dfd0eb9dd79fbc3b5e490daf8c667070232c196ea996266a1036db41214`
- Independent reconciliation SHA-256:
  `a79cb6968c5399a00977e4a4d560ee3e45a70c908fcbb6e9f36af1d9383842e0`
- Authorization SHA-256:
  `c54ed215a2cff8743462a52b44b6ec5a4e2096c4ecb4393e173a0c1ca4e81338`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, a committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
