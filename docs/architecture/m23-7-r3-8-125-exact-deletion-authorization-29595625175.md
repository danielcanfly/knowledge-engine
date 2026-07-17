# M23.7 R3.8.125 Exact Deletion Authorization for 29595625175

This record authorizes deletion of retained diagnostic Worker `knowledge-engine-r3-8-29595625175`.

The authorization is based on the worker-present recovery seal merged in PR #832 and the independent reconciliation merged in PR #833. It binds deletion to the exact observed Worker version and deployment identity sets returned by recovery probe run `29595999331`.

Authority is limited to deletion of this diagnostic Worker. It does not authorize production mutation, Qdrant mutation, R2 mutation, pointer mutation, source mutation, fresh observation, blocker clearance, parent closure, or M23.7 closure.

Bound identities:

- Observation run: `29595625175`
- Recovery run: `29595999331`
- Authorization SHA-256: `6765a4b7b930ddbbca7aee8d4c67afdd72b4a6844edaa0ec27d438c27d935ce9`
