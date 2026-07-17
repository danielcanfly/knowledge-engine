# M23.7 R3.8.38 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29558980092`.

The authorization is based on the worker-present recovery seal merged in PR #711
and the independent reconciliation merged in PR #713. It binds deletion to the
exact observed Worker version and deployment identity sets returned by recovery
probe run `29559298060`.

## Bound Evidence

- Observation run: `29558980092`
- Recovery run: `29559298060`
- Recovery receipt SHA-256:
  `939994463dd5aba84baf1d35afd01e575224d62652c1bc208b483f832c0196bf`
- Evidence seal SHA-256:
  `8631f092d07e0b898e55ff59124db987ddf585770fa8c3eff440b91f1aa752bc`
- Independent reconciliation SHA-256:
  `e4bc3c93894c0f205954d902837ef44d58392cc2b982ca1f16ee566e0b36649e`
- Authorization SHA-256:
  `5d84a62a092bae56348941b0a0171c9c35ce58ffcf7045688d0ac295c18fc939`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
