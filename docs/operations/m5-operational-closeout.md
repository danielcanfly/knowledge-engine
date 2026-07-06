# M5 Operational Closeout

Status: `closed for M5.6 hardening`

This document is the operational handoff for the first governed M5 production batch and the M5.6 hardening work that followed it. It is intentionally procedural: it tells the next operator what is now safe, what remains forbidden, and how to enter the next governed production batch without relying on chat memory.

## Canonical production identity

The first governed real content batch remains the current production target unless a later governed promotion supersedes it.

- Production release ID: `20260706T024200Z-19b86982de27`
- Manifest SHA-256: `8697f5ab6258d8545328fd32cea60b09c2c80aef4599611b0571a0553ea24a7e`
- Source repository: `danielcanfly/knowledge-source`
- Source SHA: `6254725c38969e46e65aadcba13a8803b0d8a6a9`
- Builder SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Foundation SHA: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`
- Production pointer SHA-256: `e481074e1f96dac72eabcf579a087642f926aa6c4cdc13352178ee804bf6e6cf`
- Public acceptance query: `six-dimensional map of LLM agent architectures`
- Expected citation URL: `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-1/`
- ACL negative query: `quartz lantern protocol`
- Expected ACL status: `not_found`

## Permanent ledgers and tracking issues

- `#30` is the permanent append-only M5 production ledger. Keep it open. It is evidence only, not an approval surface.
- `#35` tracked M5.6 hardening. It may be closed after this closeout is merged and recorded.

Do not convert the ledger issue into a task tracker. Add evidence entries only when a governed workflow or verified manual inspection produced evidence.

## Completed hardening slices

### M5.6.1 Secret / dispatch blocker

Outcome: Source-to-Engine dispatch was repaired after the missing `KNOWLEDGE_ENGINE_DISPATCH_TOKEN` blocker was identified and resolved.

Operational effect: Source validation can trigger the downstream candidate path without manual shell-only recovery.

### M5.6.2 Builder pin separation

Outcome: Engine control-plane SHA and Builder SHA are no longer falsely coupled.

Operational effect:

- The workflow SHA is the coordinator / control-plane identity.
- The Source policy `builder_ref` is the pinned Builder identity.
- Do not reintroduce `BUILDER_REF == ENGINE_SHA` or `builder_sha == github.sha` checks.

### M5.6.3 Request-spec production promotion

Outcome: Production promotion is now driven by a committed request spec under `production_promotions/`.

Operational effect:

- The workflow UI accepts only `request_path`.
- Release identity is reviewed as code before dispatch.
- Candidate identity is revalidated at runtime from the candidate channel and manifest.
- Already-promoted replay is accepted only when all identities match exactly.
- Already-promoted replay returns `status=already_promoted` and `idempotent=true` without writing a new intent or receipt.

### M5.6.4 Automated ledger recorder

Outcome: The production promotion workflow now renders and posts a deterministic ledger entry after runtime acceptance passes.

Operational effect:

- Ledger recording happens after request validation, candidate verification, promotion or replay verification, public citation acceptance, and ACL acceptance.
- The workflow uses narrow `issues: write` permission only for the ledger comment step.
- The rendered ledger comment and response are uploaded in the evidence artifact.

### M5.6.5 Replay / rollback proof

Outcome: A dedicated replay / rollback proof workflow exists and passes on `main`.

Operational effect:

- Promotion replay before rollback is idempotent.
- Rollback restores exact previous pointer bytes.
- Rollback replay is idempotent.
- A rolled-back promotion operation cannot revive the target release.
- Re-promoting after rollback requires a new operation ID.
- Proof artifacts are retained for audit.

## Hard invariants

These invariants are non-negotiable.

1. Do not write AI-generated content directly into canonical Source or production.
2. Do not bypass human review, Source PR review, Source validation, candidate gate, or production request-spec review.
3. Do not promote production from workflow UI fields that directly specify release identity. Use a committed request spec.
4. Do not treat request specs as proof. The workflow must revalidate candidate identity at runtime.
5. Do not weaken public citation checks or ACL negative checks.
6. Do not use raw fallback as acceptance evidence.
7. Do not close or overwrite the permanent ledger issue `#30`.
8. Do not reuse a rolled-back promotion operation to revive a target release.
9. Do not couple Builder SHA to Engine control-plane SHA.
10. Do not change the R2-backed production pointer without promotion / rollback evidence.

## Next governed production batch entry protocol

Use this protocol for the next real content batch.

### 1. Source preparation

Prepare content in the source repository through normal reviewable changes. The canonical Source repository is the authority for governed Source content.

Required evidence:

- Source PR number
- Source commit SHA
- Review status
- Source validation workflow run ID
- Source policy values, especially builder SHA, foundation SHA, candidate channel, and acceptance query

### 2. Source validation

Run or observe Source validation on `main`. Do not proceed if Source validation is missing, failed, or only partially inspected.

Required result:

- Source validation conclusion: `success`
- Source SHA matches the reviewed Source commit
- Dispatch evidence identifies the downstream Engine candidate workflow

### 3. Candidate build and gate

The candidate workflow must build from exact Source and Builder identities. It must publish to a candidate channel, not production.

Required result:

- Candidate workflow conclusion: `success`
- Candidate release ID recorded
- Candidate manifest SHA-256 recorded
- Source SHA, Builder SHA, Foundation SHA recorded
- Candidate quality overall: `passed`
- Runtime acceptance query passes
- ACL negative query passes when applicable

### 4. Production request spec

Create or update a request spec under `production_promotions/`.

Required fields include:

- `schema_version`
- `operation_id`
- `candidate_channel`
- `release_id`
- `manifest_sha256`
- `source_repository`
- `source_sha`
- `builder_sha`
- `foundation_sha`
- `expected_previous_release_id`
- `expected_previous_manifest_sha256`
- `reason`
- `actor`
- `post_promote_public_query`
- `expected_public_status`
- `expected_citation_url`
- optional ACL query and expected ACL status

Forbidden field:

- `control_plane_sha` must not be committed in the request spec. It is injected by the workflow runtime.

### 5. Production promotion dispatch

Dispatch the production workflow by request path only.

Example:

```bash
gh workflow run m5-production-promotion.yml \
  --repo danielcanfly/knowledge-engine \
  --ref main \
  -f request_path=production_promotions/<request>.json
```

Required result:

- Request validation: success
- Current production precondition checked
- Candidate identity verified from candidate channel and manifest
- Promotion result is either `promoted` or exact-match `already_promoted`
- Runtime refresh returns the requested release
- Public query returns expected status and expected citation URL
- Raw fallback is false
- ACL query returns expected negative status when configured
- Automated ledger comment is posted to `#30`
- Evidence artifact contains request, normalized request, candidate identity, promotion result, runtime acceptance, ledger comment, and ledger response

### 6. Replay / rollback proof

Before scaling the next batch family, keep the replay / rollback proof workflow green on `main`.

Required result:

- `M5 Replay Rollback Proof`: success
- `CI`: success
- `R2 Release Integration`: success

## Closeout checklist for the operator

Before declaring a governed batch closed, verify all of the following:

- The production release ID and manifest SHA-256 are recorded.
- The Source SHA, Builder SHA, Foundation SHA, and control-plane SHA are recorded.
- The production pointer SHA-256 is recorded.
- Public acceptance query status is recorded.
- Expected citation URL appears in the public query result.
- Raw fallback is false.
- ACL negative query status is recorded when applicable.
- Automated ledger entry exists in `#30`.
- Evidence artifact is downloadable and contains the expected JSON files.
- Any hardening tracker issue is closed only after evidence is posted.
- `#30` remains open.

## Failure handling

### If candidate identity mismatches

Stop. Do not edit production request fields in the workflow UI. Fix Source policy, Builder pin, or candidate channel identity through a reviewed commit, then rerun the candidate path.

### If production precondition fails

Stop. Inspect `channels/production.json` and the previous release expected by the request spec. Create a new request spec if production legitimately moved.

### If the target is already production

Use the exact-match replay path. It must return:

- `status=already_promoted`
- `idempotent=true`
- no new promotion intent
- no new promotion receipt

### If public citation acceptance fails

Stop. Do not promote based on answer text alone. The expected citation URL must appear, and raw fallback must be false.

### If ACL acceptance fails

Stop. Do not promote. The negative query must stay unauthorized, and raw fallback must be false.

### If rollback is needed

Rollback must use existing promotion intent evidence and exact pointer hashes. After rollback, the old promotion operation must not be reused to revive the target. Any recovery promotion requires a new operation ID.

## M6 entry note

M6 may increase content volume only after this closeout remains green on `main`. Scaling content should not change the governance envelope. The next work should focus on batch ergonomics, evidence summarization, and reducing operator copy-paste, not weakening review gates.
