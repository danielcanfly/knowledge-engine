# M7 Entry Plan

Status: `in progress`

Parent tracker: `#74`

Entry baseline issue: `#75`

## Goal

Turn the proven M6 single-batch release path into a repeatable governed batch system that is easier to operate but no easier to bypass.

## Starting production

- Release ID: `20260706T061437Z-bc48bf4810c0`
- Manifest SHA-256: `8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96`
- Production pointer SHA-256: `edd628ca3c2b1991866c3d7adbff05ff32f8eef581e80d4ebd4b781dbbf6dcd6`
- Final M6 replay run: `28849698444`
- Permanent ledger: `#30`

## M7 invariants

- Source remains review-only and PR-driven.
- Candidate identity remains bound to the exact Source SHA.
- Production promotion remains committed-request-spec driven.
- Workflow dispatch continues to accept only `request_path`.
- Public citation acceptance and ACL negative acceptance keep raw fallback disabled.
- Replay and rollback remain observable and safe.
- M7 planning and dry runs do not mutate Source or production.

## Milestones

### M7.1 Entry baseline

- reconcile final M6 documentation
- record the authoritative starting production identity
- merge this M7 entry plan

### M7.2 Batch spec v2 and registry

- define a versioned batch specification
- define lifecycle states and legal transitions
- prevent duplicate batch IDs, operation IDs, candidate channels, and request paths
- add schema validation and tests

### M7.3 Operator preflight

- add one non-mutating command that validates repository state, Source identity, Builder and Foundation pins, candidate availability, production baseline, acceptance queries, required secrets, and workflow availability
- emit machine-readable evidence and human-readable next actions
- never dispatch or mutate automatically

### M7.4 Scale-up readiness gate

- detect duplicate or overlapping content scope
- detect citation drift
- verify ACL fixture coverage
- detect candidate-channel and operation-ID collisions
- detect production-pointer drift
- confirm ledger and replay or rollback workflows remain healthy

### M7.5 Governed dry run

- create one M7 batch spec using the new schema
- run validation and preflight only
- stop before Source PR, candidate build, or production promotion

### M7.6 Closeout

- prove main CI and R2 release lifecycle are green
- publish M7 readiness evidence
- decide whether controlled content-volume growth may begin

## First implementation order

1. Finish M7.1 documentation reconciliation.
2. Design the batch spec v2 schema before writing operator automation.
3. Build the registry validator and transition rules.
4. Build the non-mutating preflight around the schema and registry.
5. Add scale-up readiness checks.
6. Execute the governed dry run.

## Non-goals

- no new canonical Source content
- no candidate build
- no production request spec
- no production promotion
- no weakening of citation, ACL, replay, rollback, or ledger gates
