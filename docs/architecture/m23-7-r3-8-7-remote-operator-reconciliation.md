# M23.7-R3.8.7 Remote Operator Independent Reconciliation

## Reconciled implementation

- issue: #534
- PR: #535
- accepted head: `9cfbbb4a942b265ab4b81934e54262adf7e4687a`
- squash merge: `771538d3b95fccefc3f32bd568770e08ce3552ac`
- remote operator contract: `97a6b71aa3093cdd57788f1c189f41592a85106952284f476ca2fb4c985529e2`
- reconciliation digest: `12dbb326e9f76c6541016561789f34020faf1f2978c24660882c7b9c29c3a103`

The nine implementation files match PR #535. Exact-head runs succeeded for the
remote-operator contract, global CI, M17 and M18.

## Independent conclusions

The migration is complete as an execution platform change. R3.8 no longer supports
user-operated local Terminal packs. The accepted observation path is a manual GitHub
Actions workflow using environment `m23-r3-diagnostic`, exact main head identity,
private read-only R2 evidence, pinned Wrangler and a unique Worker name derived from
the GitHub run ID.

The unique-name strategy removes the fixed-name absence and overwrite problem that
blocked all local attempts. A workflow rerun is rejected before mutation. Complete
results retain the exact Worker for evidence seal and independent reconciliation.
Deletion is a separate manual workflow and requires a committed authorization binding
the observation receipt, evidence seal and reconciliation.

## What has not happened

This reconciliation does not claim that the remote observation ran. During the
implementation and CI lifecycle:

- no diagnostic Worker was deployed;
- no Worker secret was written;
- no private R2 evidence object was read;
- no Qdrant read or mutation was dispatched;
- no latency or quality blocker was cleared.

The unchanged Worker-internal shadow maximum remains `1200 ms`. Production retrieval
remains lexical. `blocked_pending_retrieval_quality` and
`blocked_pending_latency` remain active. Issues #520 and #474 remain open.

## Next legal gate

1. Upload the exact frozen evidence ZIP to the governed private R2 diagnostic key.
2. Configure the `m23-r3-diagnostic` GitHub environment secrets and variables.
3. Dispatch `M23.7 R3.8 Remote Observation` once from exact main head.
4. Download and independently validate the resulting Actions artifact.
5. Seal and reconcile the live receipt before any blocker decision or Worker deletion.
