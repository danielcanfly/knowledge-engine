# M13.2 Batch Registry and Lifecycle Planner

Status: implementation candidate  
Parent: #173  
Slice: #176  
Depends on: M13.1 issue #174 / PR #175  
Engine baseline: `e111974a3676822cd086a4ac37e50e1f3026af18`

## Purpose

M13.2 creates the governed control-plane registry for multiple batches. It records immutable batch history, maintains one compare-and-swap protected current index, and derives the next safe lifecycle action without performing candidate, Source, release, production, rollback, retention deletion, or permanent-ledger mutations.

## Storage model

The registry separates immutable history from mutable lookup state.

```text
m13/v1/registry/head.json
m13/v1/batches/{batch_id}/events/{version}-{event_sha256}.json
m13/v1/batches/{batch_id}/snapshots/{version}-{request_id}.json
m13/v1/batches/{batch_id}/operations/{operation_id}/result.json
```

`head.json` is the only mutable object. It is updated using object-store compare-and-swap through the previous ETag. Every lifecycle event, batch snapshot, and operation result is immutable.

A CAS conflict fails with `M13_REGISTRY_CONFLICT`. Immutable artifacts written before a failed CAS remain safe orphan evidence and can be reused by an exact retry.

## Registration

A new batch must start in `planned`. Registration writes:

1. a deterministic `batch_registered` event;
2. immutable batch snapshot version 1;
3. one registry-head update.

Exact replay is idempotent. A batch identity that resolves to divergent registered origin evidence fails closed.

## Lifecycle events

Lifecycle events form an adjacent hash chain:

```text
batch_registered
-> batch_transitioned
-> batch_transitioned
...
```

Each event records:

- exact batch and batch version;
- from-state and to-state;
- actor and UTC timestamp;
- transition request identity;
- previous event hash;
- exact snapshot reference;
- explicit no-Source, no-production, and no-ledger mutation declarations.

Lookup validates every event hash, key suffix, batch identity, adjacent version, previous-event hash, current-event hash, and snapshot version.

## Operation evidence

M13 operation results are immutable and attached to the current batch snapshot as deterministic summaries. A summary records operation ID, kind, state, completion time, evidence count, and immutable object key.

New operation evidence is rejected when:

- the batch is terminal;
- the operation points to another batch;
- expected-previous production differs from the batch seed;
- the registry version is stale;
- the same operation ID resolves to divergent bytes.

## Transition prerequisites

The registry refuses state-only progress without evidence:

```text
planned -> reviewing_source
  requires completed source_review evidence

reviewing_source -> candidate_ready
  requires completed candidate_build evidence
  requires a candidate channel

candidate_ready -> awaiting_production_slot
  requires completed release_comparison evidence

awaiting_production_slot -> promoting
  rejected by M13.2
  requires the M13.3 concurrency coordinator
```

Rejected and abandoned terminal transitions remain available from the M13.1 state machine. Candidate channels become immutable once assigned.

## Lifecycle planner

The planner is deterministic and produces one `mplan_` identity from:

- exact batch snapshot and version;
- observed production identity;
- actor and planning timestamp;
- candidate-channel input when relevant;
- completed operation summaries;
- derived blockers and next action.

The planner can emit planning-only M13 operation requests for:

- source review;
- candidate build;
- release comparison.

It never emits a production mutation request. At `awaiting_production_slot`, it returns `m13_3_coordinator_required`. At `promoting`, it returns `production_mutation_in_progress`.

A stale expected-previous production identity blocks the plan and suppresses operation-request generation.

## Registry queries

M13.2 provides deterministic:

- batch lookup with full evidence validation;
- sorted batch listing, optionally filtered by state;
- registry status with exact version and state counts.

These are library surfaces. Operator CLI and external status commands belong to M13.6.

## Governance

All M13.2 artifacts carry the existing no-write boundary:

```text
canonical_source_write_permitted: false
source_pr_creation_permitted: false
candidate_write_permitted: false
release_write_permitted: false
production_write_permitted: false
rollback_permitted: false
permanent_ledger_append_permitted: false
```

The registry writes only M13 control-plane artifacts and its CAS-protected head.

## Exit criteria

- idempotent batch registration;
- immutable snapshots, operations, and hash-linked events;
- CAS-protected registry head;
- deterministic lookup, listing, and status;
- evidence-gated transitions;
- stale registry and batch-version rejection;
- stale expected-previous production detection;
- deterministic lifecycle plans and planning-only operation requests;
- M13.3 boundary for production mutation;
- tamper, terminal-state, collision, replay, and CAS-conflict tests;
- exact-head CI, R2 Canary, and R2 Release Integration green.
