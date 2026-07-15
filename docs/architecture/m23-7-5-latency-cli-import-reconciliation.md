# M23.7.5 Latency CLI Import Repair Reconciliation

Issue: #438. Parent: #430.

## Observed failure

After the latency-evidence implementation merged, the local diagnostic CLI stopped at
Python import time because it requested `StrictModeSafeLiveShadowClient`, while the
strict-mode module exports `StrictModeSafeHttpLiveShadowClient`.

The attempt ended before any Cloudflare or Qdrant request. No production, Qdrant
write/delete, R2, Source, pointer or answer-serving mutation occurred.

## Accepted repair

Implementation PR #439:

- imports and instantiates the actual strict-mode-safe HTTP client;
- adds a regression test that loads the CLI module itself;
- changes no canonical latency budget, privacy contract, request behavior or authority
  boundary.

## Accepted implementation evidence

- implementation issue: #438;
- implementation PR: #439;
- accepted implementation head: `7832410904530d39075123957fb18ae90aab223a`;
- implementation merge: `8085990ac6cdf88272f7fd6063c14b2a6eedd014`.

Accepted exact-head runs:

- M23.7.5 Latency Diagnostic Evidence `29403663963` (run 3), success;
- CI `29403663968` (run 896), success;
- M18 Graph v2 acceptance `29403664057` (run 332), success.

The dedicated gate executes the CLI import regression test, so the original symbol
mismatch is directly covered.

## Remaining parent gate

Issue #430 remains open. The operator must pull main and rerun the latency diagnostic.
Only the resulting redacted receipt can support an evidence-based latency decision and
final M23.7.5 reconciliation. M23.7.6 remains blocked.

Production mutation dispatched: false.
