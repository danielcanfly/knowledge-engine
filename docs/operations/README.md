# Knowledge OS Operator Runbooks

This directory is the canonical entry point for operating Knowledge OS. Architecture explains
what the system is; these runbooks define the exact ordered procedure, evidence handoffs, authority
boundaries, and stop conditions used by a qualified operator.

## Canonical runbooks

1. [End-to-End Governed Batch Runbook](m17/end-to-end-batch-runbook.md)
2. [Promotion, Rollback, and Recovery](m17/promotion-rollback-recovery.md)
3. `m17/runbook-registry.json`, the machine-readable ordered lifecycle contract
4. [Troubleshooting and Failure Atlas](../troubleshooting/README.md)

The architecture canon remains at `docs/architecture/README.md`. When an operations document and an
implementation disagree, stop. Code, committed contracts, immutable evidence, and approved request
identity outrank prose. Repair the documentation through a reviewed Engine PR before continuing.

## Ownership and change policy

The Knowledge Engine maintainers own these runbooks. Any change to command surfaces, evidence
identities, lifecycle phases, mutation authority, Source governance, candidate publication,
production promotion, ledger recording, closeout, failure signals, or troubleshooting boundaries
must update the relevant machine registry and pass its dedicated M17 acceptance workflow.

Runbooks never grant authority. They point to authority that already exists in an explicit approved
contract or environment. Placeholders such as `<SOURCE_SHA>` must be replaced from current governed
evidence, never from memory, a moving branch, or copied historical values.

## Universal operator rules

- Work from a clean checkout and record the exact Engine, Source, Foundation, release, manifest,
  pointer, operation, request, and batch identities relevant to the stage.
- Preserve every emitted identifier and digest. The next stage must consume the exact prior output.
- Keep canonical Source, generated packages, candidate artifacts, production artifacts, runtime
  cache, and evidence stores distinct.
- Do not broaden audience. Unknown ACL meaning blocks progress.
- Treat human review, Source PR merge, candidate publication, production promotion, permanent-ledger
  append, and batch closeout as separate authority boundaries.
- Stop on identity drift, incomplete evidence, failed checks, stale expected-previous state,
  missing approval, replay collision, unready rollback, or failed post-action verification.
- A safe stop is a valid operational outcome. Improvising a mutation is not.

## Machine validation

Run:

```bash
python scripts/m17_operator_runbook_acceptance.py \
  --root . \
  --registry docs/operations/m17/runbook-registry.json \
  --output .artifacts/m17/operator-runbook-acceptance.json
```

The report is canonical JSON, carries a SHA-256 identity, and fails closed when a stage, reference,
anchor, evidence handoff, mutation guard, or owned document is invalid.
