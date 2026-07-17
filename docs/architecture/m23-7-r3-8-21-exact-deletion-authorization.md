# M23.7 R3.8.21 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29550965495`.

The authorization is based on the worker-present recovery seal merged in PR #665
and the independent reconciliation merged in PR #667. It binds the deletion to
the exact observed worker version and deployment identity sets.

## Bound Evidence

- Observation run: `29550965495`
- Recovery run: `29551723834`
- Recovery receipt SHA-256:
  `b9a16f9bf9f8959e01daf739c821b76a71eea5fdecb7f76ab76d601d6533a3c2`
- Evidence seal SHA-256:
  `308bc22893ff2fbf24ae3b2cf7030e30a9f7f0ade6c16912c42ab5d7510a608a`
- Independent reconciliation SHA-256:
  `5e5a49796be69f3686700a911358ac9d7f6fdfeab331941129631d6f957dbd24`
- Authorization SHA-256:
  `0e4d52f0e7f81a510242f2577a885a22556663475da30b168f2637c5b6426328`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
