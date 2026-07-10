# M16.7 End-to-End Restore Drill, Acceptance, and Closure

M16.7 joins the six earlier M16 slices into one deterministic restore-drill trace. It validates evidence produced by an isolated or separately governed operation, but it does not execute restoration or obtain production mutation authority.

## Exact baseline

- Engine: `17727eddf1a6e15e4265c49b79d1f116f0e09090`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Production manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Production pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`
- Permanent ledger #30: open with 13 comments and unchanged by this slice

Every observation and report carries the complete identity tuple. Identity drift blocks closeout.

## Required drill sequence

The report requires ten ordered stages:

1. detection;
2. containment;
3. authorization;
4. restoration;
5. checksum verification;
6. runtime verification;
7. replay verification;
8. recovery objectives;
9. audit continuity;
10. closeout.

Each stage has a UTC timestamp, a closed evidence state, and bounded public evidence codes. Missing, duplicate, future-dated, stale, blocked, unknown, or chronologically out-of-order stage evidence fails closed.

## Detection and containment

The trace must prove that the incident was detected, the blast radius was bounded, production writes were disabled for the drill scope, and the production pointer remained byte-for-byte unchanged.

## Authorization and represented restoration

A represented restore requires:

- approved authorization;
- a bounded authorization ID;
- verified scope;
- exact incident, drill, and operation identities.

The evaluator records external or isolated execution evidence. It cannot perform an R2 write, copy, delete, pointer repair, cache purge, promotion, rollback, or Source mutation.

## Checksum and identity verification

Closeout requires exact matches for:

- restored object SHA-256;
- production manifest SHA-256;
- production release ID;
- production pointer SHA-256.

A buildable or readable object is insufficient when its identity differs from the trusted release inventory.

## Runtime verification

After represented restoration, the trace must verify:

- runtime release binding;
- runtime pointer binding;
- cache release binding;
- a public query;
- its citation;
- an ACL-negative query that remains denied.

This prevents a technically restored object from being called healthy while query, citation, cache, or audience behavior is still wrong.

## Replay safety and recovery objectives

The drill requires replay compliance, idempotency evidence, and exact expected-previous pointer verification. It also requires RTO, RPO, release-unavailability, rollback, and evidence-recovery objectives to be `passed` or explicitly `not_applicable`.

A failed objective blocks closeout. Missing objective evidence produces an `unknown` decision.

## Audit continuity and permanent ledger invariant

The trace must prove audit continuity and verify that permanent ledger #30:

- remains open;
- has the expected unchanged comment count;
- received no M16.7 append.

The permanent ledger is an audit invariant, not the general M16 engineering log.

## Closeout decisions

- `ready_to_close`: every gate passes;
- `blocked`: at least one identity, stage, restoration, runtime, replay, objective, audit, or closeout gate is blocked;
- `unknown`: no blocked gate exists, but required stage or objective evidence is unknown.

Reports use stable stage and gate ordering, canonical JSON, SHA-256 identity, and tamper detection.

## Privacy and authority boundary

Evidence rejects raw queries, raw answers, credentials, bearer/JWT/cookie material, private excerpts, host or IP data, object or repository URIs, arbitrary exception text, and unknown extra fields.

M16.7 cannot:

- mutate production, its pointer, or runtime caches;
- write, copy, or delete R2 objects;
- write canonical Source or create a Source PR;
- execute promotion or rollback;
- rotate credentials;
- physically delete data;
- append to permanent ledger #30.

It is the incident flight recorder and closeout board, not the recovery machinery.
