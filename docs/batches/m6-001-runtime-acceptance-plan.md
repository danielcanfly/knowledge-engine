# M6-001 Runtime Acceptance Plan

Status: `runtime acceptance workflow pending`

Parent tracker: `#42`

Previous evidence: `docs/batches/m6-001-candidate-build-evidence.md`

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

Expected:

- status: `answered`
- at least one citation
- citation set includes the Source governance concept
- raw fallback: `false`
- release identity matches candidate release ID and manifest SHA-256

Public query 2:

```text
How should LLM agent architectures be reviewed across six engineering dimensions?
```

Expected:

- status: `answered`
- citation set includes `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/`
- raw fallback: `false`
- release identity matches candidate release ID and manifest SHA-256

Boundary query:

```text
What candidate delivery controls are available for public users in Knowledge OS?
```

Expected:

- status: `not_found`
- result set is empty
- ACL filtered count is at least `1`
- raw fallback: `false`
- release identity matches candidate release ID and manifest SHA-256

## Evidence artifacts to collect

The runtime acceptance workflow must upload:

- `public_query_1.json`
- `public_query_2.json`
- `boundary_query.json`
- `summary.json`

## Decision rule

M6.12 passes only when all three runtime query outputs are recorded and `summary.json` reports `status: passed`.

If M6.12 passes, the batch status may advance to `runtime acceptance passed / production request spec pending`.

If M6.12 fails, no production request spec may be created until the failure is reviewed and repaired.
