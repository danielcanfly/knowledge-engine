# M25.7 Governed Source PR Executor

## Current status

Technical implementation candidate status:

`m25_7_executor_implemented_awaiting_daniel_item_decisions`

M25.7 enters only from accepted M25.6 closure seal
`134edbcfa3841321d3ea1106d35243b866cb6913`. The implementation may coexist with later M26
history, but it may not weaken or rewrite the M25.6 evidence and authority chain.

## Non-delegable knowledge authority

The executor never turns model output, browser acceptance evidence, reviewer confidence or a general
instruction to continue into canonical knowledge. A live plan requires all of the following:

1. the exact accepted M25.6 batch;
2. a complete terminal audit export with a valid immutable decision chain;
3. a live Source baseline bound to the exact Source commit and every file digest;
4. a Daniel item-authority envelope covering every review item;
5. exact approved replacement bytes for every write operation.

The six `browser-reviewer` journeys from M25.6 are product acceptance evidence only. They are rejected
as live knowledge authority.

## Two-key execution model

### Key 1: item authority

The item-authority envelope binds:

- Daniel's GitHub authority comment identity;
- exact M25.6 batch and audit digests;
- exact decision and review-state digests for every item;
- the exact Source repository, base commit and baseline manifest;
- exact create, replace, delete or no-write operations;
- exact approved UTF-8 bytes and SHA-256 identities.

A complete item-authority envelope permits only deterministic plan preparation. It does not permit a
Source write or GitHub pull request.

### Key 2: exact plan approval

After the deterministic plan is produced, Daniel must separately approve its exact `plan_sha256`,
Source base and branch name. Only that second authority envelope can produce an opening receipt that
permits a Source branch write and draft Source PR creation. It never permits merge.

M25.8 remains the separate exact-head Source PR merge gate.

## Fail-closed controls

The executor rejects:

- incomplete, pending or deferred decision populations;
- stale batch, review-state, decision-chain or audit identities;
- stale Source base, manifest or existing-file digest;
- browser or synthetic actors in live mode;
- unapproved content bytes or content-digest drift;
- unsafe absolute, traversal or non-Source paths;
- create collisions, stale replace/delete operations and cross-item path collisions;
- duplicate operation or item identities;
- rejected decisions that attempt a Source write;
- test-only plans presented for live Source PR opening;
- any approval that also claims merge, release or production authority.

## Test-only adapter

`knowledge-m25-source-pr materialize-test` can materialize only `test_only` plans into an isolated
local directory. It refuses live plans and produces a receipt that explicitly denies live Source write
and GitHub PR creation.

## CLI

```text
knowledge-m25-source-pr prepare
knowledge-m25-source-pr authorize-opening
knowledge-m25-source-pr materialize-test
knowledge-m25-source-pr status
```

## Preserved boundary

The knowledge-engine implementation PR performs no Source mutation, Source PR creation, canonical
knowledge decision, Foundation or release mutation, production pointer change, R2 production or
Qdrant mutation, semantic/hybrid serving, production answer serving, large-scale ingestion or M25.8
authorization.
