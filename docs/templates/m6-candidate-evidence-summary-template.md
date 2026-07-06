# M6 Candidate Evidence Summary Template

Status: `draft`

Parent tracker: `#42`

Use this template after Source validation and candidate workflow execution. It summarizes actual evidence before a production request spec is created.

## 1. Summary

- Batch ID: `<m6-batch-id>`
- Source PR: `<url>`
- Engine PR: `<url or n/a>`
- Candidate workflow run: `<url>`
- Candidate artifact: `<url / artifact id>`
- Summary author: `<name or GitHub handle>`
- Summary date: `<YYYY-MM-DD>`
- Decision: `<ready for production request spec / blocked / needs review>`

## 2. Source validation evidence

- Source repository: `danielcanfly/knowledge-source`
- Source branch: `<branch>`
- Source SHA: `<40-char sha>`
- Source validation run ID: `<run id>`
- Source validation conclusion: `<success / failure>`
- Source validation artifact ID: `<artifact id or n/a>`
- Source validation artifact digest: `<sha256:... or n/a>`

Required result: Source validation must be `success`.

## 3. Builder / Foundation evidence

- Builder repository: `danielcanfly/knowledge-engine`
- Builder SHA: `<40-char sha>`
- Foundation SHA: `<40-char sha>`
- Builder pin source: `<Source policy / request / artifact>`
- Pin rotation PR: `<url or n/a>`
- Pin mismatch observed: `<yes / no>`

Required result: Builder and Foundation identity must match Source policy and candidate manifest.

## 4. Candidate release evidence

- Candidate channel: `<candidate-channel>`
- Candidate workflow run ID: `<run id>`
- Candidate workflow conclusion: `<success / failure>`
- Candidate artifact ID: `<artifact id>`
- Candidate artifact digest: `<sha256:...>`
- Candidate release ID: `<release id>`
- Candidate manifest SHA-256: `<sha256>`
- Candidate manifest key: `<object-store key>`
- Candidate quality overall: `<passed / failed>`

Required result: candidate workflow must be `success` and quality must be `passed`.

## 5. Runtime public acceptance

- Public query: `<query>`
- Expected public status: `<answered / not_found>`
- Actual public status: `<answered / not_found>`
- Expected citation URL: `<url>`
- Citation URLs returned:
  - `<url 1>`
  - `<url 2>`
- Citation count: `<number>`
- Raw fallback used: `<true / false>`
- Result artifact file: `<file>`

Required result:

- Actual status matches expected status.
- Expected citation URL is present when expected status is `answered`.
- Raw fallback is `false`.

## 6. ACL negative acceptance

- ACL query: `<query or n/a>`
- Expected ACL status: `<not_found / n/a>`
- Actual ACL status: `<not_found / n/a>`
- ACL filtered count: `<number or n/a>`
- Raw fallback used: `<true / false / n/a>`
- Result artifact file: `<file or n/a>`

Required result when ACL query is configured:

- Actual ACL status matches expected ACL status.
- Raw fallback is `false`.
- Unauthorized content is not returned.

## 7. Candidate identity cross-check

- Manifest Source repository: `<repository>`
- Manifest Source SHA: `<sha>`
- Manifest Builder SHA: `<sha>`
- Manifest Foundation SHA: `<sha>`
- Candidate channel release ID: `<release id>`
- Candidate channel manifest SHA-256: `<sha256>`
- Request-spec target release ID candidate: `<release id>`
- Request-spec target manifest SHA-256 candidate: `<sha256>`

All values must match before creating a production request spec.

## 8. Production request-spec readiness

- Request spec path: `production_promotions/<request>.json`
- Operation ID: `<operation-id>`
- Expected previous release ID: `<release id>`
- Expected previous manifest SHA-256: `<sha256>`
- Target release ID: `<release id>`
- Target manifest SHA-256: `<sha256>`
- Public query: `<query>`
- Expected citation URL: `<url>`
- ACL query: `<query or n/a>`
- Expected ACL status: `<not_found or n/a>`

Do not include `control_plane_sha` in the committed request spec.

## 9. Blockers

List blockers or write `none`.

- `<blocker>`

## 10. Reviewer decision

- Reviewer: `<name or GitHub handle>`
- Decision: `<approved for production request spec / request changes / blocked>`
- Decision date: `<YYYY-MM-DD>`
- Notes: `<notes>`
