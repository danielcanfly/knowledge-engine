# M6-001 Batch Spec: LLM Wiki Foundation

Status: `candidate planning complete / candidate build pending`

Parent tracker: `#42`

Child slices: `#45`, `#56`, `#57`, `#59`

This is the first named M6 batch spec. It references reviewed Source paths, Source validation evidence, and candidate evidence planning. It does not edit Source, does not create a production request spec, and does not authorize production promotion.

## 1. Batch identity

- Batch ID: `m6-001-llm-wiki-foundation`
- Batch title: `LLM Wiki Foundation Batch`
- Owner / operator: `danielcanfly`
- Created at: `2026-07-06`
- Parent issue: `#42`
- Initial batch spec issue: `#45`
- Batch spec update issue: `#56`
- Source validation evidence issue: `#57`
- Candidate evidence planning issue: `#59`
- Source PR: `not required yet / selected content already exists on Source main`
- Related Engine PRs: `#54`, `#55`, `#56`, `#58`, `pending #59`

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
- Any content expansion before candidate evidence is collected

### Risk notes

- Source paths have been reviewed.
- Source validation evidence has been recorded for the reviewed Source SHA.
- Candidate evidence planning has locked query strings, citation mapping, boundary query, Builder / Foundation identity, and dispatch plan.
- Candidate build evidence is still pending.
- The batch must not rely on chat memory as evidence.

## 3. Source identity

- Source repository: `danielcanfly/knowledge-source`
- Source branch: `main`
- Source HEAD reviewed: `6a35f9f35e4c6c599a266710344f760c399d914d`
- Source validation workflow run ID: `28771739838`
- Source validation job ID: `85306679196`
- Source validation conclusion: `success`
- Source validation artifact ID: `8101046344`
- Source validation artifact digest: `sha256:d8012852c831df3b16ef46ea2b0849783dfb169ce9c3e3f0862e0f222114acfa`
- Source validation artifact name: `knowledge-source-validation-6a35f9f35e4c6c599a266710344f760c399d914d`
- Source validation artifact expired: `false`
- Inventory timestamp: `20260706T152049Z`
- Inventory checksum: `375dfe63eaeae00e1aa5a350d98e60f43412f6bc19f15689279fd44ceca9eb57`
- Path review PR: `#54`
- Path review merge commit: `48410e213132dbbd062afb21b2cb4c95e4b399fb`
- Proposal update PR: `#55`
- Proposal update merge commit: `1e342a6a6b36b379a7e4b18e33717e95144843e5`
- Batch spec update PR: `#56`
- Batch spec update merge commit: `f51fca2edd15af9473af0cb0cec6f47a5cdeb36c`
- Source validation evidence PR: `#58`
- Source validation evidence merge commit: `3c29abe08e7e46fb1f8446a8dc7753f5c4c24af6`

Required before candidate build:

- Engine-side candidate workflow target confirmed
- candidate build dispatched by governed Source automation or explicitly reviewed manual fallback

## 4. Builder and Foundation identity

Builder / Foundation rotation decision: `no rotation required for M6-001`

Current policy-pinned identity:

- Builder repository: `danielcanfly/knowledge-engine`
- Expected Builder SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Expected Automation SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Expected Foundation SHA: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`
- Rotation PR: `n/a`

If Builder or Foundation SHA changes before candidate build, M6.10 must be repeated.

## 5. Candidate identity

- Candidate channel: `candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`
- Candidate workflow run ID: `pending`
- Candidate artifact ID: `pending`
- Candidate artifact digest: `pending`
- Candidate release ID: `pending`
- Candidate manifest SHA-256: `pending`
- Candidate quality overall: `pending`

Candidate channel must be derived from the validated Source SHA.

## 6. Public acceptance

Final public query 1:

```text
What is the Knowledge Source governance boundary in Knowledge OS?
```

Expected result:

- Expected public status: `answered`
- Expected citation target: `bundle/concepts/source-governance.md` or Source-backed runtime citation target for the same concept
- Raw fallback used: `must be false`
- Acceptance result artifact: `pending`

Final public query 2:

```text
How should LLM agent architectures be reviewed across six engineering dimensions?
```

Expected result:

- Expected public status: `answered`
- Expected citation target: `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/`
- Raw fallback used: `must be false`
- Acceptance result artifact: `pending`

## 7. Boundary acceptance

Final boundary query:

```text
What candidate delivery controls are available for public users in Knowledge OS?
```

Expected result:

- Expected status: `not_found` or equivalent negative result.
- Fixture-only path not returned as public content: `bundle/concepts/candidate-delivery-controls.md`.
- Raw fallback used: `must be false`.
- Boundary result artifact: `pending`.

## 8. Candidate dispatch plan

Expected dispatch source:

- Source workflow: `danielcanfly/knowledge-source/.github/workflows/publish-candidate.yml`
- Trigger: successful `Validate Knowledge Source` workflow run on `main`
- Event type: `knowledge-source-candidate`
- Validation run ID: `28771739838`
- Candidate channel: `candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`

Expected dispatch payload identity:

- builder_ref: `1b55c68a441def01a5277c94b350efab1437459d`
- source_repository: `danielcanfly/knowledge-source`
- source_sha: `6a35f9f35e4c6c599a266710344f760c399d914d`
- foundation_sha: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`

## 9. Production request spec plan

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

## 10. Rollout assumptions

- Current production release before promotion: `20260706T024200Z-19b86982de27`
- Current production manifest before promotion: `8697f5ab6258d8545328fd32cea60b09c2c80aef4599611b0571a0553ea24a7e`
- Production precondition source: `pending workflow evidence`
- Rollback expected previous release: `20260706T024200Z-19b86982de27` unless production changes before M6-001
- Rollback evidence required: `yes`

## 11. Governance checklist

- [x] Source paths are reviewed in Engine planning evidence.
- [x] Source validation passed.
- [x] Builder / Foundation rotation decision recorded.
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

## 12. Decision

- Batch spec status: `candidate planning complete / candidate build pending`
- Reviewer: `pending`
- Decision date: `pending`
- Notes: `This spec records candidate planning inputs. It does not approve request-spec creation or production promotion.`

## 13. Next required action

Collect candidate build evidence:

- Engine candidate workflow run ID
- candidate artifact ID and digest
- candidate release ID
- candidate manifest SHA-256
- candidate quality result
- runtime acceptance artifacts for both public queries
- boundary result artifact
