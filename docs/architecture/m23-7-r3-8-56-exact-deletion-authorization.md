# M23.7 R3.8.56 Exact Deletion Authorization

This record authorizes deletion of two retained diagnostic Workers:

- `knowledge-engine-r3-8-29568576968`
- `knowledge-engine-r3-8-29568662778`

The authorization is based on the worker-present recovery seals merged in PR
#751 and the independent reconciliation merged in PR #753. It binds deletion to
the exact observed Worker version and deployment identity sets returned by
recovery probe runs `29569671523` and `29569675689`.

## Bound Evidence

### `knowledge-engine-r3-8-29568576968`

- Observation run: `29568576968`
- Recovery run: `29569671523`
- Recovery receipt SHA-256:
  `096ca1d0e6a74523b511d23c10c1b0054586579ce1de0c63e4ef888798844430`
- Evidence seal SHA-256:
  `526c62c49a7763122a8c9162bb75113fb48fe2df106770a71cde40183e5f3780`
- Independent reconciliation SHA-256:
  `6d4414d374867a65a3f6546edea8ef5d27afa181c12d29de3f9d8975f04e80b0`
- Authorization SHA-256:
  `e742ed635fe4ee8bd3926a0ee88d8245b72dc8adf7ce94a36da44245de3d899b`

### `knowledge-engine-r3-8-29568662778`

- Observation run: `29568662778`
- Recovery run: `29569675689`
- Recovery receipt SHA-256:
  `0adf0ae4da3e84e458de7ba4d20188ad41e76f7b92d18a2b576619d82e8576c7`
- Evidence seal SHA-256:
  `d21d83d9e8046f36c333a30ab709008ba606e4a46ad4f3b51396ce28271a2061`
- Independent reconciliation SHA-256:
  `6d4414d374867a65a3f6546edea8ef5d27afa181c12d29de3f9d8975f04e80b0`
- Authorization SHA-256:
  `6a4c008b64729bc98ad1f8a36d4229aca59da13047d0c3d312cf7414e6d42485`

## Scope

This PR creates the deletion authorization records only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, a committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
