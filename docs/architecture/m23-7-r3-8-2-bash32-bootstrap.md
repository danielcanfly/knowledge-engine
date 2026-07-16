# M23.7-R3.8.2 macOS Bash 3.2 bootstrap compatibility

## Trigger

The R3.8.1 operator stopped before any Cloudflare or Qdrant operation because the macOS system Bash 3.2 rejects the Bash 4-only `declare -g` option.

No diagnostic Worker existed, no Worker secret was written, no Qdrant request was dispatched, and no live observation began.

## Repair

The resolver keeps the Wrangler invocation as an indexed Bash array but declares it at file scope using Bash 3.2-compatible `declare -a`.

The accepted resolution order remains unchanged:

1. a valid single-token `WRANGLER_BIN` override;
2. a global `wrangler` executable;
3. pinned `npx --yes wrangler@4.111.0`.

Every resolved path must report Wrangler version `4.111.0`. Shell-syntax-shaped overrides, missing tools, failed version probes and version drift remain fail-closed. The resolver never uses `eval`.

## Validation

The Linux job retains the full adversarial resolver tests and accepted R3.8 Python and Node regressions. A separate macOS job runs the resolver with the system `/bin/bash`, verifies the expected Bash 3.2 lineage, and exercises the pinned npx fallback through a fake executable.

Static validation rejects `declare -g`, associative arrays, namerefs, `mapfile`, `readarray` and evaluation-based command construction.

## Frozen boundaries

The R3.8 runtime, diagnostic Worker, query identities, quality metrics, payload rules, Worker-internal `1200 ms` latency maximum and authority boundary are byte-preserved from the accepted implementation.

This hotfix authorises no deployment, secret mutation, Qdrant access, blocker clearance, serving, promotion, parent closure or M23.7 closure.
