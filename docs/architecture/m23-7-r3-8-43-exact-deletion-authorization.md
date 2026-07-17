# M23.7 R3.8.43 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29561411876`.

The authorization is based on the worker-present recovery seal merged in PR #725
and the independent reconciliation merged in PR #727. It binds deletion to the
exact observed Worker version and deployment identity sets returned by recovery
probe run `29561818934`.

## Bound Evidence

- Observation run: `29561411876`
- Recovery run: `29561818934`
- Recovery receipt SHA-256:
  `58987b1b6884eaa5eedf7f7678860bfa1ca08de384ef40e19c1f8d84b98f2af1`
- Evidence seal SHA-256:
  `035404b5d316a1a6c8e484ecaccf3c81fa4aa317418fdb0eaf8fb98342660730`
- Independent reconciliation SHA-256:
  `fd5d7d83c4e733256e71e6f8d2707961139401fa4b870e55bbc530adedf973b8`
- Authorization SHA-256:
  `48c2c40f2b13f0fcffb00dfd2c2b01e7ec436b5c9a517102858c3af1f441e944`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
