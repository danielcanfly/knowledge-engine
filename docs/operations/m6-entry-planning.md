# M6 Entry Planning Runbook

Status: `planning`

Tracking issue: `#42`

Child slice: `#43`

This runbook starts M6 without changing production state. M6 must begin by making the next governed batch explicit, reviewable, and replayable. Do not use this document as approval to create Source content or promote a release.

## Purpose

M5 proved the end-to-end governed path for one real content batch. M5.6 hardened the workflow. M5.7 closed the loop with a repo-local operational closeout. M6 now prepares the next batch by defining the batch contract before any larger content volume is introduced.

## Current production baseline

The current production baseline remains the first governed M5 production release until a later governed promotion supersedes it.

- Production release ID: `20260706T024200Z-19b86982de27`
- Manifest SHA-256: `8697f5ab6258d8545328fd32cea60b09c2c80aef4599611b0571a0553ea24a7e`
- Source SHA: `6254725c38969e46e65aadcba13a8803b0d8a6a9`
- Builder SHA: `1b55c68a441def01a5277c94b350efab1437459d`
- Foundation SHA: `d12c7c416c950d743d4cd5e7964fd3c3bc0d9062`
- Permanent ledger: `#30`
- M5 closeout doc: `docs/operations/m5-operational-closeout.md`

## M6 entry rule

M6 entry is complete only when the next batch has a reviewed batch spec and a candidate evidence summary path. M6 execution begins later, after the spec is accepted.

## Required artifacts

1. `docs/templates/m6-batch-spec-template.md`
2. `docs/templates/m6-candidate-evidence-summary-template.md`
3. A concrete batch spec for the next Source batch, created from the template.
4. Candidate evidence summary, created after Source validation and candidate workflow execution.
5. Production request spec only after candidate evidence is complete and reviewed.

## Operator sequence

### 1. Create a batch spec

Copy `docs/templates/m6-batch-spec-template.md` and fill in the next batch identity.

Required decisions:

- batch ID
- content scope
- Source repository and branch
- Source PR number
- expected Source SHA after review
- expected Builder SHA
- expected Foundation SHA
- candidate channel
- public acceptance query
- expected citation URL
- ACL negative query, if applicable
- rollback assumptions

Do not create or approve Source content as part of this step.

### 2. Review Source changes

Source changes must go through a Source PR. Do not place generated content directly into canonical Source or production.

Required evidence:

- Source PR URL
- Source review decision
- merged Source SHA
- Source validation workflow run ID
- Source validation conclusion

### 3. Run candidate path

The candidate workflow must publish a candidate release, not production.

Required evidence:

- candidate workflow run ID
- candidate channel
- candidate release ID
- candidate manifest SHA-256
- Source SHA
- Builder SHA
- Foundation SHA
- public query result
- expected citation URL present
- raw fallback false
- ACL negative status, if applicable
- ACL raw fallback false

### 4. Produce candidate evidence summary

Copy `docs/templates/m6-candidate-evidence-summary-template.md` and fill it from actual workflow artifacts. Do not rely on memory or chat-only evidence.

### 5. Create production request spec

Only after candidate evidence is reviewed, create or update a request spec under `production_promotions/`.

The request spec must not include `control_plane_sha`. The production promotion workflow injects runtime control-plane identity.

### 6. Dispatch production promotion

Dispatch by request path only:

```bash
gh workflow run m5-production-promotion.yml \
  --repo danielcanfly/knowledge-engine \
  --ref main \
  -f request_path=production_promotions/<request>.json
```

Required evidence after dispatch:

- request validation success
- current production precondition checked
- candidate identity verified from candidate channel and manifest
- promotion status `promoted` or exact-match `already_promoted`
- public query expected status
- expected citation URL present
- raw fallback false
- ACL expected status, if configured
- ACL raw fallback false
- automated ledger comment posted to `#30`
- evidence artifact downloadable

## Hard stops

Stop immediately if any of the following happens:

- Source validation fails or is missing.
- Candidate workflow does not prove exact Source / Builder / Foundation identity.
- Candidate quality is not `passed`.
- Public query uses raw fallback.
- Expected citation URL is missing.
- ACL negative query leaks authorized-only content.
- Production request spec contains `control_plane_sha`.
- Production workflow asks for release identity through UI fields instead of request path.
- Ledger comment to `#30` is missing after production workflow success.

## M6 readiness check

Before moving beyond planning:

- `#42` remains open as the M6 parent tracker.
- `#43` is closed only after templates are merged.
- `#30` remains open.
- `docs/operations/m5-operational-closeout.md` remains on `main`.
- `M5 Replay Rollback Proof` is green on `main`.
- `R2 Release Integration` is green on `main`.
- Production promotion remains request-spec driven.
- Automated ledger recorder remains active.

## Out of scope for M6 entry planning

- Approving new Source content.
- Promoting a new production release.
- Increasing content volume.
- Relaxing review gates.
- Weakening citation, ACL, replay, or rollback checks.
