# M23.7-R3.8.10 Exact Orphan Worker Deletion Authorization

## Authorized target

```text
knowledge-engine-r3-8-29506217284
```

The committed v2 authorization binds observation run `29506217284`, recovery run
`29513606007`, the successful recovery receipt, Worker-present evidence seal,
independent deletion-schema reconciliation, four Worker version IDs and four
Worker deployment IDs.

Authorization digest:

```text
0617d5351bb6c72121ac9e9fa12d2ad2de34568ecb62041826bf932a9d7cce19
```

## Execution boundary

The record authorizes deletion of only the exact diagnostic Worker above through
`M23.7 R3.8 Remote Worker Deletion`. It does not authorize production, Qdrant, R2,
pointer or Source mutation.

The authorization record itself performs no deletion. Execution requires an exact
main head, the committed authorization path and confirmation
`DELETE_RECONCILED_R3_8_WORKER`.

After deletion, the resulting evidence must be sealed and independently reconciled
before any parent closure or blocker decision. Production remains lexical and both
blockers remain active.
