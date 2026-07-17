# M23.7-R3.8.7 GitHub Actions Remote Operator

## Decision

R3.8 no longer uses a user-operated macOS Terminal pack. The accepted execution
surface is a manual, exact-head GitHub Actions workflow running in the dedicated
`m23-r3-diagnostic` environment.

The six local attempts all stopped before deployment. They exposed a control-plane
design flaw: a fixed Worker name required a brittle "prove absence" step whose
shell, Wrangler and Cloudflare error-shape assumptions differed from the real Mac.
The remote design removes that entire class of failure rather than adding another
parser exception.

## Remote observation path

```text
workflow_dispatch on main
→ exact-head + confirmation + first-attempt guard
→ read frozen ZIP from private R2 diagnostic key
→ verify exact ZIP SHA-256
→ derive knowledge-engine-r3-8-${github.run_id}
→ generate ephemeral placement config
→ pinned Wrangler 4.111.0 deploy
→ set three Worker secrets
→ readiness check
→ one 24-query observation, with bounded retry for deployment propagation 404s
→ privacy-safe receipt + lifecycle artifact
→ retain Worker for seal and reconciliation
```

A GitHub run ID is globally unique within the repository. No fixed-name absence
probe or overwrite path exists. A rerun attempt is rejected before any mutation.

## Private evidence input

The evidence object is read only from:

```text
bucket: llm-wiki-bucket
key: diagnostic/m23-7/r3-8/M23.5_Cloudflare_BGE_M3_20260714T164215Z.zip
sha256: 1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272
```

The workflow authorizes no R2 write, copy or delete. The object key cannot be
overridden to another object. Raw ZIP contents are stored only in the ephemeral
runner directory and are never uploaded as an Actions artifact.

## GitHub environment

Environment: `m23-r3-diagnostic`

Secrets:

- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `QDRANT_URL`
- `QDRANT_API_KEY`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

Variables:

- `R2_BUCKET=llm-wiki-bucket`
- `R2_ENDPOINT_URL`

The Cloudflare token must be bounded to Workers Scripts/Workers AI for the
diagnostic account. The R2 credentials should be read-only and scoped to the
single diagnostic evidence object or prefix where Cloudflare permits it.

## Result semantics

- exit `0`: complete passing result;
- exit `30`: complete fail-closed result;
- exit `23`: incomplete environment, deployment or external-service result.

Complete pass and fail-closed results both retain the Worker. An incomplete result
also retains it when deployment already occurred. The lifecycle artifact records
the exact Worker name and version ID without persisting its URL or hostname.

## Remote deletion

Deletion is a separate `workflow_dispatch` workflow. It cannot accept an ad hoc
Worker name. It requires a committed JSON authorization under:

```text
deletion_authorizations/m23-7/r3-8/*.json
```

The authorization must bind the exact Worker/version, observation receipt,
evidence seal and independent reconciliation, and must explicitly deny every
production, Qdrant, R2, pointer and Source mutation. Deletion then proves
control-plane absence and emits a separate artifact for deletion reconciliation.

## Frozen boundaries

- Worker-internal shadow maximum remains `1200 ms`.
- Live observation retries remain bounded to 9 attempts at 5 seconds each; a
  persistent Worker HTTP 404 still fails closed and retains the Worker.
- R3.5 metrics and target ranks remain exact.
- Query count remains 24 with one Workers AI binding call and one Qdrant batch.
- Qdrant writes, deletes and reindexing remain zero.
- Production retrieval remains lexical.
- Both blockers remain active until a passing receipt is sealed and independently
  reconciled.
- This migration does not close #520, #474 or M23.7.

## Local pack disposition

All R3.8 local operator ZIPs are unsupported after this workflow merges. They are
historical failed bootstrap/control-plane attempts and must not be rerun.
