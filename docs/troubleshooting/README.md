# Knowledge OS Troubleshooting and Failure Atlas

This directory is the canonical troubleshooting entry point for Knowledge OS. It complements the
[Architecture Canon](../architecture/README.md) and the
[Operator Runbooks](../operations/README.md). Use it when an observed signal, failed gate, ambiguous
workflow result, integrity mismatch, security indicator, or documentation discrepancy prevents the
normal runbook from continuing.

## Canonical troubleshooting assets

1. [Cross-Plane Failure Atlas](m17/failure-atlas.md)
2. [Triage Flow and Escalation Matrix](m17/triage-flow.md)
3. `m17/failure-registry.json`, the machine-readable failure and diagnostic contract

## How to use the atlas

1. Stop the current procedure before crossing another authority or mutation boundary.
2. Record only privacy-safe identities, digests, bounded signal codes, and verification outcomes.
3. Match the observed signal to one or more registry entries. Never select a cause from memory alone.
4. Collect the exact evidence named by the entry and verify its repository reference and anchor.
5. Perform only the listed read-only or preparation-only actions.
6. Escalate to the named owner when a stop condition remains true.
7. Resume the normal runbook only after the failure state is resolved and every affected gate is
   independently re-verified.

A symptom can map to several probable causes. The atlas narrows the investigation; it does not grant
approval, mutation authority, or permission to infer missing state.

## Authority boundary

Troubleshooting is read-only by default. These documents and their validator do not write canonical
Source, publish candidates, promote or roll back production, repair pointers, mutate R2, purge caches,
rotate credentials, append the permanent ledger, close batches, approve requests, merge pull
requests, or reconstruct missing authority.

When a recovery action is required, return to the governed recovery runbook and obtain the exact
approval, operation identity, expected-previous state, verification plan, rollback readiness, and
bounded execution authority required there.

## Evidence and privacy rules

- Prefer deterministic reason codes over raw exception text.
- Do not paste tokens, authorization headers, cookies, private excerpts, raw queries, raw answers,
  hostnames, private object locations, or unbounded logs into troubleshooting artifacts.
- Bind observations to exact Engine, Source, release, manifest, pointer, request, operation, batch,
  or report identities as applicable.
- Treat missing, stale, conflicting, future-dated, privacy-unsafe, or identity-drifted evidence as
  unknown and fail closed.
- Preserve failed evidence without rewriting it. A corrected observation is a new artifact.

## Ownership and change policy

Knowledge Engine maintainers own this atlas. Changes to error codes, gate names, security indicators,
recovery reasons, lifecycle states, evidence requirements, escalation targets, diagnostic commands,
or authority boundaries must update the registry and pass the dedicated M17 Failure Atlas Acceptance
workflow.

## Machine validation

Run:

```bash
python scripts/m17_failure_atlas_acceptance.py \
  --root . \
  --registry docs/troubleshooting/m17/failure-registry.json \
  --output .artifacts/m17/failure-atlas-acceptance.json
```

The report is canonical JSON with a SHA-256 identity. Validation fails closed on missing coverage,
broken paths or anchors, unsafe commands, duplicate signal ownership, stale dynamic identities,
privacy-unsafe content, invalid escalation, incomplete evidence or stop conditions, authority drift,
or report tampering.
