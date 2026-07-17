# M23.7 R3.8.125 Exact Deletion Authorization for 29600412694

This record authorizes deletion of retained diagnostic Worker `knowledge-engine-r3-8-29600412694`.

The authorization is based on the worker-present recovery seal merged in PR #846 and the independent reconciliation merged in PR #847. It binds deletion to the exact observed Worker version and deployment identity sets returned by recovery probe run `29600907404`.

Authority is limited to deletion of this diagnostic Worker. It does not authorize production mutation, Qdrant mutation, R2 mutation, pointer mutation, source mutation, fresh observation, blocker clearance, parent closure, or M23.7 closure.

Bound identities:

- Observation run: `29600412694`
- Recovery run: `29600907404`
- Authorization SHA-256: `6faf0b0f0cd5c4e4580a73fa4f2083b78c24035a61c90dea3b2a419b70efe5bf`
