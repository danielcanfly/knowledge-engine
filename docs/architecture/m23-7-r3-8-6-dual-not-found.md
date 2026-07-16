# M23.7-R3.8.6 Dual Worker-Not-Found Classification

## Trigger

The R3.8.5 operator reached the read-only Wrangler `versions list` absence probe and stopped with a non-zero result that was not classified as absence. The stop occurred before deployment, secret creation, Qdrant access or live observation.

## Root cause

Cloudflare Workers SDK defines two canonical Worker-not-found error codes:

- `10007`: Worker missing on the target account.
- `10090`: legacy Worker environment missing on the target account.

The prior probe accepted only `10007`.

## Classification contract

The probe accepts `absent` only when all conditions hold:

1. Wrangler exits non-zero.
2. The bounded output has no HTTP 403, forbidden, unauthorized or authentication signal.
3. Exactly one five-digit Cloudflare error code is present.
4. That single code is either `10007` or `10090`.

The probe rejects duplicated records, mixed `10007` and `10090`, any additional error code and all ambiguous output.

A successful non-empty JSON versions array remains the only `present` result. A successful empty array is ambiguous and rejected.

## Preservation boundary

This repair does not change:

- the R3.8 runtime or transient Worker;
- the 24 frozen queries or rank-quality gates;
- the 1200 ms Worker-internal shadow latency threshold;
- the Wrangler bootstrap or deploy-target parser;
- Qdrant, R2, pointer, Source or production state;
- blocker, serving or promotion authority.

Raw Wrangler output, URLs, hostnames, account IDs, tokens and secrets are not persisted.
