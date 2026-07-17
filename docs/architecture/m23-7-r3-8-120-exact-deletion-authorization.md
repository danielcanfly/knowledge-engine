# M23.7 R3.8.120 Exact Deletion Authorization

This record authorizes deletion of retained diagnostic Worker `knowledge-engine-r3-8-29589719171`.

The authorization is based on the worker-present recovery seal merged in PR #818 and the independent reconciliation merged in PR #819. It binds deletion to the exact observed Worker version and deployment identity sets returned by recovery probe run `29590293423`.

Authority is limited to deletion of this diagnostic Worker. It does not authorize production mutation, Qdrant mutation, R2 mutation, pointer mutation, source mutation, fresh observation, blocker clearance, parent closure, or M23.7 closure.

Bound identities:

- Observation run: `29589719171`
- Recovery run: `29590293423`
- Authorization SHA-256: `5b0e481381eb6bdf64c91fff0d3aeb3c846dc9fd25eb3f25b69733fd61a67072`
