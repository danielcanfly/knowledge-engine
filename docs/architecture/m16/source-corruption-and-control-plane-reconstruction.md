# M16.5 Source Corruption and Control-Plane Reconstruction

M16.5 defines deterministic evidence for recovering canonical Source and reconstructing control-plane state without adding a Source, Git, production, R2, or ledger mutation executor.

## Exact baseline

- Engine: `d9dd9cf63908fc352422b2184e7a4afc30eec0da`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Production manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Production pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

Every observation and report carries these identities. Identity drift blocks reconstruction completion.

## Source corruption detection

The evaluator distinguishes:

- `healthy`: observed Source head equals canonical Source and history has not diverged;
- `drifted`: Source head differs from the expected canonical SHA;
- `corrupted`: trusted history divergence is observed;
- `unknown`: evidence cannot support a conclusion.

A Source restoration point is trusted only when:

- its SHA equals the expected canonical Source SHA;
- it is reachable from trusted Git history;
- review evidence is complete;
- commit signature evidence is verified;
- the trusted history itself is intact.

A recent-looking commit is not enough. The restoration point must carry ancestry and governance evidence.

## Governed external restoration

This contract may represent externally governed restoration evidence, but it cannot execute reset, revert, force-push, branch update, or Source PR creation.

When restoration execution is represented, explicit authorization and the exact restored Source SHA are required. A deterministic rebuild must then reproduce both:

- the expected canonical Source SHA;
- the expected production manifest SHA-256.

A mismatch blocks completion instead of treating a merely buildable candidate as equivalent.

## Control-plane reconstruction

The reconstruction inventory contains closed component kinds:

- batch registry;
- approvals;
- lifecycle state;
- production identity;
- pointer identity;
- artifact inventory;
- permanent-ledger continuity;
- ephemeral state.

Every critical component must have bounded evidence, verified identity, and completeness. Before external execution, a complete component is `reconstructable`. After represented reconstruction, it is `verified`.

Missing or mismatched critical components block recovery. Permanent-ledger continuity is a critical gate and cannot be synthesized from memory.

## Ephemeral state

Ephemeral state is handled differently from durable governance evidence. When no durable evidence exists, it is explicitly marked `unrecoverable`. The evaluator never invents queue positions, temporary locks, in-memory sessions, or uncommitted operator context.

A system may be `partially_reconstructed` when all durable critical components are verified but an acknowledged ephemeral gap remains. That gap stays visible in the report.

## Decisions

- `healthy`: canonical Source is healthy and all durable control-plane components are already verified;
- `ready_for_governed_restore`: trusted restoration and reconstruction inputs exist, but governed execution evidence is absent;
- `reconstructed_and_verified`: Source restoration, deterministic rebuild, and all components are verified;
- `partially_reconstructed`: durable state is verified, with explicit unrecoverable ephemeral state;
- `blocked`: identity, trusted Git, rebuild, durable component, or ledger continuity evidence failed;
- `unknown`: evidence is insufficient for deterministic evaluation.

## Deterministic evidence

Reports use stable component and gate ordering, timezone-aware UTC timestamps, closed states and reason codes, canonical JSON, SHA-256 identity, and tamper detection. Evidence fields reject credentials, raw queries or answers, private excerpts, host or IP data, repository or object URIs, and arbitrary exception text.

## Authority boundary

M16.5 cannot:

- write, reset, or revert canonical Source;
- update a branch or Git ref;
- create or dispatch a Source PR;
- promote a candidate;
- mutate production, its pointer, caches, or R2;
- execute rollback;
- rotate credentials;
- physically delete data;
- append to permanent ledger #30.

It is the reconstruction map and continuity inspector, not the hand that moves canonical history.
