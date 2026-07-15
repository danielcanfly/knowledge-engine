# M23.7.5 Latency Evidence Repair Reconciliation

Issue: #435. Parent: #430.

## Observed condition

The strict-mode-safe live observation completed the real non-production retrieval path
and then failed closed on the canonical 1200 ms shadow p95 budget. The original CLI
raised before writing the already-redacted metrics, so the actual provider, Qdrant and
total p95 values were unavailable for evidence-based review.

No production, Qdrant write/delete, R2, Source, pointer or answer-serving mutation
occurred.

## Accepted repair

Implementation PR #436 added a diagnostic-only wrapper and CLI that:

- run the same maximum eight internal synthetic probes;
- retain the canonical 1200 ms shadow p95 and 25 ms dispatch-overhead budgets unchanged;
- use bounded 30-second diagnostic ceilings only to permit redacted report construction;
- classify the receipt as `pass` or `rejected` against the canonical budgets;
- persist provider, Qdrant, total and dispatch p95 metrics plus bounded violation codes;
- write the receipt before returning a nonzero exit status on rejection;
- persist no raw query, answer, credential, service URL or arbitrary exception text.

## Accepted implementation evidence

- implementation issue: #435;
- implementation PR: #436;
- accepted implementation head: `d4f787354eb42410935a8f5cd61f2f444fac2f61`;
- implementation merge: `3ca67f92f6fcd07aad8de58e2963c3eecfcff54f`.

Accepted exact-head runs:

- M23.7.5 Latency Diagnostic Evidence `29403300872` (run 2), success;
- CI `29403302362` (run 892), success;
- R2 Release Integration `29403300981` (run 603), success;
- M18 Graph v2 acceptance `29403301031` (run 328), success.

The first exact head also exposed an unrelated existing M23.6.2 digest-test flake; it
passed unchanged on the accepted head, confirming no repair scope expansion.

## Remaining parent gate

This repair does not alter the canonical latency budget and does not claim the real live
observation passes. After this reconciliation merges, the operator must run the new
latency diagnostic CLI and provide the redacted receipt. Issue #430 remains open and
M23.7.6 remains blocked until measured evidence is reviewed, any evidence-based decision
is separately governed, and a final successful observation is reconciled.

Production mutation dispatched: false.
