# M6-001 Batch Spec: LLM Wiki Foundation

Status: `draft / not approved`

Parent tracker: `#42`

Child slice: `#45`

This is the first named M6 batch spec draft. It does not approve Source content, does not authorize a candidate build, does not create a production request spec, and does not authorize production promotion.

## 1. Batch identity

- Batch ID: `m6-001-llm-wiki-foundation`
- Batch title: `LLM Wiki Foundation Batch`
- Owner / operator: `danielcanfly`
- Created at: `2026-07-06`
- Parent issue: `#42`
- Child issue: `#45`
- Related Source PR: `pending`
- Related Engine PR: `pending`

## 2. Scope

### Intended content family

This batch is reserved for the next reviewed Source batch related to the LLM Wiki / Knowledge OS foundation. The concrete Source files must be selected in a Source PR before this spec can move beyond draft.

### Included content

Pending Source PR selection. Candidate examples for later review may include:

- LLM Wiki foundation notes
- Knowledge OS governance notes
- production-RAG / agent architecture reference notes
- operational glossary entries that support later public Q&A

These examples are not approval to add or promote content.

### Excluded content

- Private credentials, tokens, secrets, account identifiers, or private personal data
- Draft chat logs copied directly into canonical Source without review
- Any Source content not represented in a reviewed Source PR
- Any production promotion request
- Any content volume expansion before M6 readiness is satisfied

### Risk notes

- The scope is still draft because no Source PR exists yet.
- Acceptance queries are provisional until the exact Source content is known.
- The batch must not rely on chat memory as evidence.

## 3. Source identity

- Source repository: `danielcanfly/knowledge-source`
- Source branch: `pending`
- Source PR: `pending`
- Expected Source SHA after merge: `pending`
- Source validation workflow run ID: `pending`
- Source validation conclusion: `pending`

Required before candidate build:

- Source PR reviewed
- Source PR merged
- Source validation success
- exact Source SHA recorded

## 4. Builder and Foundation identity

Current baseline from M5 closeout:

- Builder repository: `danielcanfly/knowledge-engine`
- Expected Builder SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Expected Foundation SHA: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`
- Builder / Foundation rotation required: `pending`
- Rotation PR: `pending / n/a`

If Builder or Foundation SHA changes, the rotation must be reviewable and must fail loudly if Source policy and Engine expectations diverge.

## 5. Candidate identity

- Candidate channel: `candidate-source-<source-sha>`
- Candidate workflow run ID: `pending`
- Candidate artifact ID: `pending`
- Candidate artifact digest: `pending`
- Candidate release ID: `pending`
- Candidate manifest SHA-256: `pending`
- Candidate quality overall: `pending`

Candidate channel must be derived from the reviewed Source SHA, not from a manually guessed value.

## 6. Public acceptance

Provisional acceptance candidates. Final values must be updated after Source scope is selected.

- Public query: `what is the LLM Wiki foundation for Knowledge OS?`
- Expected public status: `answered`
- Expected citation URL: `pending Source-backed URL or canonical citation target`
- Citation count: `pending`
- Raw fallback used: `must be false`
- Acceptance result artifact: `pending`

Acceptance requires the expected citation URL and raw fallback must be `false`.

## 7. ACL negative acceptance

Provisional ACL negative query. Final value must be updated after Source scope is selected.

- ACL negative query: `private operator token for LLM Wiki production pipeline`
- Expected ACL status: `not_found`
- ACL filtered count: `pending`
- ACL raw fallback used: `must be false`
- ACL result artifact: `pending`

If ACL negative query is configured, acceptance requires the expected status and raw fallback must be `false`.

## 8. Production request spec plan

No production request spec exists yet.

- Request spec path: `pending`
- Operation ID: `pending`
- Expected previous release ID: `20260706T024200Z-19b86982de27`
- Expected previous manifest SHA-256: `8697f5ab6258d8545328fd32cea60b09c2c80aef4599611b0571a0553ea24a7e`
- Target release ID: `pending`
- Target manifest SHA-256: `pending`
- Actor: `pending`
- Reason: `pending`

Forbidden field:

- `control_plane_sha` must not be committed in the request spec.

## 9. Rollout assumptions

- Current production release before promotion: `20260706T024200Z-19b86982de27`
- Current production manifest before promotion: `8697f5ab6258d8545328fd32cea60b09c2c80aef4599611b0571a0553ea24a7e`
- Production precondition source: `pending workflow evidence`
- Rollback expected previous release: `20260706T024200Z-19b86982de27` unless production changes before M6-001
- Rollback evidence required: `yes`

## 10. Governance checklist

- [ ] Source changes are reviewable through PR.
- [ ] No AI-generated content is written directly to canonical Source or production.
- [ ] Source validation passed.
- [ ] Candidate identity is verified from candidate channel and manifest.
- [ ] Candidate quality is `passed`.
- [ ] Public query expected citation URL is present.
- [ ] Public raw fallback is `false`.
- [ ] ACL negative query passes if configured.
- [ ] ACL raw fallback is `false` if configured.
- [ ] Production identity is committed in request spec.
- [ ] Production workflow is dispatched by `request_path` only.
- [ ] Automated ledger comment to `#30` is expected after production workflow success.
- [ ] Replay / rollback proof remains green on `main`.

## 11. Decision

- Batch spec status: `draft / not approved`
- Reviewer: `pending`
- Decision date: `pending`
- Notes: `This spec only creates the first named M6 batch envelope. It does not approve Source content, candidate build, request-spec creation, or production promotion.`

## 12. Next required action

Before M6-001 can move to Source execution, create a Source PR that selects the actual Source files and update this spec with:

- Source PR URL
- Source branch
- proposed Source content list
- final public acceptance query
- final expected citation URL
- final ACL negative query
- Builder / Foundation rotation decision
