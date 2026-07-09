# M13 Closure Evidence

Status: pre-merge closure package  
Parent: #173  
Slice: #187  
Pull request: #189  
Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`

## Evidence scope

This package records the first successful authoritative M13 three-batch acceptance run and the exact identities needed to review M13 closure. The final accepted PR head and guarded merge SHA are recorded in the PR and parent-issue closure comments after this document itself is merged into the final head.

The acceptance executed the real M13.1–M13.6 registry, lifecycle, coordinator, release-comparison, retention, operator, and closeout implementations against real R2 storage under an isolated prefix. It did not authorize or modify real production, canonical Source, permanent ledger #30, rollback state, or retained production history.

## Successful authoritative run

- Preliminary accepted implementation head: `d29ca1c34288d067697592a1d2ca1cbc17f0f3ef`
- Workflow: M13 Three-Batch Acceptance
- Workflow run ID: `29035038127`
- Workflow run number: `3`
- Artifact ID: `8205724002`
- Artifact name: `m13-three-batch-acceptance-29035038127-1`
- Artifact digest: `sha256:29ce4bf4b2143bdf41a98bff7b999636c80228648abdf92273f54edfe21e74c1`
- Acceptance ID: `m13accept_16abb5bfe3bfe6af53fec1d00a84cf8e`
- Acceptance report SHA-256: `2aebdc6c2debabc3393f48b95ed8e31c98cca861bed54e7cc008cdb5a07dee74`
- Logical report key: `m13/v3/acceptance/m13accept_16abb5bfe3bfe6af53fec1d00a84cf8e/report.json`
- Physical isolated prefix: `m13/acceptance-runs/29035038127-1-c4359d3a495a4fccffe6ebcc554c9ec5281508a9`

The runtime receipt proved the real production pointer SHA-256 was identical before and after acceptance:

```text
38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5
```

## Serialized promotion and closeout chain

### Promotion 1

- Batch: `mbatch_1bd7509c7f4c12da28674ef14587a5cd`
- Lease: `mlease_38ba5e1c32825ad266943bbb9d347643`
- Lease generation: `1`
- Permit: `mpermit_71acb2071f971c8604a7f71b35f7eece`
- Authorization: `mauth_89c706e9d737b9d64be95de6ce05f3ec`
- Completion: `mcomplete_830fc8bc6efc22dcd5a524504f336477`
- Closeout: `mclose_0aeb93c29efaec11d8f648a957c2186a`
- Resulting release: `20260710T010000Z-111111111111`
- Manifest SHA-256: `145ac45467eb3751d5db1383e33a9fc43b5d3f450e1453c7b657aa88b3b6076b`
- Isolated pointer SHA-256: `a8112a8819fcf71b200ed6ef96418b219ba11894a8cdab0987cf4f75aa4d8415`

### Promotion 2

- Batch: `mbatch_144e3f2fcadf70824a89649c3ec3c383`
- Lease: `mlease_7572e903ecb182381ab379b9f8ffbd67`
- Lease generation: `2`
- Permit: `mpermit_16b38ab2634225b4a40e26af554019f7`
- Authorization: `mauth_96a4266da659f74f782d95f080eceb1e`
- Completion: `mcomplete_86f042a400f8560e9fc25da5c894a4a9`
- Closeout: `mclose_d5a5ae2c61298dfc80d36c5a58bfcbbc`
- Resulting release: `20260710T020000Z-222222222222`
- Manifest SHA-256: `434c4e27962190343d37b76d333883be42ba4212369c4170b664f2599c68ebea`
- Isolated pointer SHA-256: `fcc2692b778b694195516b775163b9ed9adb874eb2a387a3bbf5272a023dabe5`

### Promotion 3

- Batch: `mbatch_c70ec4de5c0d805715ed27ca92b446ed`
- Lease: `mlease_9af1625550eedd36fc26ae43dfa6b922`
- Lease generation: `3`
- Permit: `mpermit_bbbf5e02032e01f78dd0b186f99914e8`
- Authorization: `mauth_1b65066efa630f72933986efc55ce303`
- Completion: `mcomplete_2704ca2b6e9cfa19f6ce700bba715361`
- Closeout: `mclose_34a66ef39395783628273e214809afcb`
- Resulting release: `20260710T030000Z-333333333333`
- Manifest SHA-256: `6ad8dc8248456fe34408a6ca0d601fae1f925e6613cffee1e4cf035d7f8ca9a1`
- Isolated pointer SHA-256: `02442d32deded915332fed2d1e3a53128bd304753b7e431324f1673e9d94b167`

## Deterministic comparison evidence

Five exact release comparisons completed and replayed idempotently:

- `mcompare_555a7e2c479f4ae83326e79e03f3c84a`
- `mcompare_6404862f2a9c96cfe813b686d78fd8d9`
- `mcompare_87df97e2efc1aea07e6a801ecf48dfd1`
- `mcompare_9b9e17cacc68179b36ecb86d4e84dc27`
- `mcompare_e564db99951cfc62dba6f9c00b62dfdb`

## Lifecycle evidence

- Candidate capacity rejection: `M13_CANDIDATE_CAPACITY_EXHAUSTED`
- Production serialization rejection: `M13_PRODUCTION_LEASE_BUSY`
- Stale expected-previous rejection: `M13_PRODUCTION_EXPECTED_PREVIOUS_STALE`
- Abandonment action: `mlife_83fddb7fb83b09b3a14af4ed86e97e14`
- Rebuild action: `mlife_fef7bfaa6d91eba19ae4c431a5e55a5d`
- Supersession action: `mlife_63ce623807685e2ac1f6cc8c68e131b1`

Terminal reconciliation:

- Closed: `3`
- Abandoned: `2`
- Rejected: `2`
- Total registered batches: `7`
- Registry version: `54`

Abandoned batch IDs:

- `mbatch_2e6c923ed5e99f45fc60effdc95a1679`
- `mbatch_ecd42e1fa36b232e514e9fb97937c459`

Rejected stale-lineage batch IDs:

- `mbatch_b235f63144514c77b34906644def81f4`
- `mbatch_fa8bc25ea6ef737f31c92e5e56da0b8e`

## Operator reconstruction

The final state was reconstructed only from persisted M13 objects:

- Integrity audit passed: `true`
- Objects checked by audit: `76`
- Stale findings: `0`
- Closed batches in ledger summary: `3`
- Exact closeout lookup matches: `1`
- State counts: `abandoned=2`, `closed=3`, `rejected=2`

No scenario-local in-memory decisions were required to explain the final state.

## Retention and immutable-history proof

- Tracked immutable objects: `212`
- All tracked hashes fresh-read and reverified from R2: `true`
- Overwritten object count: `0`
- Retention artifacts classified: `141`
- Permanent: `128`
- Protected: `13`
- Deletion candidates: `0`
- Physical delete performed: `false`
- Retention reference snapshot SHA-256: `529f18ea08e1ebccfedb7d0a15c51c6217f42a3dfeb56c866587d3b09d6d0020`

## Governance invariants

The acceptance report and runtime receipt declare and prove:

```text
isolated_acceptance_write_permitted: true
real_production_write_performed: false
canonical_source_write_performed: false
permanent_ledger_append_performed: false
rollback_performed: false
physical_delete_performed: false
```

The authoritative real production identity remained:

- Release: `20260708T040116Z-69a9f445699a`
- Manifest SHA-256: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Pointer SHA-256: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

Permanent ledger #30 remains open and unchanged. This evidence package is not a production authorization or a ledger append instruction.

## Final closure procedure

After this document enters the PR head, CI, R2 Canary, R2 Release Integration, and M13 Three-Batch Acceptance must all pass again on that exact head. The final acceptance ID and workflow run identities are then recorded in PR #189 and parent issue #173, followed by guarded squash merge, post-merge invariant verification, completion of #187, and closure of #173.
