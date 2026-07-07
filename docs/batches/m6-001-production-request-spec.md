# M6-001 Production Request Spec

Status: `ready for review / production not dispatched`

Parent tracker: `#42`

M6.13 tracker: `#69`

Runtime acceptance evidence: `docs/batches/m6-001-runtime-acceptance-evidence.md`

Committed request path: `production_promotions/m6-001-llm-wiki-foundation.json`

This document records the M6.13 production request specification for `m6-001-llm-wiki-foundation`. It does not dispatch the production workflow and does not change production state.

## 1. Readiness evidence

M6.12 passed before this request was created:

- Runtime acceptance run ID: `28843971131`
- Runtime acceptance job ID: `85543665085`
- Runtime acceptance artifact ID: `8128851263`
- Runtime acceptance artifact digest: `sha256:81426a0cbd093b6ab0cac124f69d0c32949e502c976c34039d6975bcb4ce256e`
- Runtime acceptance summary: `passed`
- Public query 1: `answered`, citations present, raw fallback false
- Public query 2: `answered`, required blog citation present, raw fallback false
- Boundary query: `not_found`, empty results, ACL filtered count 1, raw fallback false

## 2. Production baseline re-read

The governed M6 tracker and M5 production closure identify the current production baseline as:

- Production release ID: `20260706T024200Z-19b86982de27`
- Production manifest SHA-256: `8697f5ab6258d8545328fd32cea60b09c2c80aef4599611b0571a0553ea24a7e`

Repository review found no later committed production-promotion request or later production-promotion PR after the M5 promotion. This identity is therefore pinned as the request precondition.

M6.14 must still live-read `channels/production.json` from R2 immediately before mutation. The existing workflow hard-fails when the live pointer matches neither this expected previous identity nor the exact requested target identity.

## 3. Target candidate identity

- Candidate channel: `candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`
- Candidate release ID: `20260706T061437Z-bc48bf4810c0`
- Candidate manifest SHA-256: `8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96`
- Source repository: `danielcanfly/knowledge-source`
- Source SHA: `6a35f9f35e4c6c599a266710344f760c399d914d`
- Builder SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Foundation SHA: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`

All target values match the candidate-build and M6.12 runtime-acceptance evidence.

## 4. Request identity

- Schema: `production-promotion-request/v1`
- Request path: `production_promotions/m6-001-llm-wiki-foundation.json`
- Operation ID: `m6-001-llm-wiki-foundation-001`
- Actor: `danielcanfly`
- Reason: promote the reviewed M6-001 candidate after passing runtime acceptance run `28843971131`

The committed request does not contain `control_plane_sha`. The workflow injects the runtime control-plane SHA from `GITHUB_SHA` during request validation.

## 5. Post-promotion acceptance contract

Public query:

```text
How should LLM agent architectures be reviewed across six engineering dimensions?
```

Required result:

- status: `answered`
- exact citation URL: `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/`
- raw fallback used: `false`

ACL boundary query:

```text
delivery controls
```

Required result:

- status: `not_found`
- raw fallback used: `false`
- no unauthorized fixture-only content returned

These values reuse queries that passed against the exact candidate release during M6.12.

## 6. Validation contract

The request must pass `knowledge-engine validate-promotion-request` and repository CI before merge.

The request validator enforces:

- relative path under `production_promotions/*.json`
- exact schema version
- all required fields
- immutable release-ID format
- exact SHA and SHA-256 formats
- Source repository allowlist
- safe operation ID
- valid public and ACL expected statuses
- absence of committed `control_plane_sha`

A repository test loads this exact request through the production validator and asserts its candidate, previous-production, citation, and ACL identities.

## 7. Non-authorization

M6.13 authorizes only review and merge of the committed request specification.

It does not authorize:

- dispatching `M5 Production Promotion`
- writing `channels/production.json`
- posting a production ledger entry
- declaring M6.14 complete

## 8. M6.14 handoff

After this request is reviewed, merged, and CI is green, M6.14 may dispatch production promotion using only:

```text
request_path=production_promotions/m6-001-llm-wiki-foundation.json
```

M6.14 must then collect and verify request validation, live production precondition, candidate identity, promotion result, post-refresh identity, public citation acceptance, ACL acceptance, artifact digest, and ledger entry.
