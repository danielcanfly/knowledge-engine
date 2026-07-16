# M23.7-R3.8.9 Cloudflare Recovery Schema Repair

## Trigger

Read-only recovery run `29509724551` received HTTP 200 from both Workers API
endpoints but returned `worker_state_indeterminate`. The sealed parser expected the
Cloudflare envelope's `result` field itself to be an array.

Cloudflare's official Workers API schemas instead return:

```text
GET .../versions     → result.items[]
GET .../deployments  → result.deployments[]
```

The fail-closed result was correct for the accepted parser but did not determine the
Worker state.

## Repair

The parser now requires an endpoint-specific collection key:

- versions accepts exactly `result.items`;
- deployments accepts exactly `result.deployments`.

A successful empty collection classifies as `absent`. A non-empty collection
classifies as `present` only when every entry is an object with a unique non-empty
`id`. Wrong collection keys, extra result keys, malformed collection types, missing
identities, duplicate identities, mixed errors and unexpected success envelopes all
remain indeterminate.

HTTP 404 with only Cloudflare code `10007` or `10090` remains an accepted absent
result.

## New read-only workflow

Workflow: `M23.7 R3.8.9 Recovery Probe`

```text
affected_run_id = 29506217284
confirmation = PROBE_R3_8_RUN_29506217284_SCHEMA_V2
```

It is fixed to Worker `knowledge-engine-r3-8-29506217284`, first-attempt only and
exact-head only. It performs two GET requests and uploads a non-hidden privacy-safe
artifact.

## Frozen boundaries

No Worker deploy, delete, secret mutation or route invocation is authorized. No
Qdrant or R2 access is authorized. Production retrieval remains lexical, the
`1200 ms` gate is unchanged, and both blockers remain active.

The new workflow may run only after this repair is merged and independently
reconciled.
