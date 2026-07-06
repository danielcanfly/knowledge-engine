# M6-001 Candidate Build Evidence

Status: `candidate build evidence collected / runtime acceptance required`

Parent tracker: `#42`

Child slice: `#60`

Batch spec: `docs/batches/m6-001-llm-wiki-foundation-batch.md`

Candidate planning: `docs/batches/m6-001-candidate-evidence-planning.md`

This document records candidate build evidence for `m6-001-llm-wiki-foundation`. It does not record final runtime acceptance for the M6.10 public queries, does not create a production request spec, and does not authorize production promotion.

## 1. Source identity

- Source repository: `danielcanfly/knowledge-source`
- Source SHA: `6a35f9f35e4c6c599a266710344f760c399d914d`
- Source validation run ID: `28771739838`
- Source validation conclusion: `success`
- Source validation artifact ID: `8101046344`
- Source validation artifact digest: `sha256:d8012852c831df3b16ef46ea2b0849783dfb169ce9c3e3f0862e0f222114acfa`

## 2. Source dispatch evidence

- Source dispatch repository: `danielcanfly/knowledge-source`
- Source dispatch workflow run ID: `28771761112`
- Source dispatch job ID: `85306738884`
- Source dispatch job name: `dispatch-candidate`
- Source dispatch job conclusion: `success`
- Source dispatch artifact ID: `8101049916`
- Source dispatch artifact name: `source-candidate-dispatch-6a35f9f35e4c6c599a266710344f760c399d914d`
- Source dispatch artifact digest: `sha256:9b1af24f8d8e6e0378d8d4ed4fe25942e6bdac03b06ec684fdf19570a1abf91d`
- Source dispatch artifact expired: `false`
- Source dispatch artifact head SHA: `6a35f9f35e4c6c599a266710344f760c399d914d`

Dispatch payload verified from artifact:

- event type: `knowledge-source-candidate`
- builder_ref: `1b55c68a441def01a5277c94b350efab1437459d`
- source_repository: `danielcanfly/knowledge-source`
- source_sha: `6a35f9f35e4c6c599a266710344f760c399d914d`
- validation_run_id: `28771739838`
- foundation_sha: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`
- candidate_channel: `candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`
- dispatch HTTP status: `204`

## 3. Engine candidate workflow evidence

- Engine repository: `danielcanfly/knowledge-engine`
- Engine candidate workflow run ID: `28771769531`
- Engine candidate workflow conclusion: `success`
- Engine candidate artifact ID: `8101061363`
- Engine candidate artifact name: `source-candidate-6a35f9f35e4c6c599a266710344f760c399d914d`
- Engine candidate artifact digest: `sha256:ab824a8284a78f6e5c38d547aa89ba119beb2c53084640a40512f9bf0c13ca52`
- Engine candidate artifact expired: `false`
- Engine candidate workflow head SHA: `16dd26a00e2f86566e49d200a1912db06b8646e3`

Successful Engine candidate jobs:

- `validate-dispatch`
- `publish-candidate`
- `record-evidence`

Successful `publish-candidate` steps included:

- Validate Engine production secret boundary
- Check out pinned Knowledge Engine
- Install pinned Builder
- Verify successful Source validation run
- Check out exact private Source revision
- Verify Source checkout and delivery policy
- Build, publish, and gate candidate
- Collect candidate evidence
- Upload candidate evidence

## 4. Candidate build identity

Verified from candidate workflow logs and artifact:

- Builder SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Source repository: `danielcanfly/knowledge-source`
- Source SHA: `6a35f9f35e4c6c599a266710344f760c399d914d`
- Validation run ID: `28771739838`
- Foundation SHA: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`
- Candidate channel: `candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`

## 5. Candidate artifact contents

Downloaded artifact:

- `m6-001-source-candidate-6a35f9.zip`

Artifact files inspected:

- `manifest.json`
- `source-candidate-gate.json`
- `job-status.txt`
- `source-snapshot.json`
- `source-validation-run.json`

Candidate gate result:

- `job-status.txt`: `candidate gate passed`
- release ID: `20260706T061437Z-bc48bf4810c0`
- manifest SHA-256: `8eefb904d1eea0f6ca87b074c60edfe94c725bd76adb77961919b8d2bd4c8f96`
- source snapshot SHA-256: `40fa745903096660150c75ca7fe0d272e90367428e72d9d8e6245bb2ab0cc4d8`
- release tree SHA-256: `7b7cb7dabbc499df1228d6e2624ea998978cb3ecc618d025fa9b8694e528c261`
- reproducibility passed: `true`
- production pointer unchanged: `true`

Built-in candidate gate checks:

- internal status: `answered`
- internal result count: `1`
- internal citation count: `1`
- public status: `not_found`
- public result count: `0`
- public ACL filtered count: `1`

## 6. Important limitation

The built-in candidate gate used the Source policy acceptance query available at candidate-build time.

That built-in query is not the same as the final M6.10 public runtime queries:

```text
What is the Knowledge Source governance boundary in Knowledge OS?
```

```text
How should LLM agent architectures be reviewed across six engineering dimensions?
```

Therefore this document proves candidate build and built-in candidate gate success, but it does not prove final runtime acceptance for the M6.10 query set.

## 7. Candidate decision

- Candidate build evidence status: `collected / passed`
- Runtime acceptance status: `pending`
- Production promotion status: `not authorized`

## 8. Next required action

Run candidate runtime acceptance for the final M6.10 queries and record:

- public query 1 result artifact
- public query 1 citation evidence
- public query 1 raw fallback flag
- public query 2 result artifact
- public query 2 citation evidence
- public query 2 raw fallback flag
- boundary query result artifact
- boundary raw fallback flag
