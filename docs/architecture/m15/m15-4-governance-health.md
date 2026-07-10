# M15.4 Governance Health and Stalled Work

Parent: #204  
Slice: #211

## Baseline

- Engine: `fb7459d90b10fc865239c7cca3077699ca6ac07c`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

## Purpose

M15.4 evaluates governance registry and operator evidence without changing lifecycle state. It identifies stalled, inconsistent, blocked, or unverifiable work and emits deterministic evidence for operators.

## Closed lifecycle model

Registered work is evaluated in one of these phases: registered, claimed, running, awaiting approval, awaiting evidence, blocked, completed, failed, or cancelled. Unknown phase values fail validation.

## Health findings

The evaluator detects missing owners, expired leases, stale or future heartbeats, missing approvals, missing evidence, exhausted retries, unsatisfied dependencies, Engine identity drift, duplicate work IDs, and terminal-state inconsistencies.

Health is closed to healthy, degraded, unhealthy, unknown, and not applicable. Missing or contradictory evidence never produces a healthy claim.

## Determinism

All timestamps are timezone-aware UTC. Thresholds are explicit. Findings are sorted by issue code, work ID, and health state. Reports use canonical UTF-8 JSON with sorted keys and SHA-256 identity.

## No-action boundary

This slice cannot retry, reassign, approve, close, merge, promote, roll back, edit Source, mutate production, repair a pointer, write or delete R2 objects, dispatch candidates, or append permanent ledger #30. Findings are advisory evidence only.