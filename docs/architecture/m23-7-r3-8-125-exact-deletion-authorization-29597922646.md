# M23.7 R3.8.125 Exact Deletion Authorization for 29597922646

This record authorizes deletion of retained diagnostic Worker `knowledge-engine-r3-8-29597922646`.

The authorization is based on the worker-present recovery seal merged in PR #839 and the independent reconciliation merged in PR #840. It binds deletion to the exact observed Worker version and deployment identity sets returned by recovery probe run `29598351528`.

Authority is limited to deletion of this diagnostic Worker. It does not authorize production mutation, Qdrant mutation, R2 mutation, pointer mutation, source mutation, fresh observation, blocker clearance, parent closure, or M23.7 closure.

Bound identities:

- Observation run: `29597922646`
- Recovery run: `29598351528`
- Authorization SHA-256: `dc0891b17aac7e14c4984563d989c7d0050dd4d84e889da246bfb28395d5203e`
