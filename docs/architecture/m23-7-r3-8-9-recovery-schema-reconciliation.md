# M23.7-R3.8.9 Recovery Schema Independent Reconciliation

## Reconciled implementation

- issue: #547
- PR: #548
- accepted head: `e4b7a7e9d17b0945284c90ec11ef21981cadc485`
- merge: `500d61c3b05385d7fd05ec976fa6bf54043bdf77`
- schema contract: `8a3134669359fa27817ca307487faae51670f1401c3b8d8e3232060b486097b3`
- reconciliation digest: `6c1d07a5fa213fd04baa35adbeefddc14b2008a61ae2e1c9346aa3543f90a04d`

The seven changed files match PR #548. Exact-head R3.8.9 schema, R3.8.8 incident
regression, global CI, M17 and M18 runs all succeeded.

## Schema conclusions

Versions parse only `result.items[]`. Deployments parse only
`result.deployments[]`. An empty successful collection is absent. A non-empty
collection is present only when every item has a unique non-empty `id`.

Wrong or extra result keys, malformed collection types, missing identities,
duplicate identities, mixed errors and unexpected success envelopes remain
indeterminate. HTTP 404 with only code `10007` or `10090` remains absent.

## Execution authority

No schema-v2 live probe has run. During implementation and reconciliation there was
no Worker deploy, delete, secret mutation or route invocation, and no Qdrant, R2 or
protected access.

After this reconciliation, exactly one manual first-attempt exact-head execution of
`M23.7 R3.8.9 Recovery Probe` is authorized for Worker
`knowledge-engine-r3-8-29506217284` using confirmation
`PROBE_R3_8_RUN_29506217284_SCHEMA_V2`.

No fresh latency observation or Worker deletion is authorized. Production remains
lexical, the `1200 ms` gate is unchanged, and both blockers remain active.
