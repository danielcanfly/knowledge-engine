# M13.4 Retention, Supersession, Abandonment and Rebuild Rules

Status: implementation candidate  
Parent: #173  
Slice: #180  
Depends on: M13.3 issue #178 / PR #179  
Engine baseline: `eda6d6f76e5391bcf4c3c597eb98f1a065f23656`

## Purpose

M13.4 defines deterministic lifecycle and retention behavior after multiple governed batches begin to coexist. It prevents artifact age, operator convenience, or candidate-channel reuse from erasing provenance or creating ambiguous lineage.

This slice creates retention plans and registry lifecycle evidence. It does not physically delete objects, modify canonical Source, create a release, write production, execute rollback, or append the permanent ledger.

## Implementation structure

```text
m13_retention.py          retention identities, reference snapshots, reviews and plans
m13_lifecycle_common.py   shared lifecycle identities, CAS and immutable-artifact helpers
m13_abandonment.py        reasoned single-batch abandonment
m13_supersession.py       atomic multi-batch supersession
m13_rebuild.py            governed rebuild registration
m13_lifecycle_rules.py    compatibility-only public facade
```

The facade contains no lifecycle implementation logic. Every destructive or network-capable surface is excluded by an AST policy test.

## Retention dispositions

Every artifact is classified into one of four dispositions:

```text
permanent
protected
quarantine
deletion_candidate
```

`deletion_candidate` is not deletion authorization. M13.4 always emits `physical_delete_permitted: false`.

### Permanent

The following classes are permanently retained:

- review and evaluation evidence;
- registry events and historical snapshots;
- coordinator acquisition, lease, permit, authorization, completion, and recovery evidence;
- production identity records;
- permanent-ledger references and closeout evidence.

Time, terminal state, supersession, abandonment, and rebuild never downgrade permanent evidence.

### Protected

An artifact is protected while any live reference exists, including:

- current production release;
- rollback target;
- release referenced by a nonterminal batch or retained evidence;
- candidate channel referenced by a nonterminal batch;
- raw snapshot belonging to a nonterminal batch;
- artifact explicitly referenced by another retained object.

Protected artifacts cannot enter quarantine while the reference remains.

### Quarantine

Unreferenced non-permanent artifacts enter a minimum retention window:

| Artifact class | Minimum window |
|---|---:|
| Candidate | 30 days after terminal time |
| Raw snapshot | 90 days |
| Non-production release | 180 days |
| Former rollback target | 365 days |

The window is a lower bound, not authorization. After it expires, the artifact remains quarantined until an explicit retention review approves its exact artifact identity against an exact reference snapshot.

### Deletion candidate

An artifact becomes a deletion candidate only when all conditions hold:

- it is not permanent;
- it has no live batch, candidate, release, rollback, production, or evidence reference;
- its minimum retention window has elapsed;
- a reviewer approved the exact artifact ID;
- the approval names the exact reference-snapshot SHA;
- the review predates or equals plan generation;
- the artifact belongs to the reviewed plan.

Even then, M13.4 records only a non-destructive deletion candidate. A later governed deletion mechanism must revalidate all references and carry separate authorization.

## Retention artifacts

Retention plans are immutable:

```text
m13/v1/retention/plans/{plan_id}.json
```

A plan contains:

- exact artifact identities and SHA-256 values;
- exact production identity;
- open batch IDs;
- active candidate channels;
- referenced release and rollback IDs;
- referenced artifact IDs;
- optional review approval;
- deterministic decisions;
- no-write governance boundary.

Exact replay returns the same plan identity and bytes.

## Abandonment

Eligible states:

```text
planned
reviewing_source
candidate_ready
awaiting_production_slot
```

The following states cannot be abandoned through M13.4:

```text
promoting
closed
rejected
abandoned
```

Abandonment requires:

- exact registry version;
- exact batch version;
- exact expected-previous production identity;
- no active production lease;
- actor, reason code, rationale, and UTC timestamp.

The action writes immutable abandonment evidence, one event, one snapshot, and one registry-head CAS. Candidate identity remains recorded and is never reused.

## Supersession

A superseding batch must:

- start in `planned`;
- name at least one superseded batch;
- use unique, sorted supersession IDs;
- preserve the source repository and expected-previous production baseline;
- have a distinct batch identity;
- use an unclaimed candidate channel when one is reserved;
- avoid direct or transitive supersession cycles.

Only batches in abandonment-eligible states may be superseded. A promoting, closed, rejected, or already abandoned batch cannot be silently replaced.

Supersession is atomic at the registry-head level:

- register the new planned batch;
- transition every superseded batch to `abandoned`;
- write one immutable supersession evidence artifact;
- write immutable events and snapshots for all affected batches;
- commit one registry-head CAS.

Partial supersession is not visible through the registry head.

## Rebuild

A rebuild is a new batch, not mutation of the old candidate.

A rebuild batch must:

- start in `planned`;
- name exactly one direct `rebuilt_from_batch_id`;
- supersede exactly that ancestor;
- reserve a new candidate channel;
- use a distinct batch identity;
- preserve source repository, source commit, and expected-previous production;
- originate from an `abandoned` or `rejected` ancestor;
- require completed candidate-build evidence and an ancestor candidate channel;
- reject ancestor candidate-channel reuse.

The old batch, candidate channel, snapshots, events, and evidence remain immutable.

## Production coordination boundary

Abandonment, supersession, and rebuild registration are blocked whenever the M13.3 production lease is:

```text
active
permit_issued
commit_authorized
```

Released and explicitly recovered leases do not block lifecycle planning.

This prevents registry lineage changes from racing a production mutation.

## Replay and failure behavior

- exact replay returns the existing action result;
- stale registry or batch versions fail closed;
- divergent replay fails with an identity collision;
- CAS conflict leaves only safe immutable orphan evidence;
- no operation silently rewrites a candidate channel;
- no operation mutates or deletes historical snapshots or events.

## Exit criteria

- deterministic four-state retention classification;
- permanent evidence protection;
- current production and rollback protection;
- exact retention review binding;
- non-destructive deletion-candidate plans;
- reasoned, replayable abandonment;
- atomic multi-batch supersession;
- cycle and candidate-channel reuse rejection;
- strict rebuild ancestry and origin rules;
- active production lease exclusion;
- adversarial tests and all-module non-destructive surface scan;
- exact-head CI, R2 Canary, and R2 Release Integration green.
