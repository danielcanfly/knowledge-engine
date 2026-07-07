# M6-001 Batch Spec: LLM Wiki Foundation

Status: `production promoted and verified`

Parent tracker: `#42`

Runtime acceptance evidence: `docs/batches/m6-001-runtime-acceptance-evidence.md`

Production request evidence: `docs/batches/m6-001-production-request-spec.md`

Production status: `docs/batches/m6-001-production-status.md`

## 1. Batch identity

- Batch ID: `m6-001-llm-wiki-foundation`
- Batch title: `LLM Wiki Foundation Batch`
- Owner / operator: `danielcanfly`
- Source repository: `danielcanfly/knowledge-source`
- Source SHA: `6a35f9f35e4c6c599a266710344f760c399d914d`
- Builder SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Foundation SHA: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`

## 2. Reviewed scope

Primary concepts:

- `bundle/concepts/six-dimensional-map-of-llm-agent-architectures.md`
- `bundle/concepts/source-governance.md`

Supporting files:

- `bundle/index.md`
- `README.md`
- `registry/sources.json`
- `registry/reviews.json`
- `provenance/six-dimensional-map-of-llm-agent-architectures.json`
- `provenance/source-governance.json`

Fixture-only boundary concept:

- `bundle/concepts/candidate-delivery-controls.md`

## 3. Source validation

- Validation run ID: `28771739838`
- Validation job ID: `85306679196`
- Validation conclusion: `success`
- Validation artifact ID: `8101046344`
- Validation artifact digest: `sha256:d8012852c831df3b16ef46ea2b0849783dfb169ce9c3e3f0862e0f222114acfa`
- Inventory checksum: `375dfe63eaeae00e1aa5a350d98e60f43412f6bc19f15689279fd44ceca9eb57`

## 4. Candidate evidence

- Candidate channel: `candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`
- Candidate workflow run ID: `28771769531`
- Candidate artifact ID: `8101061363`
- Candidate artifact digest: `sha256:ab824a8284a78f6e5c38d547aa89ba119beb2c53084640a40512f9bf0c13ca52`
- Candidate release ID: `20260706T061437Z-bc48bf4810c0`
- Candidate manifest SHA-256: `8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96`
- Candidate quality: `passed`
- Reproducibility: `passed`
- Production pointer unchanged during candidate build: `true`

## 5. Runtime acceptance

Runtime acceptance run:

- Run ID: `28843971131`
- Job ID: `85543665085`
- Conclusion: `success`
- Artifact ID: `8128851263`
- Artifact digest: `sha256:81426a0cbd093b6ab0cac124f69d0c32949e502c976c34039d6975bcb4ce256e`
- Summary status: `passed`

Public query 1:

```text
What is the Knowledge Source governance boundary in Knowledge OS?
```

Observed:

- status: `answered`
- Source governance identity present: `true`
- citations present: `true`
- raw fallback used: `false`

Public query 2:

```text
How should LLM agent architectures be reviewed across six engineering dimensions?
```

Observed:

- status: `answered`
- required blog citation present: `true`
- raw fallback used: `false`

Boundary query:

```text
delivery controls
```

Observed:

- status: `not_found`
- results: `[]`
- ACL filtered count: `1`
- raw fallback used: `false`

## 6. Production request specification

- Request path: `production_promotions/m6-001-llm-wiki-foundation.json`
- Schema: `production-promotion-request/v1`
- Operation ID: `m6-001-llm-wiki-foundation-001`
- Expected previous release: `20260706T024200Z-19b86982de27`
- Expected previous manifest: `8697f5ab6258d8545328fd32cea60b09c2c80aef4599611b0571a0553ea24a7e`
- Target release: `20260706T061437Z-bc48bf4810c0`
- Target manifest: `8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96`
- Committed `control_plane_sha`: `false`

## 7. Production promotion

First promotion run:

- Run ID: `28847474378`
- Promotion status: `promoted`
- Previous release: `20260706T024200Z-19b86982de27`
- Target release: `20260706T061437Z-bc48bf4810c0`

Final idempotent replay:

- Run ID: `28849698444`
- Job ID: `85561748154`
- Workflow conclusion: `success`
- Precondition state: `already_target`
- Promotion status: `already_promoted`
- Idempotent: `true`

Final production identity:

- Release ID: `20260706T061437Z-bc48bf4810c0`
- Manifest SHA-256: `8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96`
- Production pointer SHA-256: `edd628ca3c2b1991866c3d7adbff05ff32f8eef581e80d4ebd4b781dbbf6dcd6`

## 8. Final runtime and ledger evidence

- Public query status: `answered`
- Required citation present: `true`
- Public raw fallback: `false`
- ACL query status: `not_found`
- ACL results empty: `true`
- ACL filtered count: `1`
- ACL raw fallback: `false`
- Ledger issue: `#30`
- Ledger comment ID: `4901314017`
- Promotion artifact ID: `8131019711`
- Promotion artifact digest: `sha256:1b24f5005de070877f304e3a7c8630014d93c6a8489611f90fea45ab729da64c`
- Artifact expiry: `2026-10-05T07:36:49Z`

## 9. Governance checklist

- [x] Source scope reviewed.
- [x] Source validation passed.
- [x] Builder and Foundation identities recorded.
- [x] Candidate identity verified.
- [x] Candidate quality passed.
- [x] Runtime public queries passed.
- [x] Required citations returned.
- [x] Raw fallback remained disabled.
- [x] ACL boundary query returned no public result.
- [x] Production identity committed in a request spec.
- [x] Production workflow dispatched by `request_path` only.
- [x] Production promotion succeeded.
- [x] Idempotent replay succeeded.
- [x] Permanent ledger entry recorded.
- [x] Evidence artifact retained.

## 10. Decision

M6-001 is complete. Production points to the reviewed release, runtime acceptance passed, the replay path proved idempotency, and the permanent ledger entry exists.

The next governed phase is M7: scale-up and operator automation. M7 entry work must not mutate Source or production.
