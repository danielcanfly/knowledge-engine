# M23.7 R3.8.19 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29548837457`.

The authorization is based on the worker-present recovery seal merged in PR #651
and the independent reconciliation merged in PR #653. It binds the deletion to
the exact observed worker version and deployment identity sets.

## Bound Evidence

- Observation run: `29548837457`
- Recovery run: `29549300979`
- Recovery receipt SHA-256:
  `caa9e4c1700add6553a43b1a90f1e4021bfef24b3820a9770458e14fab4856af`
- Evidence seal SHA-256:
  `7e85dd22facfe3051589181e4eacece578f2075af3b4421196bcff60f051a59f`
- Independent reconciliation SHA-256:
  `d103787ab87fbd08c42691c7d3684a0456fc794f3098048057787a407c990448`
- Authorization SHA-256:
  `ef531bcbe3a288672aa0f08fe1d46e41f73031b046c33846fa9760fe659900a7`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
