# M6-001 Runtime Acceptance Plan

Status: `passed`

Parent tracker: `#42`

Previous evidence: `docs/batches/m6-001-candidate-build-evidence.md`

Pass evidence: `docs/batches/m6-001-runtime-acceptance-evidence.md`

This document defines M6.12 runtime acceptance for `m6-001-llm-wiki-foundation`. It does not create a production request spec and does not authorize production promotion.

## Candidate identity

- Candidate channel: `candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`
- Candidate release ID: `20260706T061437Z-bc48bf4810c0`
- Candidate manifest SHA-256: `8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96`
- Source SHA: `6a35f9f35e4c6c599a266710344f760c399d914d`
- Builder SHA at candidate build: `1b55c68a441def01a5277c94b350efab1437459d`
- Foundation SHA: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`

## Runtime acceptance queries

Public query 1:

```text
What is the Knowledge Source governance boundary in Knowledge OS?
```

Required and observed:

- status: `answered`
- result set includes concept ID `concepts/source-governance`
- at least one citation is present
- raw fallback: `false`
- release identity matches candidate release ID and manifest SHA-256

Rationale: Source provenance for `concepts/source-governance` cites `https://github.com/danielcanfly/knowledge-os-foundation`, so Q1 does not require the citation URI itself to contain the string `source-governance`.

Public query 2:

```text
How should LLM agent architectures be reviewed across six engineering dimensions?
```

Required and observed:

- status: `answered`
- citation set includes `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/`
- raw fallback: `false`
- release identity matches candidate release ID and manifest SHA-256

Boundary query:

```text
delivery controls
```

Required and observed:

- status: `not_found`
- result set is empty
- ACL filtered count is at least `1`
- raw fallback: `false`
- release identity matches candidate release ID and manifest SHA-256

The original broad boundary wording was replaced after evidence showed lexical collisions with public Source governance content. The final query remains tied to the fixture-only concept while avoiding public terms such as `Knowledge OS`, `M3`, and `candidate`.

## Evidence artifacts collected

The passing runtime acceptance workflow uploaded:

- `public_query_1.json`
- `public_query_2.json`
- `boundary_query.json`
- `summary.json`

Workflow evidence:

- run ID: `28843971131`
- job ID: `85543665085`
- conclusion: `success`
- Engine SHA: `522c05cdd3d7d6e4d8bc8b5b05c598cfee70ad30`
- artifact ID: `8128851263`
- artifact digest: `sha256:81426a0cbd093b6ab0cac124f69d0c32949e502c976c34039d6975bcb4ce256e`
- `summary.json` status: `passed`

## Decision rule

M6.12 passes only when all three runtime query outputs are recorded and `summary.json` reports `status: passed`.

This condition was satisfied by workflow run `28843971131`.

The batch status may advance to `runtime acceptance passed / production request spec pending`.

No production request spec is created by this document, and no production promotion is authorized by this evidence alone.
