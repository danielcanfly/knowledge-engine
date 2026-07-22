# ADR M25.1: Admission Architecture Freeze and Reuse Map

**Status:** Accepted for exact-head implementation review  
**Decision date:** 2026-07-23  
**Entry Engine SHA:** `25a119e428bb202ebbed4b5a73a4209c41f9ce27`

## Context

M10 already provides immutable acquisition, normalisation, evidence identity, ACL/licence
handling, raw deduplication, event chains, and connector-specific safety. M11 already provides
structured evidence, candidates, resolution, review packets, decisions, and Source package
contracts. M21 already provides bounded inventory, resumable batches, evidence-bound
candidates, governed relations/tags, entity-resolution evidence, reviewer packets, and phase
acceptance. M24 proves bounded pilot accounting, human decision capture, candidate release
rebuild, product regression, rollback boundaries, and a final M25 entry baseline.

Building another ingestion framework would split identity, replay, ACL, and evidence semantics.
M25 therefore composes existing capabilities through explicit adapters.

## Decision

1. `intake/v1` is the single immutable evidence plane for raw bytes, snapshots, derivatives,
   acquisition events, and rejections.
2. `admission/v1` is a new control-plane namespace for plans, checkpoints, authority envelopes,
   adapter envelopes, resolution references, review decisions, and adoption receipts.
3. `admission/v1` stores references and digests. It must not duplicate raw or normalised source
   payloads already stored under `intake/v1`.
4. Canonical Source remains the only editable knowledge truth. Candidate artifacts never imply
   Source write or merge authority.
5. M21.5 and M21.6 cannot be reused unchanged because they pin legacy Source SHA
   `a6ba738d910d01d2ae99b1968f0831989934c549`. M25 uses versioned adapters bound to current Source SHA
   `acf78596ace8a7366688ccef72b507204d09d9f9`.
6. M11 resolution remains a compatibility and benchmark lane. M25.5 calibrates one governed
   identity system rather than adding a competing resolver.
7. Production retrieval remains lexical. Semantic/hybrid serving, answer serving, production
   pointer mutation, and large-scale ingestion remain disabled.
8. Every transition after `review_pending` requires a decision digest. Every Source merge and
   production promotion requires an explicit Daniel authority record.

## Consequences

M25.2 can focus on orchestration instead of rebuilding connectors. M25.3 can add provider-neutral
model extraction without changing candidate authority. M25.4 and M25.5 can benchmark and
calibrate the existing resolver family. M25.6 and M25.7 can reuse review and Source-package
contracts while adding product and GitHub execution gates.

## Rejected alternatives

- A second M25 raw/snapshot store
- A new resolver independent of M11/M21 evidence
- Automatic Source canonicalisation
- Treating model confidence as approval
- Enabling semantic or hybrid production retrieval as part of admission work
