# Knowledge OS Operator Runbooks

This directory is the canonical entry point for operating Knowledge OS. Architecture explains
what the system is; these runbooks define the exact ordered procedure, evidence handoffs, authority
boundaries, and stop conditions used by a qualified operator.

## Canonical runbooks

1. [End-to-End Governed Batch Runbook](m17/end-to-end-batch-runbook.md)
2. [Promotion, Rollback, and Recovery](m17/promotion-rollback-recovery.md)
3. `m17/runbook-registry.json`, the machine-readable ordered lifecycle contract
4. [Troubleshooting and Failure Atlas](../troubleshooting/README.md)
5. [Operator Inspection and Evidence Tooling](m17/operator-tooling.md)
6. `m17/tool-registry.json`, the machine-readable read-only tool authority contract
7. [Operator Training and Qualification](m17/operator-training.md)
8. `m17/training-registry.json`, the machine-readable curriculum and scoring contract
9. [v1 GA Evidence Matrix](../ga/m17/v1-ga-evidence-matrix.md)
10. `../ga/m17/ga-evidence-registry.json`, the machine-readable 20-capability proof contract

The architecture canon remains at `docs/architecture/README.md`. When an operations document and an
implementation disagree, stop. Code, committed contracts, immutable evidence, and approved request
identity outrank prose. Repair the documentation through a reviewed Engine PR before continuing.

## Ownership and change policy

The Knowledge Engine maintainers own these runbooks. Any change to command surfaces, evidence
identities, lifecycle phases, mutation authority, Source governance, candidate publication,
production promotion, ledger recording, closeout, failure signals, troubleshooting boundaries,
operator inspection authority, training exercises, competency coverage, qualification scoring,
critical-exercise policy, GA capability ownership, or GA proof references must update the relevant
machine registry and pass its dedicated M17 acceptance workflow.

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
- Qualification proves documented competence only. It never substitutes for operation-specific
  approval or grants production mutation authority.
- Evidence completeness means ready for M17.7. It never substitutes for the independent drill or
  final GA acceptance.

## Machine validation

Run:

```bash
python scripts/m17_operator_runbook_acceptance.py \
  --root . \
  --registry docs/operations/m17/runbook-registry.json \
  --output .artifacts/m17/operator-runbook-acceptance.json

python scripts/m17_operator_tooling_acceptance.py \
  --root . \
  --registry docs/operations/m17/tool-registry.json \
  --output .artifacts/m17/operator-tooling-acceptance.json

python scripts/m17_operator_qualification_acceptance.py \
  --root . \
  --registry docs/operations/m17/training-registry.json \
  --output .artifacts/m17/operator-qualification-acceptance.json

python scripts/m17_ga_evidence_acceptance.py \
  --root . \
  --registry docs/ga/m17/ga-evidence-registry.json \
  --output .artifacts/m17/ga-evidence-acceptance.json
```

The reports are canonical JSON, carry SHA-256 identities, and fail closed when a stage, tool,
exercise, GA capability, reference, evidence handoff, authority boundary, scoring rule, mutation
guard, or owned document is invalid.
