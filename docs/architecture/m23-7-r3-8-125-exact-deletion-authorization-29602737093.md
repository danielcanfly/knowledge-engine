# M23.7 R3.8.125 Exact Deletion Authorization for 29602737093

This record authorizes deletion of retained diagnostic Worker `knowledge-engine-r3-8-29602737093`.

The authorization is based on the worker-present recovery seal merged in PR #853 and the independent reconciliation merged in PR #854. It binds deletion to the exact observed Worker version and deployment identity sets returned by recovery probe run `29603119791`.

Authority is limited to deletion of this diagnostic Worker. It does not authorize production mutation, Qdrant mutation, R2 mutation, pointer mutation, source mutation, fresh observation, blocker clearance, parent closure, or M23.7 closure.

Bound identities:

- Observation run: `29602737093`
- Recovery run: `29603119791`
- Authorization SHA-256: `a17f1bc4389734992c41ba71cbf1adcfb969827900a451a8eb061979c826558e`
