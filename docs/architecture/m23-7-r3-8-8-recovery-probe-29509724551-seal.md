# M23.7-R3.8.8 Recovery Probe 29509724551 Evidence Seal

## Sealed evidence

- affected observation run: `29506217284`
- recovery probe run: `29509724551`
- probe engine: `4bbabf12a526135b5f31c68b1e9b371d6fc6e5d9`
- artifact ZIP SHA-256: `64fb4af6fb120cfb255b7d5e68e146d5e730c684bec584e7cc24df7e4e29bd47`
- receipt file SHA-256: `ac2852f1fc32c4a87474de62b173d5add5009fb2fcec27099f3e4219c549ebeb`
- receipt self-digest: `4889aaf284675563120accc1252a250e5e5d906c28f6688de9323a5b97d4102c`
- evidence seal digest: `41149bd725bde45e5eb8552d4a0a3d21a714481da5be65615eac5ee7fbd59b38`

The receipt is a complete fail-closed recovery result. Both Cloudflare control-plane
requests returned HTTP 200, but the parser classified each response as indeterminate
and preserved no identity.

## Independent schema diagnosis

Cloudflare's official Workers API contracts return:

```text
versions:    result.items[]
deployments: result.deployments[]
```

The accepted R3.8.8 probe expected `result` itself to be an array. Therefore the two
successful responses were safely rejected as schema drift. This seal does not infer
that the Worker is absent or present.

## Strict-zero result

The receipt records false for observation replay, Worker deployment, secret mutation,
Worker deletion, Worker route invocation, Qdrant read/mutation, R2 read/mutation and
all protected mutations.

Production retrieval remains lexical. The `1200 ms` Worker-internal maximum is
unchanged. Both blockers remain active.

## Next authority

This seal authorizes no new probe, fresh observation or Worker deletion. A separate
parser repair and independent reconciliation are required before another read-only
probe can be dispatched.
