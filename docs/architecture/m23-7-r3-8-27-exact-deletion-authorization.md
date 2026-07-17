# M23.7 R3.8.27 Exact Deletion Authorization

## Worker knowledge-engine-r3-8-29610393567

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29610393567`.

The authorization is based on the worker-present recovery seal merged in PR #880
and the independent reconciliation merged in PR #881. It binds deletion to the
exact observed Worker version and deployment identity sets returned by recovery
probe run `29611245813`.

## Bound Evidence

- Observation run: `29610393567`
- Recovery run: `29611245813`
- Recovery receipt SHA-256:
  `679f8e2fbdaf0a139cdb5e360d4104523ea9257e2a9d3011573b49fbe02ca429`
- Evidence seal SHA-256:
  `3d8fc558375e7b27a6930cfa2490e045885b66f1b2e2ce80c0f45acbe68942a1`
- Independent reconciliation SHA-256:
  `b7a844c9ba2b401305b0ff46a970df28f3b8e8cac564be6168f2f5aee94c8b92`
- Authorization SHA-256:
  `9c397501ef57dc7e925c5a8a125fe6881c3ef47657df5d5846d47b6f004e5f16`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.

## Worker knowledge-engine-r3-8-29607698618

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29607698618`.

The authorization is based on the worker-present recovery seal merged in PR #871
and the independent reconciliation merged in PR #872. It binds deletion to the
exact observed Worker version and deployment identity sets returned by recovery
probe run `29608526669`.

## Bound Evidence

- Observation run: `29607698618`
- Recovery run: `29608526669`
- Recovery receipt SHA-256:
  `62432f713ec0de751505697ff5002b75431839195e61eba6e16d5c34a1a11f09`
- Evidence seal SHA-256:
  `fea02c64c22ff1682c91c207e432c922b562625c17c36015b5bb957b3b92cbe1`
- Independent reconciliation SHA-256:
  `acf9f1f230226c50e2d741b03670bc9c1a63448e45fa7a254888f87988d9b0f5`
- Authorization SHA-256:
  `1d3c6196f52f67021e7efd3a1e8a54620cea1e6252608848586a6dd31c3480df`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.

## Worker knowledge-engine-r3-8-29604923286

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29604923286`.

The authorization is based on the worker-present recovery seal merged in PR #862
and the independent reconciliation merged in PR #863. It binds deletion to the
exact observed Worker version and deployment identity sets returned by recovery
probe run `29605835592`.

## Bound Evidence

- Observation run: `29604923286`
- Recovery run: `29605835592`
- Recovery receipt SHA-256:
  `6a778e51cf82b2d50789d784adce66686bf2fe8e307a36a9377d5aeb0b35230f`
- Evidence seal SHA-256:
  `f14513676f6fdf10df67b81fc2086f9c96b94d838cd0e81e960ec81403894fa0`
- Independent reconciliation SHA-256:
  `7e0a805a69cc299e77e8c3eaf9f0dfd1e42c5d16a37501e4fe61edf20b29dad2`
- Authorization SHA-256:
  `d097309f1b6dc3cea071b28ebc02eb0cbbf5dd235e2811172e7f38329b7b3e27`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.

## Worker knowledge-engine-r3-8-29553221650

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29553221650`.

The authorization is based on the worker-present recovery seal merged in PR #683
and the independent reconciliation merged in PR #685. It binds deletion to the
exact observed Worker version and deployment identity sets returned by recovery
probe run `29555974732`.

## Bound Evidence

- Observation run: `29553221650`
- Recovery run: `29555974732`
- Recovery receipt SHA-256:
  `09d2bc430b4343bcd5ce03e89a718339336dcd40f8fcabc8022f444c36440ff1`
- Evidence seal SHA-256:
  `9a5e154c9129ec76077bf87553bfa95246a6f302db025382087e00623174ecae`
- Independent reconciliation SHA-256:
  `df251c9453bba0c83953c1698147a71b8bec7dd719d85e68033e81c3652de900`
- Authorization SHA-256:
  `174d38fa83cfa9ea7b1df1e859f0e459ab9eacd4e43f53b1b7fe3b543bd22445`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
