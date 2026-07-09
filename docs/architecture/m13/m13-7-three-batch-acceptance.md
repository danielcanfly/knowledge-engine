# M13.7 Three-Batch Acceptance and M13 Closure

Status: implementation candidate  
Parent: #173  
Slice: #187  
Depends on: M13.6 issue #185 / PR #186  
Engine baseline: `6c901981b6a0cb4ca36985f39875b645c43df5b7`

## Purpose

M13.7 is the acceptance and closure slice for multi-batch production operations. It proves that the contracts delivered by M13.1 through M13.6 compose into one deterministic operating system rather than a collection of isolated unit-tested components.

The acceptance does not authorize a real production promotion. It exercises the real M13 registry, coordinator, lifecycle, comparison, retention, operator, and closeout implementations inside a unique ObjectStore namespace. The real production pointer is read before and after the scenario and must remain byte-for-byte identical.

## Isolation boundary

The workflow wraps the configured ObjectStore in `IsolatedObjectStore`:

```text
m13/acceptance-runs/{run_id}/...
```

Every logical key, including the acceptance fixture `channels/production.json`, is prefixed under that root. Path traversal is rejected and deletion is forbidden. The three-batch core refuses any store that is not an `IsolatedObjectStore`.

The unprefixed production pointer is used only for the before/after invariant:

```text
channels/production.json
```

Its exact expected SHA-256 is pinned by the workflow. A stale baseline or any byte mutation fails closed.

## Acceptance topology

The deterministic scenario begins with three batches derived from one expected production identity.

1. Alpha, beta, and gamma are registered and source-reviewed while all remain active.
2. Alpha and beta occupy the two candidate slots.
3. Gamma attempts a third concurrent candidate and must receive `M13_CANDIDATE_CAPACITY_EXHAUSTED`.
4. Beta is explicitly abandoned and replayed, then rebuilt with strict ancestry and a new candidate channel.
5. Gamma is atomically superseded by a new batch and the supersession is replayed.
6. Alpha, rebuilt beta, and superseding gamma receive deterministic release comparisons.
7. Alpha obtains the only production lease. Rebuilt beta must receive `M13_PRODUCTION_LEASE_BUSY` while that lease is live.
8. Alpha completes the isolated promotion and atomic closeout.
9. Rebuilt beta attempts to acquire a lease against the new production identity and must receive `M13_PRODUCTION_EXPECTED_PREVIOUS_STALE`.
10. The stale rebuilt and superseding batches are explicitly reconciled to `rejected`.
11. Delta is created from the new production identity and completes the second serialized promotion and closeout.
12. Epsilon is created from the next production identity and completes the third serialized promotion and closeout.

The final registry contains exactly:

- three `closed` batches;
- two `abandoned` batches;
- two `rejected` batches.

## Deterministic release fixtures

Each fixture release uses the production M13 inventory contract:

- canonical JSON bytes;
- exact release ID and manifest SHA-256;
- pinned Source repository and commit;
- pinned builder and foundation identities;
- sorted singleton inventories for concepts, claims, audience, citations, registry, and indexes;
- stable entry identities and complete citation support mappings.

Every comparison is executed twice. The second execution must return the same comparison ID, artifact key, canonical bytes, and `idempotent: true`.

## Serialized production mutation

Each accepted promotion uses the actual M13.3 sequence:

```text
acquire lease
→ issue permit
→ transition batch to promoting
→ authorize commit
→ revalidate authorization
→ write isolated production pointer
→ record completion
→ close batch atomically
```

The second closeout call uses identical identity inputs and must replay exactly. Lease generations must increase monotonically across the three promotions.

## Operator reconstruction

After all reconciliation, M13.6 tools must reconstruct the result without scenario-local memory:

- `operator_status` reports three closed, two abandoned, and two rejected batches;
- `integrity_audit` passes every registry, event-chain, operation, candidate, lease, completion, pointer, and manifest check;
- `stale_report` returns zero findings;
- `ledger_summary` reports three closed batches and no missing ledger references;
- exact closeout lookup resolves the third closeout identity.

A failure in any operator surface blocks acceptance.

## Immutable evidence and replay

The acceptance tracker records SHA-256 for all exposed immutable release, registry, lifecycle, candidate, comparison, coordination, completion, and closeout objects. Every hash is reread before the report is written.

The canonical report includes the complete logical object-hash map. On replay, the report bytes must be canonical and every referenced object must still exist with the same SHA-256. Missing or changed evidence fails as an immutable-history violation rather than being silently accepted.

The acceptance report identity covers:

- exact Engine SHA;
- exact canonical Source SHA;
- scenario version;
- all fixture release IDs;
- candidate capacity;
- required promoted-batch count;
- explicit absence of real-production and permanent-ledger authorization.

## Retention proof

The scenario classifies:

- release-comparison evidence;
- closeout evidence;
- abandonment, rebuild, and supersession evidence;
- candidate artifacts;
- coordinator evidence;
- registry history;
- release manifests.

All evidence and history classes must be permanent. Referenced candidate and release objects must remain protected. No object may become a deletion candidate and no physical deletion is performed.

## Authoritative workflow

`.github/workflows/m13-three-batch-acceptance.yml` runs the scenario against real R2 storage under a unique run prefix. It pins:

- the exact PR head SHA;
- canonical Source `2126db2ed4d372d3d61464fe31a86fc0243a1f24`;
- production pointer `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`.

The workflow uploads the canonical acceptance report, runtime receipt, and execution log. The runtime receipt records the physical R2 prefix and the before/after real production pointer hashes.

## Governance declarations

The report and runtime receipt explicitly declare:

```text
isolated_acceptance_write_permitted: true
real_production_write_performed: false
canonical_source_write_performed: false
permanent_ledger_append_performed: false
rollback_performed: false
physical_delete_performed: false
```

The permanent ledger remains open and append-only. The acceptance report is evidence for M13 closure, not a production approval or ledger append instruction.

## M13 closure gate

Parent issue #173 may close only after all of the following pass on the same exact PR head:

- normal CI, including the complete test suite and container build;
- R2 Canary;
- R2 Release Integration;
- M13 Three-Batch Acceptance;
- guarded merge pinned to the accepted head;
- post-merge verification of Engine main, canonical Source, production pointer, permanent ledger #30, slice #187, and parent #173.

The closure comment must record the exact workflow runs, acceptance ID, three promoted batch IDs, release chain, comparison IDs, lease generations, closeout IDs, retention proof, operator reconstruction, merge SHA, and unchanged production/Source/ledger invariants.
