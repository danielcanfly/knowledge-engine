# M23.7-R3.8.4 Wrangler-authenticated Worker absence probe

## Trigger

The fourth R3.8 operator attempt passed the accepted macOS Bash 3.2 and real pinned Wrangler bootstrap, then stopped before deployment because a bespoke direct Cloudflare REST absence check returned HTTP 403.

No Worker, Worker secret, Qdrant read, live observation or protected mutation occurred.

## Repair boundary

R3.8.4 replaces only that bespoke REST check with a read-only probe executed through the same accepted pinned Wrangler command array and generated Wrangler configuration that would be used for deployment.

The exact command surface is:

```text
versions list --name <exact-worker-name> --config <generated-config> --json
```

The probe returns:

- `present` only when Wrangler succeeds and returns a non-empty JSON array of versions;
- `absent` only when Wrangler exits non-zero and returns Cloudflare Worker-not-found code `10007`;
- failure for HTTP 403, authentication errors, unknown codes, malformed JSON, an empty versions array, oversized output or invalid arguments.

Raw Wrangler output remains in process memory only. The probe does not print or persist API responses, endpoint URLs, account identifiers, tokens, hostnames or secret values.

## Safety invariants

- Bash 3.2-compatible indexed arrays only.
- No `eval` or shell-source construction from operator inputs.
- Existing or ambiguous Workers cannot be overwritten.
- R3.8 runtime, Worker source, frozen queries, accepted quality metrics and the 1200 ms latency threshold remain byte-identical.
- This hotfix does not deploy a Worker, create secrets, access Qdrant, clear blockers, grant promotion eligibility or close parent #474.

## Validation

Exact-head CI includes:

- adversarial absent, present, HTTP 403, malformed JSON, empty-array, unknown-code, oversized-output and injection-shaped argument cases;
- Linux Bash parsing and repository regressions;
- macOS system Bash 3.2 execution with a controlled Wrangler shim;
- real pinned Wrangler command-surface verification for `versions list --help` and the `--name`, `--config` and `--json` options;
- deterministic contract digest and changed-file allowlist;
- byte-preservation checks for accepted R3.8 and R3.8.3 artifacts.
