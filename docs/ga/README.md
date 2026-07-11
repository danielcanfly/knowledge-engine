# Knowledge OS v1 GA Evidence

This directory is the canonical entry point for Knowledge OS v1 general-availability evidence.

M17.6 consolidates the cross-milestone proof for all 20 required GA capabilities. It does not declare
GA. The evidence matrix can establish only that the implementation evidence is complete enough to
enter the independent M17.7 operator drill and final acceptance.

## Canonical artifacts

1. [v1 GA Evidence Matrix](m17/v1-ga-evidence-matrix.md)
2. `m17/ga-evidence-registry.json`, the machine-readable capability evidence contract
3. `.github/workflows/m17-ga-evidence-matrix.yml`, the dedicated acceptance workflow

## Authority and interpretation

- A milestone title or narrative statement is not evidence.
- Every capability must point to an existing contract or module, test, workflow, merged pull request,
  exact merge commit, and stable matrix anchor.
- Missing, broken, unmerged, malformed, conflicting, or gap-bearing evidence blocks readiness.
- `evidence_complete` means the row is ready for the independent drill. It does not mean
  `ga_accepted`.
- Only M17.7 may produce the final independent drill and GA acceptance artifact.
- This evidence layer is read-only and exposes no Source, release, production, pointer, cache, R2,
  credential, approval, ledger, rollback, lifecycle, or closeout executor.

## Validation

Run:

```bash
python scripts/m17_ga_evidence_acceptance.py \
  --root . \
  --registry docs/ga/m17/ga-evidence-registry.json \
  --output .artifacts/m17/ga-evidence-acceptance.json
```

The report is canonical JSON with a SHA-256 identity. A failed row, unresolved gap, or attempted early
GA declaration is a hard stop.