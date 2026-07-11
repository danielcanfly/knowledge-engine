# Knowledge OS v1 GA Evidence

This directory is the canonical entry point for Knowledge OS v1 general-availability evidence.

M17.6 consolidates the cross-milestone proof for all 20 required GA capabilities. M17.7 adds the
clean-room independent operator drill and final acceptance. A valid final report may declare
`ga_accepted` only after repository-only execution, independent evaluation, complete lifecycle
coverage, safe-stop proof, exact identity binding, and unchanged-head workflow acceptance.

## Canonical artifacts

1. [v1 GA Evidence Matrix](m17/v1-ga-evidence-matrix.md)
2. `m17/ga-evidence-registry.json`, the machine-readable capability evidence contract
3. [Independent Operator Drill and GA Acceptance](m17/independent-operator-drill-and-ga-acceptance.md)
4. `m17/independent-ga-contract.json`, the machine-readable final drill contract
5. `.github/workflows/m17-ga-evidence-matrix.yml`, the M17.6 evidence workflow
6. `.github/workflows/m17-ga-acceptance.yml`, the independent M17.7 GA workflow

## Authority and interpretation

- A milestone title or narrative statement is not evidence.
- Every capability must point to an existing contract or module, test, workflow, merged pull request,
  exact merge commit, and stable matrix anchor.
- Missing, broken, unmerged, malformed, conflicting, or gap-bearing evidence blocks readiness.
- `evidence_complete` means a row is ready for the independent drill.
- `ga_accepted` requires all 18 lifecycle stages, all 20 capabilities, four mandatory safe stops,
  distinct operator and evaluator identities, repository-only context, and final reconciliation.
- Governed mutation stages are simulated at their authority boundaries in the drill. The final
  acceptance layer does not execute Source, candidate, production, pointer, cache, R2, credential,
  approval, ledger, rollback, lifecycle, or closeout mutation.

## Validation

Validate M17.6 evidence readiness:

```bash
python scripts/m17_ga_evidence_acceptance.py \
  --root . \
  --registry docs/ga/m17/ga-evidence-registry.json \
  --output .artifacts/m17/ga-evidence-acceptance.json
```

Run the final independent drill and assessment:

```bash
python scripts/m17_ga_acceptance.py \
  --root . \
  --engine-sha <ENGINE_SHA> \
  --source-sha <SOURCE_SHA> \
  --release-id <RELEASE_ID> \
  --manifest-sha256 <MANIFEST_SHA256> \
  --pointer-sha256 <POINTER_SHA256> \
  --operator-id <OPERATOR_ID> \
  --evaluator-id <EVALUATOR_ID> \
  --transcript-output .artifacts/m17/independent-operator-transcript.json \
  --report-output .artifacts/m17/final-ga-acceptance.json
```

Both reports are canonical JSON with SHA-256 identities. Any gap, identity drift, undocumented hint,
unsafe continuation, real mutation claim, missing stage, missing capability, or tampering is a hard
stop.
