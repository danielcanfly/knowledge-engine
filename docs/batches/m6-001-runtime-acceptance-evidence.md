# M6-001 Runtime Acceptance Evidence

Status: `passed`

Parent tracker: `#42`

Runtime acceptance issue: `#62`

Batch spec: `docs/batches/m6-001-llm-wiki-foundation-batch.md`

## Candidate identity

- Candidate channel: `candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`
- Candidate release ID: `20260706T061437Z-bc48bf4810c0`
- Candidate manifest SHA-256: `8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96`
- Source SHA: `6a35f9f35e4c6c599a266710344f760c399d914d`
- Runtime acceptance Engine SHA: `522c05cdd3d7d6e4d8bc8b5b05c598cfee70ad30`

## Workflow evidence

- Workflow: `M6 Runtime Acceptance`
- Workflow file: `.github/workflows/m6-runtime-acceptance.yml`
- Workflow run ID: `28843971131`
- Workflow conclusion: `success`
- Runtime acceptance job ID: `85543665085`
- Runtime acceptance job conclusion: `success`
- Artifact ID: `8128851263`
- Artifact name: `m6-runtime-acceptance-candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`
- Artifact digest: `sha256:81426a0cbd093b6ab0cac124f69d0c32949e502c976c34039d6975bcb4ce256e`
- Artifact size: `2756` bytes
- Artifact expiry: `2026-08-06T05:32:24Z`

## Artifact inventory

The uploaded workflow artifact contains:

- `public_query_1.json`
- `public_query_2.json`
- `boundary_query.json`
- `summary.json`

## Acceptance summary

`summary.json` reports:

- status: `passed`
- channel: `candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`
- release ID: `20260706T061437Z-bc48bf4810c0`
- manifest SHA-256: `8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96`

## Public query 1

Query:

```text
What is the Knowledge Source governance boundary in Knowledge OS?
```

Observed:

- status: `answered`
- raw fallback used: `false`
- citation count: `2`
- expected Source governance identity present: `true`
- concept ID present: `concepts/source-governance`
- x-kos ID present: `ko_01JXYZ123456789ABCDEFGHJKM`
- Source governance citation URI: `https://github.com/danielcanfly/knowledge-os-foundation`
- release identity matched the candidate release and manifest

## Public query 2

Query:

```text
How should LLM agent architectures be reviewed across six engineering dimensions?
```

Observed:

- status: `answered`
- raw fallback used: `false`
- citation count: `1`
- concept ID: `concepts/six-dimensional-map-of-llm-agent-architectures`
- required citation URI present: `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/`
- release identity matched the candidate release and manifest

## Boundary query

Query:

```text
delivery controls
```

Observed:

- status: `not_found`
- non-answer reason: `no_authorized_match`
- results: `[]`
- ACL filtered count: `1`
- candidate count: `0`
- selected count: `0`
- raw fallback used: `false`
- release identity matched the candidate release and manifest

The boundary result proves that the internal-only fixture was considered by retrieval and then removed by authorization filtering. No fixture-only content was returned to the public audience.

## Repair history

Two earlier workflow runs failed because broad boundary queries lexically matched public Source governance content even though ACL filtering was working:

- run `28820156111`
- run `28843425135`

The final repair narrowed the boundary negative query without changing runtime ACL logic or weakening the acceptance conditions.

Related repair PRs:

- `#66`, merged as `235fd20b8f09c2ce2ec3f7228df1a7bf882bf996`
- `#67`, merged as `522c05cdd3d7d6e4d8bc8b5b05c598cfee70ad30`

## Decision

M6.12 runtime acceptance is `passed`.

This evidence does not create a production request spec and does not authorize production promotion by itself. The batch may now advance to production request specification planning under the next governed milestone.
