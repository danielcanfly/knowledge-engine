# M12.6 Deterministic Answer Quality and Performance Metrics

Status: implementation candidate  
Issue: #168  
Depends on: #167  
Engine baseline before M12.5–M12.7: `cfc782fa2123ecaa15648a4b976500ce35a7ed10`

## Purpose

M12.6 converts one exact golden query report and bounded explicit observations into deterministic answer-quality and performance evidence. Observations are reviewer- or harness-provided facts, not model-generated verdicts trusted without validation.

## Answer-quality metrics

The artifact reports:

- faithfulness from supported versus unsupported observed claims;
- completeness from covered versus expected facts;
- unsupported-claim rate;
- contradiction handling for cases explicitly marked as contradiction probes;
- unknown/not-found handling for explicitly marked unknown probes;
- response stability across at least two deterministic response hashes per case.

All observations must exactly cover the golden report case set. Counts cannot be negative, observed claims cannot exceed expected claims, and handled flags cannot be asserted when the corresponding probe was not expected.

## Performance metrics

Each observation includes equal-length bounded samples for:

- latency in milliseconds;
- token cost in USD;
- index load time in milliseconds;
- cache-hit booleans;
- response hashes.

The artifact reports P50 and P95 latency using deterministic nearest-rank percentiles, mean token cost, P95 index load time, and cache-hit rate. Samples must be finite and non-negative.

## Threshold gate

Any quality regression or performance-budget violation becomes release-blocking. The policy controls minimum quality ratios and maximum latency, cost, and index-load budgets.

## Determinism and governance

The observation set, exact release identity, metrics, policy, case details, and failure reasons form a stable-JSON identity. Exact replay produces the same `apmetricset_` and `apmetrics_` identities.

The artifact carries the M12 no-write governance boundary and cannot mutate canonical Source, Source PRs, candidates, releases, production, rollback state, or permanent ledger #30.
