# M9.7 Production Promotion Review

## Decision

Approved by Daniel (`danielcanfly`) at `2026-07-08T04:52:50Z` through the explicit instruction:

> M9.7 Review and Explicitly Approve Production Promotion

The authoritative machine-readable approval is:

`governed_batches/evidence/m9-001-production-promotion-approval.json`

## Reviewed committed request

- batch: `m9-001-agent-planning-strategies`
- operation ID: `m9-001-agent-planning-strategies-001`
- request path: `production_promotions/m9-001-agent-planning-strategies.json`
- request SHA-256: `41564a42a3f207ea87bbc600935effbb9c3979c8366e16a4b1c7d1f35e172b5b`
- request merge commit: `ca11751a69e800f9dcc239dbb304c60f0cdc7c82`

## Reviewed target

- candidate channel: `candidate-source-2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- release: `20260708T040116Z-69a9f445699a`
- manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Source SHA: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Builder SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Foundation SHA: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`

## Reviewed production precondition

- expected previous release: `20260707T111252Z-aebf06593f89`
- expected previous manifest: `1a2f2014073e9e97f9e1fdd5df4e43bf19cb2b2679532b6e52ea38480ec4d2ec`
- expected previous pointer SHA-256: `2de63a9ff5963ea3f72f0051b25a084dda9e5e609fe79615e55e3f95a1351914`

A live, read-only R2 observation must confirm these values before this approval record can merge and before any later dispatch.

## Reviewed acceptance contract

The production workflow must run the exact committed checks:

- public planning-strategies query returns `answered`
- exact Part 3 citation is present
- public `cobalt heron checkpoint` returns `not_found`
- ACL filtering remains observable
- raw fallback remains disabled

## Authorization scope

This approval authorizes:

- one production workflow dispatch using only the committed `request_path`
- the exact post-promotion acceptance checks
- append-only ledger #30 recording only after successful promotion evidence exists
- lifecycle transition `request_spec_committed -> production_promoted` only after successful promotion

This approval does not authorize:

- request modification or target substitution
- weakening the previous-production precondition
- raw fallback
- rollback
- idempotent replay
- closing the batch

## Lifecycle boundary

The approval is an auxiliary governance gate. It does not itself mutate production or advance the governed lifecycle. Until a later successful dispatch is inspected and reconciled, the batch remains `request_spec_committed`.
