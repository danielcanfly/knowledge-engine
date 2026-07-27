# M26.PA.2 Exact Live Read-Only Evidence

This batch authorises logical attempt 5 for exact PA.2 live evidence after implementation PR
`#1187`
merged at head `11db7672f0a24c4531ac0203ca89e2c4d0a6e975` as main seal
`ecad7b2bfb2e6d472bf0ed76d2e0adc818124dd9`.

## Owner authority

Daniel's 2026-07-27 clarification, `這個我叫它 QDRANT_API_KEY_READ 已經給你了`, is
recorded only as authority to construct and merge the PA.2 logical attempt 5 read-only
evidence authorization. The exact GitHub environment secret was then provisioned under the
required name `QDRANT_READ_ONLY_API_KEY`.
It does not borrow PA.3 provider authority and does not accept PA.2 by itself.

Logical attempt 2 is immutable: GitHub Actions run `30249384010` failed closed before
runtime installation and before any data-plane operation. It must not be rerun.
Logical attempt 3 is also immutable: GitHub Actions run `30252530599` failed closed after
one R2 read, before any Qdrant count or scroll, because the frozen payload policy required
`article_id` while the production Qdrant payloads omit that field.
Logical attempt 4 is also immutable: GitHub Actions run `30258197935` failed closed after
one R2 read, before any Qdrant count or scroll, because the GitHub environment read-only
R2 secrets were stale; they were then re-synced from `.env` under the same names.

## Exact run

- workflow: `M26.PA.2 Exact Live Read-Only Evidence`
- environment: `m23-r3-diagnostic`
- logical attempt: `5`
- GitHub run attempt: `1`
- trigger marker: `[m26.pa2-live-authorized-attempt-5]`
- R2 operations: two exact `get` calls
- Qdrant operations: exact filtered `count` and complete bounded `scroll`
- expected population: `4,197`
- page size: `256`
- deterministic metadata sample: `5`
- payload fields: `section_id`, `source_id`, `release_id`, `source_commit_sha`,
  `admission_sha256`, `candidate_release_eligible`, `production_authority`, `text_sha256`
- vectors: disabled
- raw source-body reads: disabled

The workflow is installed through a normal pull request. Its pull-request job validates the
authorization without secrets. The live job can run only on the fresh main push whose merge
commit contains the exact attempt-5 trigger marker.

## Credential boundary

Only the following environment secrets may be read:

- `R2_ENDPOINT_URL`
- `R2_BUCKET`
- `R2_ACCESS_KEY_ID_READ`
- `R2_SECRET_ACCESS_KEY_READ`
- `QDRANT_URL`
- `QDRANT_READ_ONLY_API_KEY`

No write-scoped substitute is permitted. Missing read-only credentials fail closed. The
read-only R2 and Qdrant secret values must never be logged, committed, printed, attached to
artifacts, or copied into issues, pull requests, or handoffs.

## Workflow compatibility boundary

The live evidence workflow recognises only this exact attempt-5 authorization surface. It
does not admit arbitrary `m26-pa-2-*` changes and retains `contents: read`.

## Evidence boundary

Success produces a strict self-digested metadata-only receipt. Failure produces a sanitized
failure receipt. Both record exact workflow, head, attempt, release, pointer, manifest,
population, pagination, sample, and non-mutation identities. Neither receipt may contain raw
corpus text, vectors, or secret values.

The artifact is retained for 90 days. A successful live artifact still does not accept PA.2.
An independent reconciliation must bind the implementation, this exact run, artifact identity,
zero review threads, and mutation record before recording
`m26_pa_2_real_corpus_retrieval_binding_accepted`.
