# M12.3 Operator Runbook

## Purpose

Use the M12.3 baseline check when a golden query suite report needs to be compared against an approved quality floor.

## Steps

1. Generate an M12.2 golden query suite report through the ACL-aware Runtime API.
2. Select the immutable baseline contract approved for that suite and release.
3. Run `evaluate_golden_query_baseline(baseline=baseline, report=report)`.
4. Treat `passed=false` or `release_blocking=true` as a hard stop.
5. Preserve the returned artifact as evaluation evidence.

## Hard stops

Do not proceed if the check reports any failure reason. Do not edit the baseline in place to make a failing report pass. Create a separately reviewed baseline only when the quality floor is intentionally changed.

## Out of scope

This runbook does not publish, promote, roll back, or append production ledger entries.
