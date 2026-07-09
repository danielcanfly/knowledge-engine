# M13.3 Concurrency Coordinator and Single Production Mutation

Status: implementation candidate  
Parent: #173  
Slice: #178  
Depends on: M13.2 issue #176 / PR #177  
Engine baseline: `45c2d8c8f3c71260acad1dc8b349ae05a238d247`

## Purpose

M13.3 adds deterministic concurrency control for multi-batch operations. Candidate builds may run with configured bounded capacity. Production mutation remains one global lane protected by object-store compare-and-swap, a monotonic generation, and a fencing token.

This slice controls admission and authorization. It does not create a release, write the production pointer, roll back production, modify Source, delete retention targets, or append the permanent ledger.

## Implementation structure

The coordinator is split by responsibility:

```text
m13_coordination_common.py       identities, typed envelopes, time and CAS helpers
m13_candidate_coordinator.py     bounded candidate slot pool
m13_production_lease.py          global production lease and recovery
m13_production_permit.py         mutation permit and promoting transition
m13_production_commit.py         commit authorization, validation and completion
m13_production_mutation.py       compatibility-only re-export facade
m13_coordinator_v2.py            stable public facade
```

The split keeps each concurrency boundary independently reviewable while preserving one public API. The compatibility module contains no implementation logic.

## Candidate build coordination

Candidate work uses a bounded slot head:

```text
m13/v2/concurrency/candidate/head.json
m13/v2/concurrency/candidate/leases/{slot_id}.json
m13/v2/concurrency/candidate/releases/{slot_id}.json
m13/v2/concurrency/candidate/recoveries/{recovery_id}.json
```

The head contains fixed capacity, a monotonic head version, and active slot summaries. Updates use compare-and-swap against the exact prior ETag.

Candidate admission requires:

- a planning-only `candidate_build` operation request;
- a registered batch in `reviewing_source`;
- expected-previous production equal to the batch seed;
- a non-empty holder identity;
- a valid UTC acquisition and expiry window;
- free capacity.

Exact replay returns the same slot. Expired slots continue occupying capacity until an explicit recovery action writes immutable evidence and updates the head. There is no silent expiry deletion.

## Production mutation lane

Production coordination uses one mutable lease object and immutable evidence objects:

```text
m13/v2/concurrency/production/lease.json
m13/v2/concurrency/production/acquisitions/{lease_id}.json
m13/v2/concurrency/production/renewals/{renewal_id}.json
m13/v2/concurrency/production/permits/{permit_id}.json
m13/v2/concurrency/production/transitions/{marker_id}.json
m13/v2/concurrency/production/authorizations/{authorization_id}.json
m13/v2/concurrency/production/completions/{completion_id}.json
m13/v2/concurrency/production/releases/{release_id}.json
m13/v2/concurrency/production/recoveries/{recovery_id}.json
```

Only `lease.json` is mutable. Every update uses compare-and-swap. Immutable evidence written before a failed CAS is safe orphan evidence and can be reused by exact replay.

## Lease lifecycle

```text
active
  -> permit_issued
  -> commit_authorized
  -> released

active / permit_issued
  -> recovered, only after explicit expiry recovery
```

A lease contains:

- deterministic lease identity;
- monotonic generation;
- fencing token derived from generation and predecessor;
- exact batch and operation identities;
- exact candidate channel;
- exact registry and batch versions observed at acquisition;
- exact expected-previous production identity;
- holder, acquisition time, expiry, and immutable evidence keys.

A second batch cannot acquire the production lane while an unexpired active, permit-issued, or commit-authorized lease exists.

## Acquisition requirements

Production lease acquisition requires:

- batch state `awaiting_production_slot`;
- candidate channel present;
- completed release-comparison evidence;
- exact registry version;
- exact batch version;
- observed production equal to the batch expected-previous identity;
- a valid production-promotion operation identity;
- no current unexpired lease.

An expired `active` or `permit_issued` lease cannot be silently replaced. The operator must record explicit recovery first. An expired `commit_authorized` lease cannot be automatically recovered because the external mutation may have occurred. It returns `M13_PRODUCTION_MANUAL_RECONCILIATION_REQUIRED`.

## Fencing

Every successful acquisition increments the generation and creates a new fencing token. Renewal, permit, transition, authorization, abort, completion, and recovery verify:

- lease identity;
- holder identity;
- fencing token;
- allowed lease state;
- lease expiry.

A previous generation can never renew, authorize, complete, or release a later lease.

## Permit and transition

A mutation permit is immutable and may be issued only while the lease is active and the batch still satisfies the acquisition conditions. The permit carries the lease generation, fencing token, expected registry and batch versions, expected-previous production, candidate channel, and expiry.

The coordinator is the only M13.3 path that moves a batch from `awaiting_production_slot` to `promoting`. It writes:

- a coordinator-authorized registry event;
- a new immutable batch snapshot;
- a production-promotion running summary linked to the permit;
- an immutable transition marker;
- one registry-head CAS using the same ETag read with the source snapshot.

The ordinary M13.2 transition path continues to reject `awaiting_production_slot -> promoting`.

## Commit authorization

Commit authorization occurs only after the batch reaches `promoting`. Immediately before authorization, the coordinator revalidates:

- current lease, generation, holder, and fencing token;
- current permit;
- unexpired lease;
- exact promoting batch version;
- observed production still equal to expected previous.

Authorization is immutable and one-time per lease. External production code must validate it immediately before mutation.

## Completion and recovery

Completion requires:

- the current commit authorization;
- the current holder and fence;
- unique completion evidence references;
- a resulting production identity different from expected previous.

Completion writes immutable evidence and releases the lease. It does not itself write production.

Crash behavior is fail closed:

- expired `active` or `permit_issued`: explicit recovery allowed;
- unexpired lease: recovery rejected;
- expired `commit_authorized`: automatic recovery rejected and manual reconciliation required;
- CAS collision: action rejected and exact state must be re-read.

## Governance

Candidate artifacts, leases, recovery evidence, and transition markers retain the no-write boundary. Permit, commit authorization, and completion evidence declare permissions required by the external production operation, but the coordinator modules contain no release creation, production-pointer write, rollback, Source write, retention deletion, or ledger append implementation.

## Exit criteria

- bounded candidate concurrency with CAS and explicit expiry recovery;
- one global production mutation lease;
- monotonic generation and fencing tokens;
- exact registry, batch, candidate, comparison, and production validation;
- immutable acquisition, renewal, permit, transition, authorization, completion, release, and recovery evidence;
- coordinator-only transition to `promoting`;
- production revalidation immediately before commit authorization;
- stale holder, fence, permit, version, production, expiry, and concurrent acquisition rejection;
- manual reconciliation after commit-authorized expiry;
- adversarial concurrency tests;
- exact-head CI, R2 Canary, and R2 Release Integration green.
