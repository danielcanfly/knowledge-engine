# M23.7 R3.8.125 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic Worker `knowledge-engine-r3-8-29592583765`.

The authorization is based on the worker-present recovery seal merged in PR #825 and the independent reconciliation merged in PR #826. It binds deletion to the exact observed Worker version and deployment identity sets returned by recovery probe run `29592989012`.

Authority is limited to deletion of this diagnostic Worker. It does not authorize production mutation, Qdrant mutation, R2 mutation, pointer mutation, source mutation, fresh observation, blocker clearance, parent closure, or M23.7 closure.

Bound identities:

- Observation run: `29592583765`
- Recovery run: `29592989012`
- Authorization SHA-256: `2724f1ebd4fb92cc66f9c10540bbf084f2361ff98deaee97e10521821bee284d`
