# M26.PA.2 Exact Live Read-Only Evidence

This batch authorises one exact PA.2 live evidence attempt after implementation PR `#1187`
merged at head `11db7672f0a24c4531ac0203ca89e2c4d0a6e975` as main seal
`ecad7b2bfb2e6d472bf0ed76d2e0adc818124dd9`.

## Owner authority

Daniel's 2026-07-27 instruction, `繼續完成PA-2 然後繼續依序從PA-3往下做`, is
recorded only as authority for PA.2 read-only evidence attempt 1. It does not borrow PA.3
provider authority and does not accept PA.2 by itself.

## Exact run

- workflow: `M26.PA.2 Exact Live Read-Only Evidence`
- environment: `m23-r3-diagnostic`
- attempt: `1`
- trigger marker: `[m26.pa2-live-authorized]`
- R2 operations: two exact `get` calls
- Qdrant operations: exact filtered `count` and complete bounded `scroll`
- expected population: `4,197`
- page size: `256`
- deterministic metadata sample: `5`
- vectors: disabled
- raw source-body reads: disabled

The workflow is installed through a normal pull request. Its pull-request job validates the
authorization without secrets. The live job can run only on the main push whose merge commit
contains the exact trigger marker.

## Credential boundary

Only the following environment secrets may be read:

- `R2_ENDPOINT_URL`
- `R2_BUCKET`
- `R2_ACCESS_KEY_ID_READ`
- `R2_SECRET_ACCESS_KEY_READ`
- `QDRANT_URL`
- `QDRANT_READ_ONLY_API_KEY`

No write-scoped substitute is permitted. Missing read-only credentials fail closed.

## Workflow compatibility boundary

The existing PA.2 non-live workflow is changed only to recognise two explicit file sets: the
accepted 12-file implementation surface and this exact six-file live-authorization surface.
It does not admit arbitrary `m26-pa-2-*` changes. Both workflows retain `contents: read`.

## Evidence boundary

Success produces a strict self-digested metadata-only receipt. Failure produces a sanitized
failure receipt. Both record exact workflow, head, attempt, release, pointer, manifest,
population, pagination, sample, and non-mutation identities. Neither receipt may contain raw
corpus text, vectors, or secret values.

The artifact is retained for 90 days. A successful live artifact still does not accept PA.2.
An independent reconciliation must bind the implementation, this exact run, artifact identity,
zero review threads, and mutation record before recording
`m26_pa_2_real_corpus_retrieval_binding_accepted`.
