# M6 Batch Spec Template

Status: `draft`

Parent tracker: `#42`

Use this template for the next governed Source batch. Copy it into a concrete batch spec file before Source execution. Do not use the template itself as approval.

## 1. Batch identity

- Batch ID: `<m6-batch-id>`
- Batch title: `<human readable title>`
- Owner / operator: `<name or GitHub handle>`
- Created at: `<YYYY-MM-DD>`
- Parent issue: `#42`
- Child issue: `<issue number>`
- Related Source PR: `<url or pending>`
- Related Engine PR: `<url or pending>`

## 2. Scope

### Included content

- `<content item 1>`
- `<content item 2>`

### Excluded content

- `<explicitly out-of-scope item 1>`
- `<explicitly out-of-scope item 2>`

### Risk notes

- `<risk or ambiguity>`

## 3. Source identity

- Source repository: `danielcanfly/knowledge-source`
- Source branch: `<branch>`
- Source PR: `<url>`
- Expected Source SHA after merge: `<40-char sha>`
- Source validation workflow run ID: `<run id>`
- Source validation conclusion: `<success / failure / pending>`

## 4. Builder and Foundation identity

- Builder repository: `danielcanfly/knowledge-engine`
- Expected Builder SHA: `<40-char sha>`
- Expected Foundation SHA: `<40-char sha>`
- Builder / Foundation rotation required: `<yes / no>`
- Rotation PR: `<url or n/a>`

If Builder or Foundation SHA changes, the rotation must be reviewable and must fail loudly if Source policy and Engine expectations diverge.

## 5. Candidate identity

- Candidate channel: `<candidate-channel>`
- Candidate workflow run ID: `<run id>`
- Candidate artifact ID: `<artifact id>`
- Candidate artifact digest: `<sha256:...>`
- Candidate release ID: `<release id>`
- Candidate manifest SHA-256: `<sha256>`
- Candidate quality overall: `<passed / failed / pending>`

## 6. Public acceptance

- Public query: `<query>`
- Expected public status: `<answered / not_found>`
- Expected citation URL: `<url>`
- Citation count: `<number>`
- Raw fallback used: `<true / false>`
- Acceptance result artifact: `<path or artifact file>`

Acceptance requires the expected citation URL and raw fallback must be `false`.

## 7. ACL negative acceptance

- ACL negative query: `<query or n/a>`
- Expected ACL status: `<not_found / n/a>`
- ACL filtered count: `<number or n/a>`
- ACL raw fallback used: `<true / false / n/a>`
- ACL result artifact: `<path or artifact file>`

If ACL negative query is configured, acceptance requires the expected status and raw fallback must be `false`.

## 8. Production request spec plan

- Request spec path: `production_promotions/<request>.json`
- Operation ID: `<operation-id>`
- Expected previous release ID: `<release id>`
- Expected previous manifest SHA-256: `<sha256>`
- Target release ID: `<release id>`
- Target manifest SHA-256: `<sha256>`
- Actor: `<GitHub handle>`
- Reason: `<short reason>`

Forbidden field:

- `control_plane_sha` must not be committed in the request spec.

## 9. Rollout assumptions

- Current production release before promotion: `<release id>`
- Current production manifest before promotion: `<sha256>`
- Production precondition source: `<artifact / command output>`
- Rollback expected previous release: `<release id>`
- Rollback evidence required: `<yes / no>`

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

- Batch spec status: `<draft / ready for Source PR / blocked / superseded>`
- Reviewer: `<name or GitHub handle>`
- Decision date: `<YYYY-MM-DD>`
- Notes: `<notes>`
