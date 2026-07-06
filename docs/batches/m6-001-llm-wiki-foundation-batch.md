# M6-001 Batch Spec: LLM Wiki Foundation

Status: `runtime acceptance workflow pending`

Parent tracker: `#42`

Child slices: `#45`, `#56`, `#57`, `#59`, `#60`, `#62`

This is the first named M6 batch spec. It references reviewed Source paths, Source validation evidence, candidate evidence planning, and candidate build evidence. It does not edit Source, does not create a production request spec, and does not authorize production promotion.

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
- Candidate build evidence issue: `#60`
- Runtime acceptance issue: `#62`
- Source PR: `not required yet / selected content already exists on Source main`
- Related Engine PRs: `#54`, `#55`, `#56`, `#58`, `#59`, `#61`, `pending #62`

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
- Candidate build evidence has been collected and passed.
- Runtime acceptance workflow is prepared; final runtime artifacts are still pending.
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
- Candidate workflow run ID: `28771769531`
- Candidate artifact ID: `8101061363`
- Candidate artifact digest: `sha256:ab824a8284a78f6e5c38d547aa89ba119beb2c53084640a40512f9bf0c13ca52`
- Candidate release ID: `20260706T061437Z-bc48bf4810c0`
- Candidate manifest SHA-256: `8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96`
- Candidate source snapshot SHA-256: `40fa745903096660150c75ca7fe0d272e90367428e72d9d8e6245bb2ab0cc4d8`
- Candidate release tree SHA-256: `7b7cb7dabbc499df1228d6e2624ea998978cb3ecc618d025fa9b8694e528c261`
- Candidate quality overall: `passed`
- Reproducibility passed: `true`
- Production pointer unchanged: `true`

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

## 9. Candidate build evidence

Source dispatch:

- Source dispatch run ID: 28771761112
- Source dispatch job ID: 85306738884
- Source dispatch conclusion: success
- Source dispatch artifact ID: 8101049916
- Source dispatch artifact digest: sha256:9b1af24f8d8e6e0378d8d4ed4fe25942e6bdac03b06ec684fdf19570a1abf91d
- Source dispatch HTTP status: 204

Engine candidate workflow:

- Engine candidate run ID: 28771769531
- Engine candidate conclusion: success
- Candidate artifact ID: 8101061363
- Candidate artifact digest: sha256:ab824a8284a78f6e5c38d547aa89ba119beb2c53084640a40512f9bf0c13ca52

Built-in candidate gate:

- internal status: answered
- internal citation count: 1
- public status: not_found
- public ACL filtered count: 1

Important limitation:

- Built-in candidate gate evidence does not replace final runtime acceptance for the M6.10 public query set.

## 10. Production request spec plan

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

## 11. Rollout assumptions

- Current production release before promotion: `20260706T024200Z-19b86982de27`
- Current production manifest before promotion: `8697f5ab6258d8545328fd32cea60b09c2c80aef4599611b0571a0553ea24a7e`
- Production precondition source: `pending workflow evidence`
- Rollback expected previous release: `20260706T024200Z-19b86982de27` unless production changes before M6-001
- Rollback evidence required: `yes`

## 12. Governance checklist

- [x] Source paths are reviewed in Engine planning evidence.
- [x] Source validation passed.
- [x] Builder / Foundation rotation decision recorded.
- [x] Candidate identity is verified from candidate channel and manifest.
- [x] Candidate quality is `passed`.
- [ ] Public query expected citation target is present.
- [ ] Public raw fallback is `false`.
- [ ] Boundary query passes if configured.
- [ ] Boundary raw fallback is `false` if configured.
- [ ] Production identity is committed in request spec.
- [ ] Production workflow is dispatched by `request_path` only.
- [ ] Automated ledger comment to `#30` is expected after production workflow success.
- [ ] Replay / rollback proof remains green on `main`.

## 13. Decision

- Batch spec status: `runtime acceptance workflow pending`
- Reviewer: `pending`
- Decision date: `pending`
- Notes: `This spec records candidate build evidence and M6.12 runtime acceptance workflow planning. It does not approve request-spec creation or production promotion.`

## 14. Next required action

Collect runtime acceptance evidence:

- final public query 1 result artifact
- final public query 1 citation evidence
- final public query 1 raw fallback flag
- final public query 2 result artifact
- final public query 2 citation evidence
- final public query 2 raw fallback flag
- final boundary query result artifact
- final boundary raw fallback flag
