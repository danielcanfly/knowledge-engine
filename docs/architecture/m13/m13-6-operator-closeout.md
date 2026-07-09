# M13.6 Operator Status, Lookup and Closeout Tools

Status: implementation candidate  
Parent: #173  
Slice: #185  
Depends on: M13.5 issue #183 / PR #184  
Engine baseline: `45203ef90c1afbd90f17216e2070808743ea7fd4`

## Purpose

M13.6 removes the need for operators to reconstruct multi-batch state from scattered object keys, workflow logs, and memory. It provides deterministic status, lookup, audit, stale-work, ledger-summary, and closeout tools over the exact M13 registry and coordinator evidence.

The slice does not mutate canonical Source, create a candidate or release, write the production pointer, execute rollback, delete retained objects, call GitHub, or append permanent ledger issue #30.

## Executable surface

The `knowledge-m13` CLI exposes:

```text
knowledge-m13 status
knowledge-m13 lookup
knowledge-m13 audit
knowledge-m13 stale-report
knowledge-m13 ledger-summary
knowledge-m13 closeout
```

All commands read the configured `ObjectStore`. Output is stable, sorted JSON. No command accepts a URL, shell expression, arbitrary object prefix, or unbounded search query.

## Status

`status` derives one coherent operator snapshot from:

- the M13 registry head;
- every exact current batch snapshot and validated event chain;
- the exact production pointer and referenced manifest;
- the candidate-concurrency head;
- the current production lease;
- the existing lifecycle planner.

For each batch it reports state, versions, Source identity, candidate channel, expected-previous production, event and operation counts, next action, blockers, terminal state, and current snapshot key.

Status performs no writes and never treats a secondary cache as truth.

## Exact identity lookup

`lookup` accepts one bounded exact identity. Supported identities include:

- `mbatch_...` batch;
- `mop_...` operation;
- `candidate-...` channel;
- immutable release ID;
- `mcompare_...` release comparison;
- `mcslot_...` candidate slot;
- `mlease_...` production lease;
- `mpermit_...` production permit;
- `mauth_...` commit authorization;
- `mcomplete_...` production completion;
- `mclose_...` closeout.

Batch and operation lookup use the exact registry head and snapshot references. Direct immutable identities map only to their fixed object namespaces. There is no fuzzy lookup or `latest` alias.

## Integrity audit

`audit` validates the current control plane without modifying it:

- registry head schema and version;
- each current snapshot and full event hash chain;
- head summary equality with the referenced snapshot;
- operation-summary identities and referenced operation objects;
- production pointer, manifest hash, and release identity;
- candidate slot summaries and immutable lease artifacts;
- current production lease and every referenced permit, authorization, completion, release, or recovery artifact.

Failures are aggregated into deterministic issue records. Missing, malformed, mismatched, or corrupt evidence makes the audit fail closed.

## Stale report

`stale-report` detects operator action requirements, including:

- a nonterminal batch whose expected-previous production is no longer current;
- expired candidate slots;
- expired active, permitted, or commit-authorized production leases;
- a promoting batch without the matching current lease;
- a released lease without completion evidence;
- promotion completion that is ready for closeout;
- completed closeout evidence while the batch is not closed;
- a production lease whose batch is absent from the registry.

The report distinguishes blockers from action-required findings and does not perform recovery automatically.

## Ledger summary

`ledger-summary` derives an append-ready operational summary from registry operation evidence. It reports promotion and closeout counts, exact batch and release lineage, ledger references already bound into closeout, and closed batches missing ledger references.

It explicitly reports `ledger_append_performed: false`. Appending issue #30 remains a separate human-governed action.

## Atomic closeout

M13.6 closes one batch only when all preconditions are exact:

- the batch is `promoting` at the expected batch version;
- the registry is at the expected registry version;
- the current production lease belongs to the batch and is `released`;
- the lease names immutable production-completion evidence;
- completion batch and promotion-operation identities match the lease;
- completion expected-previous production matches the batch seed;
- completion resulting production matches the exact current production pointer;
- resulting production differs from expected previous;
- completed release-comparison evidence exists;
- explicit unique ledger references are supplied.

One registry-head compare-and-swap makes the following visible together:

- production-promotion summary changes from `running` to `completed`;
- completed `closeout` operation result is added;
- immutable closeout evidence is written;
- one `batch_closed` event is appended;
- one new batch snapshot records `promoting → closed`.

Immutable evidence, operation, event, and snapshot objects may exist safely before the head CAS. If the CAS loses a race, exact replay is accepted only when the visible registry state and immutable bytes match the same closeout identity. Divergent replay fails as an identity collision.

## Closeout evidence

Closeout evidence is stored at:

```text
m13/v2/closeouts/{closeout_id}.json
```

The identity covers:

- batch, actor, timestamp, and expected versions;
- lease ID and generation;
- promotion operation ID;
- completion key and SHA-256;
- expected-previous and resulting production identities;
- explicit ledger references.

The closeout operation result remains in the existing batch operation namespace. Closeout evidence is classified as permanent M13 evidence.

## Governance boundary

M13.6 closeout changes only M13 registry state and immutable M13 evidence. It records:

```text
source_write_performed: false
production_write_performed: false
rollback_performed: false
ledger_append_performed: false
```

The production coordinator remains the only mechanism that may mutate production. Closeout cannot manufacture completion evidence or infer a production result.

## Exit criteria

- deterministic status across registry, candidate slots, production and lease state;
- exact bounded lookup for every M13 operator identity;
- fail-closed integrity audit;
- deterministic stale-work report;
- ledger summary with missing-reference detection and no append capability;
- exact atomic closeout with replay and collision protection;
- CLI coverage and non-network surface enforcement;
- exact-head CI, R2 Canary, and R2 Release Integration green.
