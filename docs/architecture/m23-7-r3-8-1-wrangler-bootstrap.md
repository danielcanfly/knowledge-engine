# M23.7-R3.8.1 Wrangler Bootstrap Hotfix

## Trigger

The first R3.8 operator invocation stopped before repository preparation with:

```text
R3.8 ERROR: required command not found: wrangler
```

This was a local bootstrap failure. No diagnostic Worker existed, no Worker secret was written, no live observation ran and no Qdrant access or protected mutation occurred.

## Repair

The hotfix adds `scripts/m23_7_r3_8_wrangler_bootstrap.sh`, which resolves one exact Wrangler 4.111.0 command using the following order:

1. an explicit, single-token `WRANGLER_BIN` executable;
2. a global `wrangler` executable;
3. `npx --yes wrangler@4.111.0`.

The resolved command is stored in the Bash array `M23_R3_8_WRANGLER_CMD`. The resolver does not use `eval`, rejects shell-syntax-shaped overrides and rejects every version other than 4.111.0.

## Preservation

This hotfix does not alter:

- the R3.8 runtime or diagnostic Worker;
- the 24 frozen query identities;
- the accepted R3.5 metrics and target ranks;
- the 1200 ms Worker-internal latency maximum;
- the candidate collection or Qdrant authority;
- evidence, blocker, promotion or closure authority.

The R3.8 operator pack must be rebuilt after the hotfix merge so the runner sources the committed resolver before deployment.

## Tests

Adversarial tests cover:

- global Wrangler precedence;
- pinned npx fallback;
- explicit single-token overrides;
- wrong-version rejection;
- shell-syntax-shaped override rejection;
- failure when neither Wrangler nor npx exists.

Exact-head CI also verifies that the R3.8 runtime and Worker files remain byte-identical to the accepted R3.8 implementation merge.

## Authority

Code, documentation, tests, CI and operator packaging only. No deployment, secrets, Qdrant access, protected mutation, blocker clearance, serving, promotion, parent R3 closure or M23.7 closure is authorized by this hotfix.
