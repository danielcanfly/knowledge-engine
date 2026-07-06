# M6-001 Batch Spec: LLM Wiki Foundation

Status: `source paths reviewed / source validation required`

Parent tracker: `#42`

Child slices: `#45`, `#56`

This is the first named M6 batch spec. It now references reviewed Source paths from the M6.6 path review and the M6.7 proposal update. It does not edit Source, does not authorize a candidate build, does not create a production request spec, and does not authorize production promotion.

## 1. Batch identity

- Batch ID: `m6-001-llm-wiki-foundation`
- Batch title: `LLM Wiki Foundation Batch`
- Owner / operator: `danielcanfly`
- Created at: `2026-07-06`
- Parent issue: `#42`
- Initial batch spec issue: `#45`
- Batch spec update issue: `#56`
- Source PR: `not required yet / pending validation decision`
- Related Engine PRs: `#54`, `#55`, `pending #56`

## 2. Scope

### Intended content family

This batch covers the first reviewed Source-backed slice for LLM Wiki / Knowledge OS foundation material.

### Reviewed primary content paths

- `bundle/concepts/six-dimensional-map-of-llm-agent-architectures.md`
- `bundle/concepts/source-governance.md`

### Reviewed supporting paths

- `bundle/index.md`
- `README.md`
- `registry/sources.json`
- `registry/reviews.json`
- `provenance/six-dimensional-map-of-llm-agent-architectures.json`
- `provenance/source-governance.json`

### Reviewed fixture-only path

- `bundle/concepts/candidate-delivery-controls.md`

### Excluded content

- Sensitive private material
- Raw chat logs copied directly into canonical Source
- Any unreviewed Source path not represented in M6.6 / M6.7 planning evidence
- Any production request spec
- Any content expansion before Source validation evidence is collected

### Risk notes

- Source paths have been reviewed, but Source validation evidence has not yet been recorded in this batch spec.
- Candidate build remains blocked until Source validation evidence exists.
- Acceptance queries are now narrowed to two query families, but final query strings remain candidate-evidence work.
- The batch must not rely on chat memory as evidence.

## 3. Source identity

- Source repository: `danielcanfly/knowledge-source`
- Source branch: `main`
- Source HEAD reviewed: `6a35f9f35e4c6c599a266710344f760c399d914d`
- Inventory timestamp: `20260706T152049Z`
- Inventory checksum: `375dfe63eaeae00e1aa5a350d98e60f43412f6bc19f15689279fd44ceca9eb57`
- Path review PR: `#54`
- Path review merge commit: `48410e213132dbbd062afb21b2cb4c95e4b399fb`
- Proposal update PR: `#55`
- Proposal update merge commit: `1e342a6a6b36b379a7e4b18e33717e95144843e5`
- Source validation workflow run ID: `pending`
- Source validation conclusion: `pending`

Required before candidate build:

- Source validation success
- exact Source SHA confirmed at validation time
- final Source path table retained
- final query strings recorded
- Builder / Foundation rotation decision recorded

## 4. Builder and Foundation identity

Current baseline from M5 closeout:

- Builder repository: `danielcanfly/knowledge-engine`
- Expected Builder SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Expected Foundation SHA: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`
- Builder / Foundation rotation required: `pending`
- Rotation PR: `pending / n/a`

If Builder or Foundation SHA changes, the rotation must be reviewable and must fail loudly if Source policy and Engine expectations diverge.

## 5. Candidate identity

- Candidate channel: `candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`
- Candidate workflow run ID: `pending`
- Candidate artifact ID: `pending`
- Candidate artifact digest: `pending`
- Candidate release ID: `pending`
- Candidate manifest SHA-256: `pending`
- Candidate quality overall: `pending`

Candidate channel must be derived from the reviewed Source SHA and must be rechecked after Source validation.

## 6. Public acceptance

Primary public query family:

- Public query family: `Knowledge Source governance boundary in Knowledge OS`
- Expected public status: `answered`
- Expected citation target: `bundle/concepts/source-governance.md` or Source-backed runtime citation target
- Citation count: `pending`
- Raw fallback used: `must be false`
- Acceptance result artifact: `pending`

Secondary public query family:

- Public query family: `six-dimensional review of LLM agent architectures`
- Expected public status: `answered`
- Expected citation target: `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/`
- Citation count: `pending`
- Raw fallback used: `must be false`
- Acceptance result artifact: `pending`

Final query strings must be locked during the candidate evidence step.

## 7. Boundary acceptance

Reviewed fixture-only path:

- `bundle/concepts/candidate-delivery-controls.md`

Expected boundary behavior:

- Public-audience query should return `not_found` or equivalent negative result.
- Raw fallback used: `must be false`.
- Fixture-only content must not be returned as public content.
- Boundary result artifact: `pending`.

The exact query string must be locked during the candidate evidence step.

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

- [x] Source paths are reviewed in Engine planning evidence.
- [ ] Source validation passed.
- [ ] Builder / Foundation rotation decision recorded.
- [ ] Candidate identity is verified from candidate channel and manifest.
- [ ] Candidate quality is `passed`.
- [ ] Public query expected citation target is present.
- [ ] Public raw fallback is `false`.
- [ ] Boundary query passes if configured.
- [ ] Boundary raw fallback is `false` if configured.
- [ ] Production identity is committed in request spec.
- [ ] Production workflow is dispatched by `request_path` only.
- [ ] Automated ledger comment to `#30` is expected after production workflow success.
- [ ] Replay / rollback proof remains green on `main`.

## 11. Decision

- Batch spec status: `source paths reviewed / source validation required`
- Reviewer: `pending`
- Decision date: `pending`
- Notes: `This spec now names reviewed Source paths. It does not approve candidate build, request-spec creation, or production promotion.`

## 12. Next required action

Collect Source validation evidence for `danielcanfly/knowledge-source` at Source HEAD `6a35f9f35e4c6c599a266710344f760c399d914d`, then update candidate evidence planning with:

- Source validation workflow run ID
- Source validation conclusion
- final public acceptance query strings
- final citation target mapping
- final boundary query string
- Builder / Foundation rotation decision
