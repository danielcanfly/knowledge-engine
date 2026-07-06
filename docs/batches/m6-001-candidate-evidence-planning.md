# M6-001 Candidate Evidence Planning

Status: `candidate planning complete / candidate build pending`

Parent tracker: `#42`

Child slice: `#59`

Batch spec: `docs/batches/m6-001-llm-wiki-foundation-batch.md`

Source validation evidence: `docs/batches/m6-001-source-validation-evidence.md`

This planning document locks the candidate evidence inputs for `m6-001-llm-wiki-foundation`. It does not run a candidate build, create a production request spec, or change production state.

## 1. Source identity

- Source repository: `danielcanfly/knowledge-source`
- Source branch: `main`
- Source SHA: `6a35f9f35e4c6c599a266710344f760c399d914d`
- Source validation run ID: `28771739838`
- Source validation conclusion: `success`
- Source validation artifact ID: `8101046344`
- Source validation artifact digest: `sha256:d8012852c831df3b16ef46ea2b0849783dfb169ce9c3e3f0862e0f222114acfa`

## 2. Builder / Foundation rotation decision

No Builder / Foundation rotation is required for M6-001.

Source policy at the reviewed Source SHA records:

- Builder repository: `danielcanfly/knowledge-engine`
- Builder SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Automation SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Foundation repository: `danielcanfly/knowledge-os-foundation`
- Foundation SHA: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`
- Candidate channel prefix: `candidate-source-`
- Dispatch event type: `knowledge-source-candidate`

The Source validation workflow also installs the pinned Builder and checks the Builder SHA before preview build. M6-001 should therefore use the policy-pinned Builder / Foundation identity above.

## 3. Candidate dispatch plan

Candidate dispatch is expected to be triggered by `danielcanfly/knowledge-source` workflow automation after successful Source validation on `main`.

Dispatch source workflow:

- Repository: `danielcanfly/knowledge-source`
- Workflow: `.github/workflows/publish-candidate.yml`
- Workflow name: `Publish Source Candidate`
- Trigger: successful `Validate Knowledge Source` workflow run
- Required workflow_run conditions:
  - event: `push`
  - head_branch: `main`
  - conclusion: `success`

Expected dispatch payload values:

- event type: `knowledge-source-candidate`
- builder_ref: `1b55c68a441def01a5277c94b350efab1437459d`
- source_repository: `danielcanfly/knowledge-source`
- source_sha: `6a35f9f35e4c6c599a266710344f760c399d914d`
- validation_run_id: `28771739838`
- foundation_sha: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`
- candidate_channel: `candidate-source-6a35f9f35e4c6c599a266710344f760c399d914d`

Candidate build must not be considered complete until Engine-side candidate workflow evidence is recorded.

## 4. Final public acceptance queries

### Public query 1

```text
What is the Knowledge Source governance boundary in Knowledge OS?
```

Expected result:

- status: `answered`
- expected citation target: `bundle/concepts/source-governance.md` or a Source-backed runtime citation target for the same concept
- raw fallback: `false`

### Public query 2

```text
How should LLM agent architectures be reviewed across six engineering dimensions?
```

Expected result:

- status: `answered`
- expected citation target: `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/`
- raw fallback: `false`

## 5. Final boundary query

```text
What candidate delivery controls are available for public users in Knowledge OS?
```

Expected result:

- status: `not_found` or equivalent negative result
- expected fixture path not returned as public content: `bundle/concepts/candidate-delivery-controls.md`
- raw fallback: `false`

## 6. Candidate evidence required after build

After the candidate build runs, record:

- Engine candidate workflow run ID
- Engine candidate workflow conclusion
- candidate artifact ID
- candidate artifact digest
- candidate release ID
- candidate manifest SHA-256
- candidate source snapshot SHA-256 if available
- final public query 1 artifact
- final public query 2 artifact
- final boundary query artifact
- raw fallback flags for all runtime checks
- reviewer decision

## 7. Non-authorization

This document does not authorize production promotion. It only finalizes candidate planning inputs so that the next M6 step can collect candidate build evidence.
