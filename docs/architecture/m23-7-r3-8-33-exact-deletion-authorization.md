# M23.7 R3.8.33 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic worker
`knowledge-engine-r3-8-29557251118`.

The authorization is based on the worker-present recovery seal merged in PR #697
and the independent reconciliation merged in PR #699. It binds deletion to the
exact observed Worker version and deployment identity sets returned by recovery
probe run `29557534438`.

## Bound Evidence

- Observation run: `29557251118`
- Recovery run: `29557534438`
- Recovery receipt SHA-256:
  `ca6ab820ad1aeefc9e4e28c3b628130dcdf521fec1298f2bb40a500f81af807c`
- Evidence seal SHA-256:
  `6c7fc5a09d1661e1cf7e412ebdc33dde7934237586e4d2335bd8847f782a51f0`
- Independent reconciliation SHA-256:
  `eab1bd2848e074941d9ce8df9cc21e3ff6e49561922d365045a394440e2d4ccc`
- Authorization SHA-256:
  `80dc77aefeb654f365027cc428b8af7ecbfbfe278dfa8ffb0a3060111a2154dd`

## Scope

This PR creates the deletion authorization record only. It does not execute
deletion and does not change production retrieval, Qdrant, R2, Source, pointer,
or blocker state.

Deletion execution remains gated by the separate remote-delete workflow with
exact main head, this committed authorization path, and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.
